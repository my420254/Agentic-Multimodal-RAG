"""
基于 Redis 7 ZSet + Lua 脚本的高性能分布式滑动窗口限流器
支持 1000+ QPS 高并发防刷与突发流量削峰
针对无 Redis 环境提供内存双端队列 (collections.deque) 高性能回退
"""

import time
import logging
from typing import Optional
from collections import deque

from app.core.config import get_settings
from app.services.memory_service import memory_service

logger = logging.getLogger(__name__)
settings = get_settings()

# Redis Lua 脚本：原子滑动窗口限流
# KEYS[1]: 限流 key
# ARGV[1]: 当前时间戳 (毫秒)
# ARGV[2]: 窗口大小 (毫秒)
# ARGV[3]: 窗口内允许的最大请求数
SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local clear_before = now - window

-- 清理窗口外的历史请求记录
redis.call('ZREMRANGEBYSCORE', key, '-inf', clear_before)

-- 获取当前窗口内的请求数
local current_count = redis.call('ZCARD', key)

if current_count < limit then
    -- 记录本次请求 (score 和 member 均使用时间戳+微秒保证唯一)
    redis.call('ZADD', key, now, tostring(now) .. '-' .. tostring(redis.call('INCR', key .. ':seq')))
    -- 设置过期时间保证内存自愈释放
    redis.call('EXPIRE', key, math.ceil(window / 1000) + 1)
    return 1
else
    return 0
end
"""


class SlidingWindowRateLimiter:
    """原子滑动窗口限流器"""

    def __init__(self, limit: int = 1000, window_seconds: float = 1.0):
        self.limit = limit
        self.window_ms = int(window_seconds * 1000)
        self._memory_windows: dict[str, deque] = {}
        self._lua_script_sha = None

    def is_allowed(self, client_id: str = "global") -> bool:
        """检查请求是否允许通过"""
        now_ms = int(time.time() * 1000)
        redis_client = memory_service.client

        if redis_client is not None:
            try:
                key = f"rate_limit:{client_id}"
                # 使用 EVAL 执行原子限流 Lua 脚本
                result = redis_client.eval(
                    SLIDING_WINDOW_LUA,
                    1,
                    key,
                    now_ms,
                    self.window_ms,
                    self.limit
                )
                return bool(result == 1)
            except Exception as e:
                logger.warning(f"[RateLimiter] Redis 限流降级至本地内存: {str(e)}")

        # 本地内存滑动窗口降级
        if client_id not in self._memory_windows:
            self._memory_windows[client_id] = deque()

        q = self._memory_windows[client_id]
        clear_before = now_ms - self.window_ms

        while q and q[0] < clear_before:
            q.popleft()

        if len(q) < self.limit:
            q.append(now_ms)
            return True
        else:
            return False


# 全局默认限流器 (1000 QPS 窗口)
global_rate_limiter = SlidingWindowRateLimiter(limit=1000, window_seconds=1.0)
