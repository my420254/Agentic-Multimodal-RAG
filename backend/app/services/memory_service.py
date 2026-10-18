"""
三层分层记忆管理系统 (Hierarchical Memory System)

体系结构：
- L1 (短期工作记忆 / Working Buffer):
  基于 Redis List 维护当前会话最近 K 轮活跃对话，确保多轮指代消解与连贯性。
- L2 (中期会话滚动摘要 / Rolling Summary Memory):
  当会话长度超限时，自动触发轻量 LLM 增量压缩前序历史为摘要，避免长会话 Token 爆炸。
- L3 (长期用户画像与语义偏好 / Profile Memory):
  基于 Redis Hash 维护用户的长效习惯与偏好（如技术栈、语言、格式偏好），跨会话主动注入。

多租户隔离（W1）：
- 所有业务数据 key 统一为 u:{uid}:...；
- user_id 必须来自鉴权层（token），所有公开方法都要求显式传入，没有默认用户；
- 会话归属索引 session_owner:{sid} 只保存 uid，用于判断“该会话是否存在/是否属于当前用户”，
  不保存任何对话正文。它必须跨用户可见，否则无法在不泄露内容的前提下返回 404。
"""

import json
import logging
import threading
import time
from typing import List, Dict, Any, Optional

import redis

from app.core.config import get_settings
from app.services.llm import LLMService

logger = logging.getLogger(__name__)
settings = get_settings()

# 会话归属索引与 L1 消息保持同样的 7 天生命周期。
SESSION_OWNER_TTL_SECONDS = 86400 * 7


