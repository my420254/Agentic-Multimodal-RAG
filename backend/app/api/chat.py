"""
对话 API 路由
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlmodel import Session
from typing import AsyncGenerator
import json

from app.core.database import get_session
from app.core.deps import get_current_user
from app.core.access import get_visible_kb
from app.models import KnowledgeBase, User
from app.schemas import (
    RewriteRequest,
    RewriteResponse,
    ChatRequest,
    ApiResponse,
)
from app.services.chat import ChatService
from app.services.llm import LLMService
from app.services.memory_service import memory_service

router = APIRouter(tags=["Chat"])


@router.post("/chat/rewrite", response_model=ApiResponse[RewriteResponse])
async def rewrite_query(
    data: RewriteRequest,
    current_user: User = Depends(get_current_user),
):
    """问题改写"""
    try:
        llm_service = LLMService()
        rewritten = await llm_service.rewrite_query(data.query)
        return ApiResponse(data=RewriteResponse(rewritten_query=rewritten))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": 50001, "message": f"问题改写失败: {str(e)}"},
        )


@router.post("/chat/completions")
async def chat_completions(
    data: ChatRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """对话接口 (SSE 流式响应)"""
    # 验证知识库存在且当前用户可见（公共或本人）
    for kb_id in data.kb_ids:
        get_visible_kb(session, kb_id, current_user)

    # 身份只来自 token。body/query 里的任何 user_id 都不参与判定。
    uid = str(current_user.id)

    # 会话归属必须来自 token：新会话允许认领，他人会话统一 404。
    if data.session_id and not memory_service.claim_session(uid, data.session_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": 40402, "message": "会话不存在"},
        )

    async def generate_sse() -> AsyncGenerator[str, None]:
        """生成 SSE 事件流"""
        chat_service = ChatService()

        try:
            async for event_type, event_data in chat_service.chat_stream(
                messages=data.messages,
                kb_ids=data.kb_ids,
                use_rewrite=data.use_rewrite,
                mode=data.mode,
                top_k=data.top_k,
                score_threshold=data.score_threshold,
                model_id=data.model_id,
                rerank_enabled=data.rerank_enabled,
                rerank_score_threshold=data.rerank_score_threshold,
                rerank_model_id=data.rerank_model_id,
                # 新增检索参数
                search_mode=data.search_mode,
                vector_weight=data.vector_weight,
                bm25_weight=data.bm25_weight,
                rerank_top_k=data.rerank_top_k,
                context_window=data.context_window,
                session_id=data.session_id,
                user_id=uid,
            ):
                # 格式化 SSE 事件
                yield f"event: {event_type}\n"
                yield f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"

        except Exception as e:
            # 发送错误事件
            error_data = {"error": str(e)}
            yield f"event: error\n"
            yield f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate_sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
