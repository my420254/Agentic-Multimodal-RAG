"""工具治理：Pydantic 参数校验 + 超时 + 有限重试 + 错误分类。

模型可以决定“调什么”，但不能绕过服务端的参数/资源约束。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.config import get_settings
from app.core.tracing import tracer

logger = logging.getLogger(__name__)
settings = get_settings()


class ToolValidationError(Exception):
    """模型生成的工具参数不合法。"""


class ToolTimeoutError(Exception):
    """工具调用超时。"""


class ToolExecutionError(Exception):
    """工具执行异常。"""


class SearchKnowledgeBaseInput(BaseModel):
    """search_knowledge_base 的唯一合法入参契约。"""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=500)
    kb_ids: Optional[List[str]] = None
    search_mode: Literal["vector", "fulltext", "hybrid"] = "hybrid"
    top_k: int = Field(default=5, ge=1, le=20)
    score_threshold: float = Field(default=0.1, ge=0.0, le=1.0)
    use_rerank: bool = False
    rerank_top_k: int = Field(default=3, ge=1, le=20)
    rerank_score_threshold: float = Field(default=0.0, ge=0.0, le=1.0)
    rerank_model_id: Optional[str] = None
    vector_weight: float = Field(default=0.7, ge=0.0, le=1.0)
    bm25_weight: float = Field(default=0.3, ge=0.0, le=1.0)
    context_window: int = Field(default=0, ge=0, le=5)


def validate_tool_args(tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """校验并归一化工具参数；未知参数直接拒绝，避免模型幻觉参数穿透。"""
    if tool_name != "search_knowledge_base":
        raise ToolValidationError(f"未知工具: {tool_name}")
    try:
        return SearchKnowledgeBaseInput(**args).model_dump()
    except ValidationError as exc:
        # 只返回字段级错误，避免把内部堆栈喂给模型
        details = []
        for err in exc.errors():
            loc = ".".join(str(x) for x in err.get("loc", ()))
            details.append(f"{loc}: {err.get('msg')}")
        raise ToolValidationError("; ".join(details)) from exc


async def execute_with_governance(
    tool_name: str,
    tool: Any,
    args: Dict[str, Any],
    config: Any = None,
    timeout_s: Optional[float] = None,
    max_retries: Optional[int] = None,
) -> str:
    """校验 -> 超时 -> 有限重试 -> 返回字符串结果。"""
    validated = validate_tool_args(tool_name, args)
    timeout_s = timeout_s if timeout_s is not None else settings.TOOL_TIMEOUT_SECONDS
    max_retries = max_retries if max_retries is not None else settings.TOOL_MAX_RETRIES
    last_error: Optional[Exception] = None
    with tracer.observation(
        f"tool.governance.{tool_name}",
        as_type="tool",
        input=validated,
        metadata={"timeout_s": timeout_s, "max_retries": max_retries},
    ) as span:
        for attempt in range(max_retries + 1):
            try:
                result = await asyncio.wait_for(
                    tool.ainvoke(validated, config=config),
                    timeout=timeout_s,
                )
                tracer.update(span, output=str(result)[:4000])
                return str(result)
            except asyncio.TimeoutError as exc:
                last_error = ToolTimeoutError(f"工具 {tool_name} 超时（{timeout_s}s）")
                if attempt < max_retries:
                    await asyncio.sleep(0.2 * (attempt + 1))
                    continue
                tracer.update(span, status_message=str(last_error))
                raise last_error from exc
            except ToolValidationError as exc:
                tracer.update(span, status_message=str(exc))
                raise
            except Exception as exc:
                last_error = ToolExecutionError(str(exc))
                if attempt < max_retries:
                    await asyncio.sleep(0.2 * (attempt + 1))
                    continue
                tracer.update(span, status_message=str(last_error))
                raise last_error from exc
        tracer.update(span, status_message=str(last_error or "tool execution failed"))
        raise last_error or ToolExecutionError("工具执行失败")


def error_payload(error_type: str, message: str, retryable: bool) -> str:
    return json.dumps({
        "error": message,
        "error_type": error_type,
        "retryable": retryable,
        "context": "",
        "citations": [],
    }, ensure_ascii=False)