class MemoryService:
    """分层记忆管理服务（所有方法均要求显式 user_id）"""

    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url or settings.REDIS_URL
        self._redis_client: Optional[redis.Redis] = None
        self._fallback_memory: Dict[str, Any] = {}  # 内存降级兜底
        self._fallback_lock = threading.RLock()

    @property
    def client(self) -> Optional[redis.Redis]:
        """获取或初始化 Redis 客户端 (带健康重试与降级)"""
        if self._redis_client is None:
            try:
                pool = redis.ConnectionPool.from_url(
                    self.redis_url,
                    decode_responses=True,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                    max_connections=20,
                )
                r = redis.Redis(connection_pool=pool)
                r.ping()
                self._redis_client = r
                logger.info("✅ [MemoryService] Redis 连接成功: %s", self.redis_url)
            except Exception as e:
                logger.warning(
                    "⚠️ [MemoryService] Redis 无法连接 (%s)，自动降级为本地内存缓存",
                    str(e),
                )
                self._redis_client = None
        return self._redis_client

    # ==================== 隔离约束 ====================

    @staticmethod
    def _require_user_id(user_id: str) -> str:
        if not isinstance(user_id, str) or not user_id.strip():
            raise ValueError("user_id is required and must come from the authenticated token")
        return user_id.strip()

    @staticmethod
    def _require_session_id(session_id: str) -> str:
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("session_id is required")
        return session_id.strip()

    @staticmethod
    def _messages_key(user_id: str, session_id: str) -> str:
        return f"u:{user_id}:session:{session_id}:messages"

    @staticmethod
    def _summary_key(user_id: str, session_id: str) -> str:
        return f"u:{user_id}:session:{session_id}:summary"

    @staticmethod
    def _profile_key(user_id: str) -> str:
        return f"u:{user_id}:profile"

    @staticmethod
    def _owner_key(session_id: str) -> str:
        return f"session_owner:{session_id}"

    # ==================== 会话归属 ====================

    def claim_session(self, user_id: str, session_id: str, ttl: int = SESSION_OWNER_TTL_SECONDS) -> bool:
        """
        认领会话归属。

        - 会话不存在：原子创建归属并返回 True（允许新会话）；
        - 已属于当前用户：返回 True；
        - 已属于其他用户：返回 False（调用方必须返回 404，不能泄露存在性）。
        """
        uid = self._require_user_id(user_id)
        sid = self._require_session_id(session_id)
        owner_key = self._owner_key(sid)

        r = self.client
        if r:
            try:
                if r.set(owner_key, uid, nx=True, ex=ttl):
                    return True
                return r.get(owner_key) == uid
            except Exception as e:
                logger.error("Redis claim_session 失败: %s", e)

        with self._fallback_lock:
            owner = self._fallback_memory.get(owner_key)
            if owner is None:
                self._fallback_memory[owner_key] = uid
                return True
            return owner == uid

    def get_session_owner(self, session_id: str) -> Optional[str]:
        """读取会话归属；不存在或读失败返回 None。"""
        sid = self._require_session_id(session_id)
        owner_key = self._owner_key(sid)

        r = self.client
        if r:
            try:
                return r.get(owner_key)
            except Exception as e:
                logger.error("Redis get_session_owner 失败: %s", e)

        with self._fallback_lock:
            return self._fallback_memory.get(owner_key)

    def owns_session(self, user_id: str, session_id: str) -> bool:
        uid = self._require_user_id(user_id)
        return self.get_session_owner(session_id) == uid

    # ==================== L1: 短期活跃会话记忆 ====================

    def add_message(
        self,
        user_id: str,
        session_id: str,
        role: str,
        content: str,
        ttl: int = 86400 * 7,
    ) -> None:
        """向当前用户当前会话追加一条消息 (原子入队)。"""
        uid = self._require_user_id(user_id)
        sid = self._require_session_id(session_id)
        msg_obj = {
            "role": role,
            "content": content,
            "timestamp": time.time(),
        }
        msg_json = json.dumps(msg_obj, ensure_ascii=False)
        key = self._messages_key(uid, sid)

        r = self.client
        if r:
            try:
                r.rpush(key, msg_json)
                r.expire(key, ttl)
                return
            except Exception as e:
                logger.error("Redis rpush 失败: %s", e)

        with self._fallback_lock:
            self._fallback_memory.setdefault(key, []).append(msg_obj)

    def get_recent_messages(self, user_id: str, session_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """获取当前用户当前会话最近的 N 条对话记录 (保持时序)。"""
        uid = self._require_user_id(user_id)
        sid = self._require_session_id(session_id)
        key = self._messages_key(uid, sid)

        r = self.client
        if r:
            try:
                raw_items = r.lrange(key, -limit, -1)
                return [json.loads(item) for item in raw_items]
            except Exception as e:
                logger.error("Redis lrange 失败: %s", e)

        with self._fallback_lock:
            items = list(self._fallback_memory.get(key, []))
        return items[-limit:]

    def get_all_messages_count(self, user_id: str, session_id: str) -> int:
        """获取当前用户当前会话总消息数。"""
        uid = self._require_user_id(user_id)
        sid = self._require_session_id(session_id)
        key = self._messages_key(uid, sid)

        r = self.client
        if r:
            try:
                return r.llen(key)
            except Exception:
                pass

        with self._fallback_lock:
            return len(self._fallback_memory.get(key, []))

    def clear_session(self, user_id: str, session_id: str) -> None:
        """清空当前用户指定会话的全部记忆 (L1 + L2)，并释放本人持有的归属索引。"""
        uid = self._require_user_id(user_id)
        sid = self._require_session_id(session_id)
        msg_key = self._messages_key(uid, sid)
        summary_key = self._summary_key(uid, sid)
        owner_key = self._owner_key(sid)

        r = self.client
        if r:
            try:
                r.delete(msg_key, summary_key)
                # 只有归属确实是当前用户时才删除索引，避免误删他人会话。
                if r.get(owner_key) == uid:
                    r.delete(owner_key)
            except Exception as e:
                logger.error("Redis delete 失败: %s", e)

        with self._fallback_lock:
            self._fallback_memory.pop(msg_key, None)
            self._fallback_memory.pop(summary_key, None)
            if self._fallback_memory.get(owner_key) == uid:
                self._fallback_memory.pop(owner_key, None)

    # ==================== L2: 中期滚动会话摘要 ====================

    def get_summary(self, user_id: str, session_id: str) -> Optional[str]:
        """获取当前用户当前会话的背景摘要。"""
        uid = self._require_user_id(user_id)
        sid = self._require_session_id(session_id)
        key = self._summary_key(uid, sid)

        r = self.client
        if r:
            try:
                return r.get(key)
            except Exception:
                pass

        with self._fallback_lock:
            return self._fallback_memory.get(key)

    def set_summary(self, user_id: str, session_id: str, summary: str, ttl: int = 86400 * 7) -> None:
        """存储当前用户当前会话更新后的摘要。"""
        uid = self._require_user_id(user_id)
        sid = self._require_session_id(session_id)
        key = self._summary_key(uid, sid)

        r = self.client
        if r:
            try:
                r.set(key, summary, ex=ttl)
                return
            except Exception as e:
                logger.error("Redis set summary 失败: %s", e)

        with self._fallback_lock:
            self._fallback_memory[key] = summary

    def update_summary_if_needed(
        self,
        user_id: str,
        session_id: str,
        llm_service: LLMService,
        threshold: int = 6,
        keep_recent: int = 4,
    ) -> Optional[str]:
        """
        增量摘要压缩：当总消息数超过 threshold 时，将较早的历史消息压缩为摘要，
        仅保留最近 keep_recent 条原始消息活跃。
        """
        uid = self._require_user_id(user_id)
        sid = self._require_session_id(session_id)
        total_count = self.get_all_messages_count(uid, sid)
        if total_count <= threshold:
            return self.get_summary(uid, sid)

        key = self._messages_key(uid, sid)
        r = self.client
        older_messages: List[Dict[str, Any]] = []
        if r:
            try:
                raw_older = r.lrange(key, 0, -(keep_recent + 1))
                older_messages = [json.loads(m) for m in raw_older]
            except Exception as e:
                logger.error("读取需压缩消息失败: %s", e)
        else:
            with self._fallback_lock:
                items = list(self._fallback_memory.get(key, []))
            older_messages = items[:-keep_recent]

        if not older_messages:
            return self.get_summary(uid, sid)

        prev_summary = self.get_summary(uid, sid) or "无前序背景。"
        formatted_dialog = "\n".join(
            [f"{m['role'].upper()}: {m['content']}" for m in older_messages]
        )

        compress_prompt = f"""你是一个高效的会话记忆提炼专家。请阅读此前的背景摘要与新增的历史对话，生成一段精炼、准确的【增量滚动摘要】。
要求：
1. 提取讨论的核心主题、关键实体、用户明确的要求、技术参数和结论。
2. 忽略寒暄与无意义的废话。
3. 控制在 200 字以内，作为后续长期对话的背景线索。

【历史既有摘要】:
{prev_summary}

【待压缩对话片段】:
{formatted_dialog}

请输出更新后的完整背景摘要："""

        try:
            new_summary = llm_service.chat_complete(
                messages=[{"role": "user", "content": compress_prompt}],
                temperature=0.3,
                max_tokens=300,
            )
            if new_summary and new_summary.strip():
                clean_summary = new_summary.strip()
                self.set_summary(uid, sid, clean_summary)
                logger.info(
                    "🧠 [MemoryService] 会话 %s 增量摘要更新完成 (共压缩 %d 条消息)",
                    sid,
                    len(older_messages),
                )
                return clean_summary
        except Exception as e:
            logger.error("LLM 生成摘要失败: %s", e)

        return self.get_summary(uid, sid)

    # ==================== L3: 长期用户画像与偏好 ====================

    def get_user_profile(self, user_id: str) -> Dict[str, str]:
        """获取用户的长效画像与偏好配置。"""
        uid = self._require_user_id(user_id)
        key = self._profile_key(uid)

        r = self.client
        if r:
            try:
                return r.hgetall(key) or {}
            except Exception as e:
                logger.error("Redis hgetall 失败: %s", e)

        with self._fallback_lock:
            return dict(self._fallback_memory.get(key, {}))

    def set_user_preference(self, user_id: str, field: str, value: str) -> None:
        """存储用户特定的偏好标签。"""
        uid = self._require_user_id(user_id)
        key = self._profile_key(uid)

        r = self.client
        if r:
            try:
                r.hset(key, field, value)
                return
            except Exception as e:
                logger.error("Redis hset 失败: %s", e)

        with self._fallback_lock:
            self._fallback_memory.setdefault(key, {})[field] = value

    def extract_preference_if_any(
        self,
        user_id: str,
        user_text: str,
        llm_service: Optional[LLMService] = None,
    ) -> None:
        uid = self._require_user_id(user_id)

        if llm_service is None:
            # 轻量级本地规则提取备选
            if "倾向于" in user_text or "喜欢" in user_text or "偏好" in user_text:
                self.set_user_preference(uid, "preference", user_text[:100])
            return

        # 快速特征前置拦截（如果是反问/疑问句，绝不判定为写入偏好）
        if any(kw in user_text for kw in ["你知道我", "你记得我", "我偏好什么", "我是谁", "我喜欢什么吗"]):
            return

        extract_prompt = f"""分析以下用户输入，判断是否包含明确的长期个人偏好设定（如：编程语言习惯、输出格式要求、设备型号）。
如果是明确的声明（例如：“以后回答请用 Python”、“我负责的是 Ubuntu 生产环境”），请提取为 JSON 键值对；
如果是普通提问、临时查询或疑问，请直接输出空 JSON {{}}。

用户输入: "{user_text}"

输出格式严格为单行合法 JSON:"""

        try:
            res = llm_service.chat_complete(
                messages=[{"role": "user", "content": extract_prompt}],
                temperature=0.1,
                max_tokens=100,
            )
            res = res.strip().replace("```json", "").replace("```", "").strip()
            data = json.loads(res)
            if isinstance(data, dict):
                for k, v in data.items():
                    if k and v:
                        self.set_user_preference(uid, str(k), str(v))
                        logger.info("🎯 [MemoryService] 识别并写入用户长期偏好: %s -> %s", k, v)
        except Exception:
            pass

    # ==================== 统一上下文组装器 ====================

    def assemble_context_for_prompt(
        self,
        user_id: str,
        session_id: str,
        recent_limit: int = 6,
    ) -> Dict[str, Any]:
        """
        为 Agent 和 LLM 统一组装三层记忆上下文：
        - L3: 用户偏好
        - L2: 前序滚动摘要
        - L1: 最近活跃消息列表
        """
        uid = self._require_user_id(user_id)
        sid = self._require_session_id(session_id)

        profile = self.get_user_profile(uid)
        profile_text = ""
        if profile:
            profile_lines = [f"- {k}: {v}" for k, v in profile.items()]
            profile_text = "【用户长期偏好与环境】:\n" + "\n".join(profile_lines)

        summary = self.get_summary(uid, sid)
        summary_text = ""
        if summary:
            summary_text = f"【前序会话背景摘要】:\n{summary}"

        recent_msgs = self.get_recent_messages(uid, sid, limit=recent_limit)

        return {
            "profile_text": profile_text,
            "summary_text": summary_text,
            "recent_messages": recent_msgs,
        }


# 全局单例
memory_service = MemoryService()
