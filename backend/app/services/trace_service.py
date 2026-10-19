"""请求级 Agent trace 持久化（本地版；字段对齐 Langfuse 常用维度）。"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlmodel import Session

from app.core.database import engine
from app.models import AgentTrace

logger = logging.getLogger(__name__)


def new_trace_id() -> str:
    return f"tr_{uuid.uuid4().hex}"


def _truncate(value: Any, limit: int = 4000) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text[:limit]


def _citation_summary(citations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for c in (citations or [])[:10]:
        if not isinstance(c, dict):
            continue
        out.append({
            "fileId": c.get("fileId") or c.get("file_id"),
            "fileName": c.get("fileName") or c.get("file_name"),
            "chunk_id": c.get("chunk_id"),
            "score": c.get("score"),
            "rerank_score": c.get("rerank_score"),
        })
    return out


def _tool_calls(steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for step in steps or []:
        if not isinstance(step, dict):
            continue
        if step.get("step") in {"action", "tool_error"}:
            out.append({
                "step": step.get("step"),
                "content": str(step.get("content", ""))[:1000],
            })
    return out[:30]


def record_agent_trace(
    *,
    trace_id: str,
    user_id: Optional[str],
    session_id: Optional[str],
    mode: str,
    query: str,
    answer: str,
    kb_ids: List[str],
    model_id: Optional[str],
    prompt_version: Optional[str],
    citations: List[Dict[str, Any]],
    steps: List[Dict[str, Any]],
    ttft_ms: Optional[float],
    total_ms: float,
    error: Optional[str] = None,
) -> None:
    """记录 trace；观测失败不能影响主对话。"""
    try:
        row = AgentTrace(
            trace_id=trace_id,
            user_id=str(user_id) if user_id else None,
            session_id=session_id,
            mode=mode or "chat",
            query=_truncate(query, 2000),
            answer_preview=_truncate(answer, 4000),
            kb_ids=",".join(str(x) for x in (kb_ids or [])),
            model_id=model_id,
            prompt_version=prompt_version,
            citations_json=json.dumps(_citation_summary(citations), ensure_ascii=False),
            steps_json=json.dumps(steps or [], ensure_ascii=False, default=str)[:12000],
            tool_calls_json=json.dumps(_tool_calls(steps), ensure_ascii=False, default=str),
            ttft_ms=round(ttft_ms, 2) if ttft_ms is not None else None,
            total_ms=round(total_ms, 2),
            error=_truncate(error, 500) if error else None,
        )
        with Session(engine) as session:
            session.add(row)
            session.commit()
    except Exception as exc:
        logger.warning("record_agent_trace failed trace_id=%s: %s", trace_id, exc)


def trace_to_dict(row: AgentTrace, detail: bool = False) -> Dict[str, Any]:
    base = {
        "trace_id": row.trace_id,
        "user_id": row.user_id,
        "session_id": row.session_id,
        "mode": row.mode,
        "query": row.query,
        "model_id": row.model_id,
        "ttft_ms": row.ttft_ms,
        "total_ms": row.total_ms,
        "error": row.error,
        "created_at": row.created_at,
    }
    if not detail:
        base["answer_preview"] = (row.answer_preview or "")[:200]
        return base
    base.update({
        "answer_preview": row.answer_preview,
        "kb_ids": [x for x in (row.kb_ids or "").split(",") if x],
        "prompt_version": row.prompt_version,
        "citations": json.loads(row.citations_json or "[]"),
        "steps": json.loads(row.steps_json or "[]"),
        "tool_calls": json.loads(row.tool_calls_json or "[]"),
    })
    return base
