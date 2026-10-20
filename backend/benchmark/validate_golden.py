#!/usr/bin/env python3
"""Golden 数据集体检。

结构检查不需要数据库；传 ``--kb-id`` 时再做一次相关性映射检查：
每条 behavior=answer 的题，必须至少有一个 chunk 同时包含全部 gold_evidence。

用法：
    cd backend
    JWT_SECRET=... python3 benchmark/validate_golden.py \
      --golden benchmark/real_resumes_golden.json --kb-id kb_real_resumes
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Mapping

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlmodel import Session, select  # noqa: E402

from app.core.database import engine  # noqa: E402
from app.models import DocumentChunk, FileDocument  # noqa: E402
from benchmark.metrics import build_qrels, split_cases  # noqa: E402

ALLOWED_BEHAVIORS = {"answer", "refuse", "report_conflict"}


def structural_checks(golden: Mapping[str, Any]) -> List[str]:
    errors: List[str] = []
    cases = list(golden.get("cases") or [])
    if golden.get("size") != len(cases):
        errors.append(f"size={golden.get('size')} 与实际 cases={len(cases)} 不一致")

    ids = [str(case.get("id")) for case in cases]
    if len(ids) != len(set(ids)):
        errors.append("存在重复 case id")

    categories = Counter(str(case.get("category")) for case in cases)
    mix = golden.get("mix") or {}
    if mix and dict(categories) != dict(mix):
        errors.append(f"mix={mix} 与 category 实际分布={dict(categories)} 不一致")

    queries = [str(case.get("query", "")).strip() for case in cases]
    duplicated = [q for q, n in Counter(queries).items() if n > 1]
    if duplicated:
        errors.append(f"存在重复 query: {duplicated}")

    corpus_files = set(golden.get("corpus_files") or [])
    for case in cases:
        case_id = case.get("id")
        behavior = case.get("behavior")
        evidence = case.get("gold_evidence") or []
        if behavior not in ALLOWED_BEHAVIORS:
            errors.append(f"{case_id}: 未知 behavior={behavior!r}")
        if behavior == "answer" and not evidence:
            errors.append(f"{case_id}: answer 用例缺少 gold_evidence")
        if behavior == "refuse" and evidence:
            errors.append(f"{case_id}: refuse 用例不应有 gold_evidence")
        if behavior == "report_conflict" and not evidence:
            errors.append(f"{case_id}: report_conflict 用例缺少 gold_evidence")
        gold_file = case.get("gold_file")
        if behavior != "refuse" and gold_file and corpus_files and gold_file not in corpus_files:
            errors.append(f"{case_id}: gold_file={gold_file!r} 不在 corpus_files 中")
    return errors


def mapping_checks(
    golden: Mapping[str, Any],
    chunk_text_by_id: Mapping[str, str],
) -> tuple[List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []
    groups = split_cases(golden.get("cases") or [])
    qrels, invalid = build_qrels(groups["retrieval"], chunk_text_by_id)
    if invalid:
        errors.append(f"以下 answer 用例在语料中找不到同时包含全部 evidence 的 chunk: {invalid}")

    total = max(1, len(chunk_text_by_id))
    for case in groups["retrieval"]:
        evidence = [str(item) for item in case.get("gold_evidence") or []]
        if len(evidence) == 1 and len(evidence[0].strip()) <= 3:
            warnings.append(f"{case['id']}: 单条 evidence 过短，容易误判：{evidence[0]!r}")
        relevant = qrels.get(str(case["id"]), {})
        if len(relevant) > max(10, total // 5):
            warnings.append(
                f"{case['id']}: evidence 匹配到 {len(relevant)}/{total} 个 chunk，相关性过宽"
            )
    if groups["conflict"]:
        warnings.append(
            f"{len(groups['conflict'])} 条 report_conflict 用例不参与单 chunk Hit@K，"
            "需在生成端单独评测"
        )
    return errors, warnings


def load_chunks(kb_id: str) -> Dict[str, str]:
    with Session(engine) as session:
        rows = session.exec(
            select(DocumentChunk)
            .join(FileDocument, DocumentChunk.file_id == FileDocument.id)
            .where(FileDocument.kb_id == kb_id)
        ).all()
    return {row.id: row.content for row in rows}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--golden", required=True)
    parser.add_argument("--kb-id", default=None)
    args = parser.parse_args()

    golden = json.loads(Path(args.golden).read_text(encoding="utf-8"))
    errors = structural_checks(golden)
    warnings: List[str] = []

    if args.kb_id:
        chunks = load_chunks(args.kb_id)
        if not chunks:
            errors.append(f"KB {args.kb_id} 没有 chunk")
        else:
            map_errors, map_warnings = mapping_checks(golden, chunks)
            errors.extend(map_errors)
            warnings.extend(map_warnings)
            print(f"[info] KB={args.kb_id} chunks={len(chunks)}")

    groups = split_cases(golden.get("cases") or [])
    print(
        "[info] cases="
        f"{len(golden.get('cases') or [])} retrieval={len(groups['retrieval'])} "
        f"refusal={len(groups['refusal'])} conflict={len(groups['conflict'])}"
    )
    for warning in warnings:
        print(f"[warn] {warning}")
    for error in errors:
        print(f"[error] {error}", file=sys.stderr)

    if errors:
        print(f"\nFAILED: {len(errors)} error(s)", file=sys.stderr)
        return 1
    print("\nOK: golden structure and relevance mapping are valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
