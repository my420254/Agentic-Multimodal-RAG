#!/usr/bin/env python3
"""
对比 Hybrid 融合策略：min-max 加权和 vs RRF。

只评真实简历库（kb_real_resumes / 42 条 golden），复用向量+BM25 原始召回，
不重复 embedding，只比较融合排序。
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlmodel import Session  # noqa: E402

from app.core.database import engine  # noqa: E402
from app.services.retrieval import RetrievalService, normalize_scores  # noqa: E402

engine.echo = False
KB_ID = "kb_real_resumes"
GOLDEN = BACKEND_DIR / "benchmark" / "real_resumes_golden.json"
OUT = BACKEND_DIR / "benchmark" / "rrf_compare.json"


def metrics(results: List[Dict[str, Any]], evidence: List[str]) -> Dict[str, Any]:
    top = results[:3]
    text = "\n".join(r.get("content", "") for r in top)
    hits = sum(1 for e in evidence if e in text)
    rr = 0.0
    for rank, row in enumerate(results, start=1):
        if any(e in row.get("content", "") for e in evidence):
            rr = 1.0 / rank
            break
    return {
        "evidence_all": bool(evidence) and hits == len(evidence),
        "evidence_any": hits > 0,
        "rr": rr,
    }


def fuse_weighted(
    svc: RetrievalService,
    session: Session,
    vector_results: List[Dict[str, Any]],
    bm25_results: List[Dict[str, Any]],
    vw: float = 0.7,
    bw: float = 0.3,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    vs = normalize_scores({r["id"]: r["score"] for r in vector_results})
    bs = normalize_scores({r["id"]: r["bm25_score"] for r in bm25_results})
    fused = {
        cid: vw * vs.get(cid, 0.0) + bw * bs.get(cid, 0.0)
        for cid in set(vs) | set(bs)
    }
    top = sorted(fused.items(), key=lambda x: x[1], reverse=True)[:top_k]
    raw = {r["id"]: r for r in vector_results}
    raw.update({r["id"]: r for r in bm25_results})
    return svc._enrich_results(
        session,
        [
            {
                "id": cid,
                "score": score,
                "kb_id": raw.get(cid, {}).get("kb_id", KB_ID),
            }
            for cid, score in top
        ],
    )


def fuse_rrf(
    svc: RetrievalService,
    session: Session,
    vector_results: List[Dict[str, Any]],
    bm25_results: List[Dict[str, Any]],
    k: int = 60,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    scores: Dict[str, float] = {}
    for rank, row in enumerate(vector_results, start=1):
        cid = row["id"]
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
    for rank, row in enumerate(bm25_results, start=1):
        cid = row.get("id") or row.get("chunk_id")
        if not cid:
            continue
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
    top = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
    raw = {r["id"]: r for r in vector_results}
    raw.update({(r.get("id") or r.get("chunk_id")): r for r in bm25_results})
    return svc._enrich_results(
        session,
        [
            {
                "id": cid,
                "score": score,
                "kb_id": raw.get(cid, {}).get("kb_id", KB_ID),
            }
            for cid, score in top
        ],
    )


def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(rows)
    return {
        "cases": n,
        "evidence_all@3": round(sum(r["evidence_all"] for r in rows) / n, 4),
        "evidence_any@3": round(sum(r["evidence_any"] for r in rows) / n, 4),
        "mrr": round(sum(r["rr"] for r in rows) / n, 4),
    }


async def main() -> int:
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    cases = [c for c in golden["cases"] if c.get("behavior") != "refuse" and c.get("gold_evidence")]
    rows_weighted: List[Dict[str, Any]] = []
    rows_rrf60: List[Dict[str, Any]] = []
    rows_rrf10: List[Dict[str, Any]] = []
    rows_rrf30: List[Dict[str, Any]] = []

    with Session(engine) as session:
        svc = RetrievalService()
        for case in cases:
            q = case["query"]
            evidence = case["gold_evidence"]
            v, _ = await svc._vector_search(session, q, [KB_ID], top_k=20, score_threshold=0.0)
            b, _ = await svc._bm25_search(session, q, [KB_ID], top_k=20)
            weighted = fuse_weighted(svc, session, v, b, 0.7, 0.3, 5)
            rrf60 = fuse_rrf(svc, session, v, b, 60, 5)
            rrf10 = fuse_rrf(svc, session, v, b, 10, 5)
            rrf30 = fuse_rrf(svc, session, v, b, 30, 5)
            rows_weighted.append(metrics(weighted, evidence))
            rows_rrf60.append(metrics(rrf60, evidence))
            rows_rrf10.append(metrics(rrf10, evidence))
            rows_rrf30.append(metrics(rrf30, evidence))
            print(f"[{case['id']}] weighted={rows_weighted[-1]} rrf60={rows_rrf60[-1]}", flush=True)

    result = {
        "kb_id": KB_ID,
        "cases": len(cases),
        "weighted_0.7_0.3": summarize(rows_weighted),
        "rrf_k10": summarize(rows_rrf10),
        "rrf_k30": summarize(rows_rrf30),
        "rrf_k60": summarize(rows_rrf60),
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n=== RRF COMPARE ===")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"JSON: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
