#!/usr/bin/env python3
"""
个人知识库（4 份真实材料）检索评测。

评测对象：
- backend/benchmark/personal_kb_golden.json 的 38 条人工 golden；
- 只评检索，不评生成；refusal / report_conflict 类不混入 Hit@K 分母；
- 标准指标：Success@3、P@3、Recall@3、RR@3、nDCG@3（由 ir_measures 计算）；
- 兼容指标：evidence_all@3（严格：每条 gold_evidence 都出现在 top3 正文）、
  evidence_any@3、evidence_any_rr、文件命中、检索延迟；
- 参数：vector / fulltext / hybrid 三种模式；hybrid 权重扫描；BM25 k1/b 扫描。

用法：
    cd backend
    JWT_SECRET=... python3 benchmark/eval_personal_kb.py
    JWT_SECRET=... python3 benchmark/eval_personal_kb.py --limit 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

BACKEND_DIR = Path(__file__).resolve().parent.parent
ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlmodel import Session, select  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.database import engine  # noqa: E402
from app.models import DocumentChunk, FileDocument, KnowledgeBase  # noqa: E402
from app.services.bm25 import BM25Index  # noqa: E402
from app.services.retrieval import RetrievalService, normalize_scores  # noqa: E402
from benchmark.metrics import (  # noqa: E402
    build_qrels,
    is_retrieval_case,
    results_to_run,
    split_cases,
    standard_metrics,
)

settings = get_settings()
engine.echo = False

KB_ID = "6d3e18a1-f70a-4acc-80a6-65eaea9a7a69"
GOLDEN_PATH = BACKEND_DIR / "benchmark" / "personal_kb_golden.json"
OUT_JSON = BACKEND_DIR / "benchmark" / "personal_kb_eval.json"
OUT_MD = BACKEND_DIR / "benchmark" / "personal_kb_report.md"
# 真实文件名只放在本地 ignored 映射里；golden 使用 resume.pdf / resume.docx 别名。
PERSONAL_FILES_LOCAL = BACKEND_DIR / "benchmark" / "personal_kb_files.local.json"


def _load_file_aliases() -> Dict[str, str]:
    if not PERSONAL_FILES_LOCAL.exists():
        return {}
    try:
        return json.loads(PERSONAL_FILES_LOCAL.read_text(encoding="utf-8"))
    except Exception:
        return {}


FILE_ALIASES = _load_file_aliases()


def _resolve_file_alias(name: Optional[str]) -> Optional[str]:
    if not name:
        return name
    return FILE_ALIASES.get(name, name)

HYBRID_WEIGHTS = [
    (0.2, 0.8),
    (0.4, 0.6),
    (0.5, 0.5),
    (0.6, 0.4),
    (0.7, 0.3),
    (0.8, 0.2),
]
BM25_GRID = [
    (1.2, 0.50),
    (1.2, 0.75),
    (1.2, 0.90),
    (1.5, 0.50),
    (1.5, 0.75),
    (1.5, 0.90),
    (2.0, 0.50),
    (2.0, 0.75),
    (2.0, 0.90),
]


def _joined(results: List[Dict[str, Any]]) -> str:
    return "\n".join(r.get("content", "") for r in results)


def _evidence_hits(results: List[Dict[str, Any]], evidence: List[str]) -> int:
    text = _joined(results)
    return sum(1 for item in evidence if item in text)


def _metrics_at_k(
    results: List[Dict[str, Any]],
    evidence: List[str],
    gold_file: Optional[str],
    k: int,
) -> Dict[str, Any]:
    top = results[:k]
    hits = _evidence_hits(top, evidence)
    any_hit = hits > 0
    all_hit = bool(evidence) and hits == len(evidence)
    file_hit = bool(gold_file) and any(r.get("file_name") == gold_file for r in top)

    rr = 0.0
    for rank, row in enumerate(results, start=1):
        text = row.get("content", "")
        if any(item in text for item in evidence):
            rr = 1.0 / rank
            break

    return {
        "hits": hits,
        "evidence_count": len(evidence),
        "evidence_any": any_hit,
        "evidence_all": all_hit,
        "file_hit": file_hit,
        "rr": rr,
    }


def _aggregate(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(rows)
    if n == 0:
        return {}
    latencies = [r["latency_ms"] for r in rows]
    return {
        "cases": n,
        "evidence_all@3": round(sum(r["k3"]["evidence_all"] for r in rows) / n, 4),
        "evidence_any@3": round(sum(r["k3"]["evidence_any"] for r in rows) / n, 4),
        "evidence_all@1": round(sum(r["k1"]["evidence_all"] for r in rows) / n, 4),
        "file_hit@3": round(sum(r["k3"]["file_hit"] for r in rows) / n, 4),
        "mrr": round(sum(r["k3"]["rr"] for r in rows) / n, 4),
        "latency_ms_mean": round(statistics.mean(latencies), 1),
        "latency_ms_p50": round(statistics.median(latencies), 1),
        "latency_ms_p95": round(
            sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)], 1
        ),
    }


def _fuse(
    svc: RetrievalService,
    session: Session,
    vector_results: List[Dict[str, Any]],
    bm25_results: List[Dict[str, Any]],
    vector_weight: float,
    bm25_weight: float,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    vector_scores = normalize_scores({r["id"]: r["score"] for r in vector_results})
    bm25_scores = normalize_scores(
        {(r.get("chunk_id") or r["id"]): r["bm25_score"] for r in bm25_results}
    )
    fused = {
        chunk_id: vector_weight * vector_scores.get(chunk_id, 0.0)
        + bm25_weight * bm25_scores.get(chunk_id, 0.0)
        for chunk_id in set(vector_scores) | set(bm25_scores)
    }
    sorted_ids = sorted(fused.items(), key=lambda item: item[1], reverse=True)[:top_k]
    raw = {r["id"]: r for r in vector_results}
    raw.update({(r.get("chunk_id") or r["id"]): r for r in bm25_results})
    merged = []
    for chunk_id, score in sorted_ids:
        source = raw.get(chunk_id, {})
        merged.append(
            {
                "id": chunk_id,
                "score": score,
                "vector_score": vector_scores.get(chunk_id, 0.0),
                "bm25_score": bm25_scores.get(chunk_id, 0.0),
                "kb_id": source.get("kb_id", KB_ID),
            }
        )
    return svc._enrich_results(session, merged)


def _case_for_retrieval(case: Dict[str, Any]) -> bool:
    """只把 behavior=answer 的题算进检索指标。

    refuse 评的是生成端拒答；report_conflict 需要跨 chunk 取证，
    用单 chunk 的 evidence_all 计算会系统性压低分数。
    """
    return is_retrieval_case(case)


def main() -> int:
    global KB_ID, GOLDEN_PATH, OUT_JSON, OUT_MD

    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 条，用于冒烟")
    parser.add_argument("--kb-id", default=KB_ID, help="要评测的知识库 ID")
    parser.add_argument("--golden", default=str(GOLDEN_PATH), help="golden JSON 路径")
    parser.add_argument("--out-json", default=str(OUT_JSON), help="输出 JSON 路径")
    parser.add_argument("--out-md", default=str(OUT_MD), help="输出 Markdown 路径")
    args = parser.parse_args()

    KB_ID = args.kb_id
    GOLDEN_PATH = Path(args.golden).resolve()
    OUT_JSON = Path(args.out_json).resolve()
    OUT_MD = Path(args.out_md).resolve()

    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    cases = golden["cases"]
    if args.limit:
        cases = cases[: args.limit]

    with Session(engine) as session:
        kb = session.get(KnowledgeBase, KB_ID)
        if kb is None:
            print(f"[错误] PostgreSQL 中找不到个人知识库 {KB_ID}，先跑 migrate_personal_kb.py", file=sys.stderr)
            return 2
        chunk_rows = session.exec(
            select(DocumentChunk)
            .join(FileDocument, DocumentChunk.file_id == FileDocument.id)
            .where(FileDocument.kb_id == KB_ID)
        ).all()
        chunk_count = len(chunk_rows)
        chunk_text_by_id = {row.id: row.content for row in chunk_rows}

        svc = RetrievalService()
        case_rows: List[Dict[str, Any]] = []
        runs_by_mode: Dict[str, Dict[str, Dict[str, float]]] = {
            mode: {} for mode in ("vector", "fulltext", "hybrid")
        }
        weight_rows: Dict[Tuple[float, float], List[Dict[str, Any]]] = {
            pair: [] for pair in HYBRID_WEIGHTS
        }
        bm25_rows: Dict[Tuple[float, float], List[Dict[str, Any]]] = {
            pair: [] for pair in BM25_GRID
        }

        async def run_case(case: Dict[str, Any]) -> None:
            if not _case_for_retrieval(case):
                return
            evidence = case.get("gold_evidence", [])
            gold_file = _resolve_file_alias(case.get("gold_file"))
            query = case["query"]

            vector_start = time.perf_counter()
            vector_results, _ = await svc._vector_search(
                session, query, [KB_ID], top_k=20, score_threshold=0.0
            )
            vector_latency = (time.perf_counter() - vector_start) * 1000

            bm25_start = time.perf_counter()
            bm25_results, _ = await svc._bm25_search(
                session, query, [KB_ID], top_k=20
            )
            bm25_latency = (time.perf_counter() - bm25_start) * 1000

            hybrid_start = time.perf_counter()
            hybrid_results = _fuse(
                svc, session, vector_results, bm25_results, 0.7, 0.3, top_k=5
            )
            hybrid_latency = vector_latency + bm25_latency + (
                time.perf_counter() - hybrid_start
            ) * 1000

            row = {
                "id": case["id"],
                "category": case["category"],
                "behavior": case.get("behavior"),
                "query": query,
                "gold_file": gold_file,
                "gold_evidence": evidence,
                "modes": {
                    "vector": {
                        "results": [
                            {
                                "rank": i + 1,
                                "file": r.get("file_name"),
                                "score": round(float(r.get("score", 0)), 4),
                                "snippet": r.get("content", "")[:160].replace("\n", " "),
                            }
                            for i, r in enumerate(vector_results[:5])
                        ],
                        "k1": _metrics_at_k(vector_results, evidence, gold_file, 1),
                        "k3": _metrics_at_k(vector_results, evidence, gold_file, 3),
                    },
                    "fulltext": {
                        "results": [
                            {
                                "rank": i + 1,
                                "file": r.get("file_name"),
                                "score": round(float(r.get("score", 0)), 4),
                                "snippet": r.get("content", "")[:160].replace("\n", " "),
                            }
                            for i, r in enumerate(bm25_results[:5])
                        ],
                        "k1": _metrics_at_k(bm25_results, evidence, gold_file, 1),
                        "k3": _metrics_at_k(bm25_results, evidence, gold_file, 3),
                    },
                    "hybrid": {
                        "results": [
                            {
                                "rank": i + 1,
                                "file": r.get("file_name"),
                                "score": round(float(r.get("score", 0)), 4),
                                "snippet": r.get("content", "")[:160].replace("\n", " "),
                            }
                            for i, r in enumerate(hybrid_results[:5])
                        ],
                        "k1": _metrics_at_k(hybrid_results, evidence, gold_file, 1),
                        "k3": _metrics_at_k(hybrid_results, evidence, gold_file, 3),
                    },
                },
                "latency_ms": {
                    "vector": round(vector_latency, 1),
                    "fulltext": round(bm25_latency, 1),
                    "hybrid": round(hybrid_latency, 1),
                },
            }
            for mode in ("vector", "fulltext", "hybrid"):
                row[f"{mode}_k1"] = row["modes"][mode]["k1"]
                row[f"{mode}_k3"] = row["modes"][mode]["k3"]
                row[f"{mode}_latency"] = row["latency_ms"][mode]

            case_rows.append(row)
            runs_by_mode["vector"][case["id"]] = results_to_run(vector_results)
            runs_by_mode["fulltext"][case["id"]] = results_to_run(bm25_results)
            runs_by_mode["hybrid"][case["id"]] = results_to_run(hybrid_results)

            # 权重扫描：复用同一批 raw 结果，不重复 embedding
            for pair in HYBRID_WEIGHTS:
                fused = _fuse(svc, session, vector_results, bm25_results, pair[0], pair[1], top_k=5)
                weight_rows[pair].append(
                    {
                        "id": case["id"],
                        "latency_ms": vector_latency + bm25_latency,
                        "k1": _metrics_at_k(fused, evidence, gold_file, 1),
                        "k3": _metrics_at_k(fused, evidence, gold_file, 3),
                    }
                )

            # BM25 k1/b 扫描：只查本地索引，不调用 embedding
            for pair in BM25_GRID:
                k1, b = pair
                bm25 = BM25Index(k1=k1, b=b)
                start = time.perf_counter()
                raw = bm25.search(session, query, KB_ID, top_k=20)
                elapsed = (time.perf_counter() - start) * 1000
                enriched = svc._enrich_results(
                    session,
                    [{"id": r["chunk_id"], "score": r["bm25_score"], "kb_id": KB_ID} for r in raw],
                )
                bm25_rows[pair].append(
                    {
                        "id": case["id"],
                        "latency_ms": elapsed,
                        "k1": _metrics_at_k(enriched, evidence, gold_file, 1),
                        "k3": _metrics_at_k(enriched, evidence, gold_file, 3),
                    }
                )

            print(
                f"[{case['id']}] vector={int(row['vector_k3']['evidence_all'])} "
                f"fulltext={int(row['fulltext_k3']['evidence_all'])} "
                f"hybrid={int(row['hybrid_k3']['evidence_all'])} "
                f"lat(ms) v={vector_latency:.0f}/b={bm25_latency:.0f}",
                flush=True,
            )

        async def run_all() -> None:
            for i, case in enumerate(cases, 1):
                if not _case_for_retrieval(case):
                    print(
                        f"[{case['id']}] 跳过：behavior={case.get('behavior')} 不混入检索 Hit@K",
                        flush=True,
                    )
                    continue
                await run_case(case)
                if i % 5 == 0:
                    print(f"--- 进度 {i}/{len(cases)} ---", flush=True)

        asyncio.run(run_all())

    groups = split_cases(cases)
    qrels, invalid_cases = build_qrels(groups["retrieval"], chunk_text_by_id)
    standard_by_mode = {
        mode: standard_metrics(qrels, runs_by_mode[mode], k=3)
        for mode in ("vector", "fulltext", "hybrid")
    }

    def _legacy_mode_metrics(mode: str) -> Dict[str, Any]:
        legacy = _aggregate(
            [
                {
                    "k3": r[f"{mode}_k3"],
                    "k1": r[f"{mode}_k1"],
                    "latency_ms": r[f"{mode}_latency"],
                }
                for r in case_rows
            ]
        )
        # 旧字段名 mrr 实际是 evidence_any 的 reciprocal rank，不是标准 MRR；
        # 标准 MRR 请使用 ir_measures 的 RR@3。
        if "mrr" in legacy:
            legacy["evidence_any_rr"] = legacy.pop("mrr")
        return legacy

    summary = {
        "answerable_cases": len(case_rows),
        "refusal_cases": len(groups["refusal"]),
        "conflict_cases": len(groups["conflict"]),
        "invalid_cases": invalid_cases,
        "modes": {
            mode: {
                **_legacy_mode_metrics(mode),
                **standard_by_mode[mode],
            }
            for mode in ("vector", "fulltext", "hybrid")
        },
        "hybrid_weight_sweep": [
            {
                "vector_weight": pair[0],
                "bm25_weight": pair[1],
                "cases": len(rows),
                "evidence_all@3": round(
                    sum(r["k3"]["evidence_all"] for r in rows) / len(rows), 4
                ),
                "evidence_any@3": round(
                    sum(r["k3"]["evidence_any"] for r in rows) / len(rows), 4
                ),
                "evidence_any_rr": round(sum(r["k3"]["rr"] for r in rows) / len(rows), 4),
            }
            for pair, rows in weight_rows.items()
            if rows
        ],
        "bm25_grid": [
            {
                "k1": pair[0],
                "b": pair[1],
                "cases": len(rows),
                "evidence_all@3": round(
                    sum(r["k3"]["evidence_all"] for r in rows) / len(rows), 4
                ),
                "evidence_any@3": round(
                    sum(r["k3"]["evidence_any"] for r in rows) / len(rows), 4
                ),
                "evidence_any_rr": round(sum(r["k3"]["rr"] for r in rows) / len(rows), 4),
            }
            for pair, rows in bm25_rows.items()
            if rows
        ],
    }

    payload = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "kb_id": KB_ID,
            "kb_name": kb.name,
            "chunk_count": chunk_count,
            "golden_set": str(GOLDEN_PATH.relative_to(ROOT)),
            "golden_size": len(golden["cases"]),
            "evaluated_cases": len(case_rows),
            "evaluated_standard_cases": len(qrels),
            "embedding_model": settings.EMBEDDING_MODEL,
            "llm_model": settings.LLM_MODEL,
            "git_commit": subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True
            ).strip(),
            "notes": [
                "标准指标由 ir_measures 计算：Success@3 / P@3 / Recall@3 / RR@3 / nDCG@3。",
                "只有 behavior=answer 的题进入检索分母；refuse 和 report_conflict 单独列出。",
                "evidence_all@3 是自定义严格口径（每条 gold_evidence 都出现在 top3 同一批正文），保留用于历史对齐。",
                "evidence_any_rr 是旧字段 mrr 的准确名称：首个包含任一 evidence 的 chunk 的 reciprocal rank，不是标准 MRR。",
                "PDF 与 DOCX 是同一份简历的重复导出，file_hit 仅作参考，主指标看 evidence/标准指标。",
                "向量延迟包含网络 embedding 调用；第一次调用有冷启动。",
            ],
            "refusal_case_ids": [c["id"] for c in groups["refusal"]],
            "conflict_case_ids": [c["id"] for c in groups["conflict"]],
        },
        "summary": summary,
        "known_limits": golden.get("known_limits", []),
        "qrels": qrels,
        "cases": case_rows,
        "refusal_cases": groups["refusal"],
        "conflict_cases": groups["conflict"],
    }

    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# 个人知识库（4 份真实材料）检索评测报告",
        "",
        f"- 生成时间：{payload['meta']['generated_at']}",
        f"- KB：`{KB_ID}` · {kb.name} · {chunk_count} chunks",
        f"- Golden：{len(golden['cases'])} 条；检索可评 {len(case_rows)} 条；refusal {summary['refusal_cases']} 条；conflict {summary['conflict_cases']} 条",
        f"- invalid retrieval cases：{summary['invalid_cases'] or 'none'}",
        f"- Embedding：`{settings.EMBEDDING_MODEL}`；LLM：`{settings.LLM_MODEL}`；commit：`{payload['meta']['git_commit']}`",
        "",
        "## 1. 标准检索指标（ir_measures）",
        "",
        "| 模式 | Success@3 | P@3 | Recall@3 | RR@3 | nDCG@3 | 平均检索延迟(ms) |",
        "| :--- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for mode in ("vector", "fulltext", "hybrid"):
        row = summary["modes"][mode]
        lines.append(
            f"| {mode} | {row.get('Success@3', 0):.4f} | {row.get('P@3', 0):.4f} | "
            f"{row.get('R@3', 0):.4f} | {row.get('RR@3', 0):.4f} | "
            f"{row.get('nDCG@3', 0):.4f} | {row['latency_ms_mean']:.1f} |"
        )
    lines += [
        "",
        "## 1.1 兼容指标（自定义 evidence 口径）",
        "",
        "| 模式 | evidence_all@3 | evidence_any@3 | evidence_any_rr | file_hit@3 |",
        "| :--- | ---: | ---: | ---: | ---: |",
    ]
    for mode in ("vector", "fulltext", "hybrid"):
        row = summary["modes"][mode]
        lines.append(
            f"| {mode} | {row['evidence_all@3']:.2%} | {row['evidence_any@3']:.2%} | "
            f"{row['evidence_any_rr']:.4f} | {row['file_hit@3']:.2%} |"
        )
    lines += [
        "",
        "## 2. Hybrid 权重扫描",
        "",
        "| vector_weight | bm25_weight | evidence_all@3 | evidence_any@3 | evidence_any_rr |",
        "| ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summary["hybrid_weight_sweep"]:
        lines.append(
            f"| {row['vector_weight']} | {row['bm25_weight']} | {row['evidence_all@3']:.2%} | {row['evidence_any@3']:.2%} | {row['evidence_any_rr']:.4f} |"
        )
    lines += [
        "",
        "## 3. BM25 k1 / b 扫描",
        "",
        "| k1 | b | evidence_all@3 | evidence_any@3 | evidence_any_rr |",
        "| ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summary["bm25_grid"]:
        lines.append(
            f"| {row['k1']} | {row['b']} | {row['evidence_all@3']:.2%} | {row['evidence_any@3']:.2%} | {row['evidence_any_rr']:.4f} |"
        )
    lines += [
        "",
        "## 4. 逐题结果（hybrid 0.7/0.3）",
        "",
        "| ID | category | evidence_all@3 | file_hit@3 | top1 文件 | top1 片段 |",
        "| :--- | :--- | :---: | :---: | :--- | :--- |",
    ]
    for row in case_rows:
        top1 = row["modes"]["hybrid"]["results"][0] if row["modes"]["hybrid"]["results"] else {}
        snippet = (top1.get("snippet") or "").replace("|", "/")[:80]
        lines.append(
            f"| {row['id']} | {row['category']} | {'✅' if row['hybrid_k3']['evidence_all'] else '❌'} | {'✅' if row['hybrid_k3']['file_hit'] else '❌'} | {top1.get('file','-')} | {snippet} |"
        )
    if groups["conflict"]:
        lines += [
            "",
            "## 4.1 Conflict cases（单独评测，不参与 Hit@K）",
            "",
        ]
        for case in groups["conflict"]:
            lines.append(f"- `{case['id']}`：{case['query']}")
    if groups["refusal"]:
        lines += [
            "",
            "## 4.2 Refusal cases（评生成端拒答，不参与 Hit@K）",
            "",
        ]
        for case in groups["refusal"]:
            lines.append(f"- `{case['id']}`：{case['query']}")
    lines += [
        "",
        "## 5. 已知限制（来自 golden 文件）",
        "",
    ]
    for item in payload["known_limits"]:
        lines.append(f"- {item}")
    lines += [
        "",
        "## 6. 复算命令",
        "",
        "```bash",
        "cd /home/yang/Agentic-Multimodal-RAG/backend",
        'JWT_SECRET="$(python3 -c \'import secrets;print(secrets.token_urlsafe(48))\')" \\',
        "  python3 benchmark/eval_personal_kb.py",
        "```",
        "",
    ]
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    print("\n=== SUMMARY ===")
    print(json.dumps(summary["modes"], ensure_ascii=False, indent=2))
    print(f"\nJSON: {OUT_JSON}")
    print(f"MD:   {OUT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
