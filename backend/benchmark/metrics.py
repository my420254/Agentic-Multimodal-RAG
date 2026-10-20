"""标准检索指标适配层。

职责边界：
- 指标计算：交给 ``ir_measures``（Success/P/Recall/RR/nDCG），不在本仓库重写公式；
- 相关性定义：本模块只负责把 golden 的 evidence 短语映射成 qrels；
- 结果适配：把 retrieval service 的 ranked list 转成 ``{doc_id: score}``。

``evidence_all@K`` / ``evidence_any@K`` 是项目自定义的严格口径，保留用于和
历史报告对齐；对外的标准指标以 ``Success@K`` / ``RR@K`` / ``nDCG@K`` 为准。
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Tuple

import ir_measures
from ir_measures import RR, Recall, Success, nDCG, P

# 只有 behavior=answer 的用例参与检索指标。
# - refuse：没有 gold_evidence，评的是生成端拒答；
# - report_conflict：本来就要求跨 chunk 取证，用单 chunk 的 evidence_all 计算没有意义。
RETRIEVAL_BEHAVIOR = "answer"


def is_retrieval_case(case: Mapping[str, Any]) -> bool:
    return case.get("behavior") == RETRIEVAL_BEHAVIOR and bool(case.get("gold_evidence"))


def split_cases(cases: Iterable[Mapping[str, Any]]) -> Dict[str, List[Mapping[str, Any]]]:
    """按 behavior 分组，避免把拒答/冲突题混进检索分母。"""
    groups: Dict[str, List[Mapping[str, Any]]] = {
        "retrieval": [],
        "refusal": [],
        "conflict": [],
        "other": [],
    }
    for case in cases:
        behavior = case.get("behavior")
        if is_retrieval_case(case):
            groups["retrieval"].append(case)
        elif behavior == "refuse":
            groups["refusal"].append(case)
        elif behavior == "report_conflict":
            groups["conflict"].append(case)
        else:
            groups["other"].append(case)
    return groups


def build_qrels(
    cases: Iterable[Mapping[str, Any]],
    chunk_text_by_id: Mapping[str, str],
) -> Tuple[Dict[str, Dict[str, int]], List[str]]:
    """把 evidence 短语映射成二值 qrels。

    一个 chunk 算 relevant，当且仅当它同时包含该 case 的每一条 gold evidence。
    返回 ``(qrels, invalid_case_ids)``；invalid 表示语料里找不到任何满足条件的
    chunk，通常意味着 golden 写错了或语料已变更，应在评测前修掉。
    """
    qrels: Dict[str, Dict[str, int]] = {}
    invalid: List[str] = []
    for case in cases:
        if not is_retrieval_case(case):
            continue
        evidence = [str(item) for item in case.get("gold_evidence") or []]
        relevant = {
            chunk_id: 1
            for chunk_id, text in chunk_text_by_id.items()
            if evidence and all(item in text for item in evidence)
        }
        if relevant:
            qrels[str(case["id"])] = relevant
        else:
            invalid.append(str(case["id"]))
    return qrels, invalid


def results_to_run(results: Iterable[Mapping[str, Any]]) -> Dict[str, float]:
    """把 ranked results 转成 ir_measures 需要的 ``{doc_id: score}``。"""
    run: Dict[str, float] = {}
    for row in results:
        chunk_id = row.get("id") or row.get("chunk_id")
        if not chunk_id:
            continue
        try:
            score = float(row.get("score") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        run[str(chunk_id)] = score
    return run


def standard_metrics(
    qrels: Mapping[str, Mapping[str, int]],
    runs: Mapping[str, Mapping[str, float]],
    k: int = 3,
) -> Dict[str, float]:
    """用标准库计算聚合指标；缺失 run 的 query 按空结果处理。"""
    if not qrels:
        return {}
    measures = [Success @ k, P @ k, Recall @ k, RR @ k, nDCG @ k]
    complete_runs = {qid: dict(runs.get(qid, {})) for qid in qrels}
    aggregate = ir_measures.calc_aggregate(measures, dict(qrels), complete_runs)
    return {str(measure): round(float(aggregate[measure]), 4) for measure in measures}
