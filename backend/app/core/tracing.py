"""可选 Langfuse tracing。

设计目标：
- 没有 key：完全 no-op，不发起任何网络请求，聊天/测试照常运行；
- Langfuse 初始化或上报失败：只记 warning，不影响主链路；
- 本地 ``agent_traces`` 继续保留，作为 Langfuse 不可用时的 fallback；
- 默认 ``TRACE_CONTENT_MODE=redacted``：发送前做正则脱敏；``metadata`` 模式
  只发长度/ID，不发 query/answer/content 正文；``full`` 仅限自托管环境。

Langfuse v5 使用 OTel 语义：root observation 就是 trace，子 observation 通过
当前 context 自动挂载。这里只做一层薄封装，不重写 SDK 的指标/上报逻辑。
"""

from __future__ import annotations

import hashlib
import logging
import re
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_ID_CARD_RE = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
_STUDENT_ID_RE = re.compile(r"(?<!\d)(?:19|20)\d{5,10}(?!\d)")

# 这些字段在 metadata 模式下不发送正文，只发送长度。
_SENSITIVE_KEYS = {
    "input",
    "output",
    "query",
    "answer",
    "content",
    "context",
    "citations",
    "messages",
    "documents",
    "result",
}


def redact_text(text: str, limit: int = 2000) -> str:
    """按 TRACE_CONTENT_MODE 处理文本。"""
    if not text:
        return ""
    text = str(text)
    mode = settings.TRACE_CONTENT_MODE
    if mode == "full":
        return text[:limit]
    text = _EMAIL_RE.sub("[email]", text)
    text = _PHONE_RE.sub("[phone]", text)
    text = _ID_CARD_RE.sub("[id_card]", text)
    text = _STUDENT_ID_RE.sub("[student_id]", text)
    return text[:limit]


def hash_user_id(user_id: Optional[str]) -> Optional[str]:
    """伪名化 user_id；同一个部署内保持稳定，不把原始 ID 发给 Langfuse。"""
    if not user_id:
        return None
    salt = settings.JWT_SECRET[:16]
    return hashlib.sha256(f"{salt}:{user_id}".encode("utf-8")).hexdigest()[:16]


