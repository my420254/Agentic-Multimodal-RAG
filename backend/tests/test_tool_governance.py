import asyncio
import pytest

from app.tools.governance import (
    SearchKnowledgeBaseInput,
    ToolExecutionError,
    ToolTimeoutError,
    ToolValidationError,
    execute_with_governance,
    validate_tool_args,
)


def test_schema_rejects_unknown_and_out_of_range():
    with pytest.raises(ToolValidationError):
        validate_tool_args("search_knowledge_base", {"query": "x", "hallucinated": 1})
    with pytest.raises(ToolValidationError):
        validate_tool_args("search_knowledge_base", {"query": ""})
    with pytest.raises(ToolValidationError):
        validate_tool_args("search_knowledge_base", {"query": "x", "top_k": 999})


def test_schema_normalizes_valid_args():
    args = validate_tool_args("search_knowledge_base", {"query": "Redis 限流", "kb_ids": ["kb1"]})
    assert args["query"] == "Redis 限流"
    assert args["kb_ids"] == ["kb1"]
    assert args["search_mode"] == "hybrid"
    assert args["top_k"] == 5


class FakeTool:
    def __init__(self, fail_times=0, sleep_s=0):
        self.fail_times = fail_times
        self.sleep_s = sleep_s
        self.calls = 0

    async def ainvoke(self, args, config=None):
        self.calls += 1
        if self.sleep_s:
            await asyncio.sleep(self.sleep_s)
        if self.calls <= self.fail_times:
            raise RuntimeError("transient")
        return '{"context": "ok", "citations": []}'


@pytest.mark.asyncio
async def test_timeout_is_classified():
    tool = FakeTool(sleep_s=0.2)
    with pytest.raises(ToolTimeoutError):
        await execute_with_governance(
            "search_knowledge_base", tool, {"query": "x"},
            timeout_s=0.01, max_retries=0,
        )


@pytest.mark.asyncio
async def test_transient_failure_retries_once():
    tool = FakeTool(fail_times=1)
    result = await execute_with_governance(
        "search_knowledge_base", tool, {"query": "x"},
        timeout_s=1, max_retries=1,
    )
    assert "ok" in result
    assert tool.calls == 2


@pytest.mark.asyncio
async def test_permanent_failure_raises_execution_error():
    tool = FakeTool(fail_times=5)
    with pytest.raises(ToolExecutionError):
        await execute_with_governance(
            "search_knowledge_base", tool, {"query": "x"},
            timeout_s=1, max_retries=1,
        )
    assert tool.calls == 2
