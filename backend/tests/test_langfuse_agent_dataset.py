"""Langfuse SRE Agent dataset/experiment 的纯逻辑测试（不联网）。"""

from benchmark.langfuse_agent_dataset import (
    citation_present,
    golden_cases,
    keyword_hit,
    no_tool_error,
)


def test_golden_cases_are_non_pii_and_stable():
    items = golden_cases()
    assert len(items) == 10
    assert [item["id"] for item in items] == [f"A{i:02d}" for i in range(1, 11)]
    assert all(item["metadata"]["pii"] is False for item in items)
    assert all(item["input"]["kb_ids"] == ["kb_sre_enterprise"] for item in items)
    assert all(item["expected_output"]["keywords"] for item in items)


def test_keyword_hit_evaluator():
    evaluation = keyword_hit(
        input={},
        output={"answer": "应由后端做权限校验，并使用白名单。"},
        expected_output={"keywords": ["后端", "权限", "白名单", "allowlist"]},
        metadata={},
    )
    assert evaluation.name == "keyword_hit"
    assert evaluation.value == 0.75


def test_citation_and_tool_error_evaluators():
    citation = citation_present(
        input={},
        output={"citations": [{"chunk_id": "c1"}]},
        expected_output={},
        metadata={},
    )
    assert citation.value is True

    no_error = no_tool_error(
        input={},
        output={"tool_errors": []},
        expected_output={},
        metadata={},
    )
    assert no_error.value is True

    has_error = no_tool_error(
        input={},
        output={"tool_errors": [{"step": "tool_error"}]},
        expected_output={},
        metadata={},
    )
    assert has_error.value is False
