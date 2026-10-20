"""Golden 相关性映射与标准 IR 指标测试（不依赖数据库/网络）。"""

import json
from pathlib import Path

import pytest

from benchmark.metrics import (
    build_qrels,
    is_retrieval_case,
    results_to_run,
    split_cases,
    standard_metrics,
)
from benchmark.validate_golden import structural_checks

BENCHMARK_DIR = Path(__file__).resolve().parent.parent / "benchmark"
GOLDEN_FILES = [
    BENCHMARK_DIR / "real_resumes_golden.json",
    BENCHMARK_DIR / "personal_kb_golden.json",
]


@pytest.mark.parametrize("path", GOLDEN_FILES, ids=lambda p: p.name)
def test_golden_files_pass_structural_checks(path):
    if not path.exists():
        pytest.skip(f"{path.name} 是本地 PII 数据，CI 不包含")
    golden = json.loads(path.read_text(encoding="utf-8"))
    assert structural_checks(golden) == []


def _case(case_id: str, behavior: str, evidence=None) -> dict:
    return {
        "id": case_id,
        "behavior": behavior,
        "gold_evidence": evidence or [],
    }


def test_split_cases_keeps_refusal_and_conflict_out_of_retrieval():
    groups = split_cases([
        _case("R1", "answer", ["alpha", "beta"]),
        _case("X1", "refuse"),
        _case("C1", "report_conflict", ["alpha", "beta"]),
        _case("R2", "answer", []),
    ])
    assert [c["id"] for c in groups["retrieval"]] == ["R1"]
    assert [c["id"] for c in groups["refusal"]] == ["X1"]
    assert [c["id"] for c in groups["conflict"]] == ["C1"]
    assert [c["id"] for c in groups["other"]] == ["R2"]


def test_is_retrieval_case_requires_answer_behavior_and_evidence():
    assert is_retrieval_case(_case("R1", "answer", ["x"]))
    assert not is_retrieval_case(_case("R2", "answer", []))
    assert not is_retrieval_case(_case("X1", "refuse", ["x"]))
    assert not is_retrieval_case(_case("C1", "report_conflict", ["x"]))


def test_build_qrels_requires_all_evidence_in_the_same_chunk():
    chunks = {
        "c1": "alpha beta gamma",
        "c2": "alpha only",
        "c3": "beta only",
        "c4": "alpha beta delta",
    }
    qrels, invalid = build_qrels(
        [
            _case("R1", "answer", ["alpha", "beta"]),
            _case("R2", "answer", ["missing"]),
            _case("X1", "refuse"),
            _case("C1", "report_conflict", ["alpha", "beta"]),
        ],
        chunks,
    )
    assert qrels == {"R1": {"c1": 1, "c4": 1}}
    assert invalid == ["R2"]


def test_results_to_run_keeps_ranked_chunk_ids_and_scores():
    run = results_to_run([
        {"id": "c1", "score": 0.9},
        {"chunk_id": "c2", "score": 0.5},
        {"id": None, "score": 1.0},
        {"id": "c3"},
    ])
    assert run == {"c1": 0.9, "c2": 0.5, "c3": 0.0}


def test_standard_metrics_use_ir_measures():
    qrels = {"q1": {"a": 1, "b": 1}}
    runs = {"q1": {"x": 0.9, "a": 0.8, "b": 0.7}}
    metrics = standard_metrics(qrels, runs, k=3)

    assert metrics["Success@3"] == 1.0
    assert metrics["P@3"] == round(2 / 3, 4)
    assert metrics["R@3"] == 1.0
    assert metrics["RR@3"] == 0.5
    assert 0.0 < metrics["nDCG@3"] <= 1.0


def test_standard_metrics_handles_empty_and_missing_runs():
    assert standard_metrics({}, {}) == {}

    metrics = standard_metrics({"q1": {"a": 1}}, {"q2": {"a": 1}}, k=3)
    assert metrics["Success@3"] == 0.0
    assert metrics["RR@3"] == 0.0
    assert metrics["nDCG@3"] == 0.0
