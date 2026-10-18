# -*- coding: utf-8 -*-
"""
三态熔断器 (Three-State Circuit Breaker)
参考 agent-interview-hub 生产级架构设计：
Closed (正常放行) -> Open (快速失败熔断) -> Half-Open (有限试探恢复)
保护下游 LLM API (SiliconFlow/DeepSeek/Ollama) 与外部服务免受级联雪崩冲击。
"""

from __future__ import annotations

import asyncio
import time
from enum import Enum
from typing import Any, Awaitable, Callable, TypeVar, Optional
import logging

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitState(str, Enum):
    """熔断器状态：关闭（正常）、打开（快速失败）、半开（试探探测）"""
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """生产级三态熔断器

    状态流转：
    - Closed：正常放行。连续失败达到 failure_threshold 时跳闸进入 OPEN。
    - Open：快速失败，直接抛出 CircuitBreakerOpenException，避免下游请求堆积。
      经过 recovery_timeout 后自动进入 HALF_OPEN。
    - Half-Open：允许最多 half_open_max 次试探调用。
      - 试探全部成功 -> 恢复 CLOSED，失败计数清零。
      - 试探中有任何一次失败 -> 重新切回 OPEN，延长等待窗口。
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max: int = 2,
        name: str = "llm_circuit",
    ) -> None:
        self.failure_threshold = max(1, failure_threshold)
        self.recovery_timeout = max(0.1, recovery_timeout)
        self.half_open_max = max(1, half_open_max)
        self.name = name

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: Optional[float] = None
        self._half_open_attempts = 0
        self._half_open_successes = 0
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        """获取当前熔断器状态"""
        return self._state

    def _should_attempt_reset(self) -> bool:
        """Open 状态下是否已过冷却窗口，可转为 Half-Open 试探"""
        if self._last_failure_time is None:
            return True
        return (time.monotonic() - self._last_failure_time) >= self.recovery_timeout

    def _record_success(self) -> None:
        """记录成功调用"""
        if self._state == CircuitState.HALF_OPEN:
            self._half_open_successes += 1
            if self._half_open_successes >= self.half_open_max:
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                self._half_open_attempts = 0
                self._half_open_successes = 0
                self._last_failure_time = None
                logger.info("🛡️ [CircuitBreaker][%s] 试探调用连续成功，状态恢复为: CLOSED", self.name)
        else:
            # 正常闭合状态下，偶尔成功可衰减失败计数
            if self._failure_count > 0:
                self._failure_count = max(0, self._failure_count - 1)

    def _record_failure(self, error: Exception) -> None:
        """记录异常失败"""
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        logger.warning(
            "🛡️ [CircuitBreaker][%s] 捕获异常: %s (连续失败: %d/%d, 当前状态: %s)",
            self.name,
            str(error),
            self._failure_count,
            self.failure_threshold,
            self._state.value,
        )

        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.OPEN
            self._half_open_attempts = 0
            self._half_open_successes = 0
            logger.error("🛡️ [CircuitBreaker][%s] 半开试探失败，立即重新进入: OPEN 状态", self.name)
        elif self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN
            logger.error(
                "🛡️ [CircuitBreaker][%s] 连续失败达到阈值 %d，熔断器跳闸切入: OPEN (快速失败冷却期 %.1fs)",
                self.name,
                self.failure_threshold,
                self.recovery_timeout,
            )

    async def call(
        self,
        func: Callable[..., Awaitable[T]],
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """通过熔断器执行异步调用"""
        async with self._lock:
            if self._state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_attempts = 0
                    self._half_open_successes = 0
                    logger.info("🛡️ [CircuitBreaker][%s] 冷却期已过，进入 HALF_OPEN 试探状态", self.name)
                else:
                    remaining = self.recovery_timeout - (time.monotonic() - (self._last_failure_time or 0))
                    raise RuntimeError(
                        f"🛡️ 熔断器 [{self.name}] 处于 OPEN 状态，下游服务不可用，快速失败 (剩余冷却: {max(0.0, remaining):.1f}s)"
                    )

            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_attempts >= self.half_open_max:
                    raise RuntimeError(
                        f"🛡️ 熔断器 [{self.name}] 处于 HALF_OPEN 状态，试探并发数已达上限 ({self.half_open_max})"
                    )
                self._half_open_attempts += 1

        try:
            result = await func(*args, **kwargs)
        except Exception as exc:
            async with self._lock:
                self._record_failure(exc)
            raise

        async with self._lock:
            self._record_success()

        return result


# 全局默认 LLM 熔断器实例
llm_circuit_breaker = CircuitBreaker(
    failure_threshold=5,
    recovery_timeout=30.0,
    half_open_max=2,
    name="llm_upstream"
)