class Tracing:
    """Langfuse 的惰性单例封装；keys 缺失时所有方法都是 no-op。"""

    def __init__(self) -> None:
        self._client = None
        self._init_done = False
        self._enabled = False

    def _ensure_client(self) -> None:
        if self._init_done:
            return
        self._init_done = True
        if not settings.LANGFUSE_ENABLED:
            return
        if not (settings.LANGFUSE_PUBLIC_KEY and settings.LANGFUSE_SECRET_KEY):
            return
        try:
            from langfuse import Langfuse

            self._client = Langfuse(
                public_key=settings.LANGFUSE_PUBLIC_KEY,
                secret_key=settings.LANGFUSE_SECRET_KEY,
                host=settings.LANGFUSE_HOST,
                environment=settings.ENV,
                tracing_enabled=True,
                mask=self._mask,
            )
            self._enabled = True
            logger.info("Langfuse tracing enabled host=%s env=%s", settings.LANGFUSE_HOST, settings.ENV)
        except Exception as exc:  # 观测失败不能影响业务
            logger.warning("Langfuse init failed; tracing disabled: %s", exc)

    @property
    def enabled(self) -> bool:
        self._ensure_client()
        return self._enabled

    @property
    def client(self):
        self._ensure_client()
        return self._client

    # ------------------------------------------------------------------
    # PII / content masking
    # ------------------------------------------------------------------
    def _mask(self, **kwargs: Any) -> Any:
        """Langfuse SDK 的 mask 回调；对 input/output/metadata 递归脱敏。"""
        return self._safe_value(kwargs.get("data"))

    def _safe_value(self, value: Any, key: Optional[str] = None) -> Any:
        if settings.TRACE_CONTENT_MODE == "full":
            return value
        if isinstance(value, str):
            if settings.TRACE_CONTENT_MODE == "metadata" and (
                key in _SENSITIVE_KEYS or len(value) > 80
            ):
                return f"[redacted:{len(value)}]"
            return redact_text(value)
        if isinstance(value, list):
            return [self._safe_value(item, key) for item in value]
        if isinstance(value, tuple):
            return [self._safe_value(item, key) for item in value]
        if isinstance(value, dict):
            return {k: self._safe_value(v, str(k)) for k, v in value.items()}
        return value

    def safe(self, value: Any, key: Optional[str] = None) -> Any:
        """供业务代码在传 input/output 前调用。"""
        return self._safe_value(value, key)

    # ------------------------------------------------------------------
    # Traces / observations
    # ------------------------------------------------------------------
    @contextmanager
    def trace(
        self,
        *,
        name: str,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        input: Any = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Iterator[Any]:
        """创建 root trace；禁用或 SDK 初始化失败时 yield None。

        注意：只在“进入 span”阶段吞异常；业务代码在 ``yield`` 之后抛出的异常
        必须原样向上传播，不能被观测层掩盖。
        """
        if not self.enabled:
            yield None
            return

        root_cm = None
        attr_cm = None
        try:
            from langfuse import propagate_attributes

            root_cm = self._client.start_as_current_observation(
                name=name,
                as_type="span",
                input=self._safe_value(input),
                metadata=self._safe_value(metadata),
            )
            root = root_cm.__enter__()
            attr_cm = propagate_attributes(
                user_id=hash_user_id(user_id),
                session_id=session_id,
                trace_name=name,
                metadata=self._safe_value(metadata),
            )
            attr_cm.__enter__()
        except Exception as exc:
            logger.warning("Langfuse trace failed; continuing without tracing: %s", exc)
            for cm in (attr_cm, root_cm):
                if cm is not None:
                    try:
                        cm.__exit__(None, None, None)
                    except Exception:
                        pass
            yield None
            return

        try:
            yield root
        finally:
            for cm in (attr_cm, root_cm):
                if cm is not None:
                    try:
                        cm.__exit__(None, None, None)
                    except Exception as exc:
                        logger.warning("Langfuse trace exit failed: %s", exc)

    @contextmanager
    def observation(
        self,
        name: str,
        *,
        as_type: str = "span",
        input: Any = None,
        output: Any = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Iterator[Any]:
        """在当前 trace 下创建子 observation；没有 active trace 时 no-op。"""
        if not self.enabled:
            yield None
            return

        # 注意：这里的 yield None 必须放在 try 之外。否则调用方 with 块里的
        # 业务异常会被 throw 到这个 yield 上，被下面的 except 误捕获。
        try:
            has_active_trace = bool(self._client.get_current_trace_id())
        except Exception:
            has_active_trace = False
        if not has_active_trace:
            yield None
            return

        span_cm = None
        try:
            span_cm = self._client.start_as_current_observation(
                name=name,
                as_type=as_type,
                input=self._safe_value(input),
                output=self._safe_value(output),
                metadata=self._safe_value(metadata),
                **kwargs,
            )
            span = span_cm.__enter__()
        except Exception as exc:
            logger.warning("Langfuse observation %s failed: %s", name, exc)
            if span_cm is not None:
                try:
                    span_cm.__exit__(None, None, None)
                except Exception:
                    pass
            yield None
            return

        try:
            yield span
        finally:
            try:
                span_cm.__exit__(None, None, None)
            except Exception as exc:
                logger.warning("Langfuse observation exit failed: %s", exc)

    def current_trace_id(self) -> Optional[str]:
        if not self.enabled:
            return None
        try:
            return self._client.get_current_trace_id()
        except Exception:
            return None

    def update(self, span: Any, **kwargs: Any) -> None:
        if span is None:
            return
        try:
            safe_kwargs = {
                key: self._safe_value(value, key)
                for key, value in kwargs.items()
                if key in {"input", "output", "metadata", "status_message"}
            }
            span.update(**safe_kwargs)
        except Exception as exc:
            logger.warning("Langfuse span update failed: %s", exc)

    def callback_handler(self, trace_id: Optional[str] = None):
        """LangChain/LangGraph callback；未启用时返回 None。

        传入 trace_id 时显式绑定到当前 trace，避免 LangGraph 在独立任务里
        丢失 OTel context 后生成第二条 trace。
        """
        if not self.enabled:
            return None
        try:
            from langfuse.langchain import CallbackHandler

            trace_context = None
            if trace_id:
                from langfuse.types import TraceContext

                trace_context = TraceContext(trace_id=trace_id)
            return CallbackHandler(
                public_key=settings.LANGFUSE_PUBLIC_KEY,
                trace_context=trace_context,
            )
        except Exception as exc:
            logger.warning("Langfuse callback handler init failed: %s", exc)
            return None

    def flush(self) -> None:
        if not self.enabled:
            return
        try:
            self._client.flush()
        except Exception as exc:
            logger.warning("Langfuse flush failed: %s", exc)

    def shutdown(self) -> None:
        if not self.enabled:
            return
        try:
            self._client.shutdown()
        except Exception as exc:
            logger.warning("Langfuse shutdown failed: %s", exc)


tracer = Tracing()
