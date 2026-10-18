"""
三层分层记忆管理系统 (Hierarchical Memory System)

体系结构：
- L1 (短期工作记忆 / Working Buffer): 
  基于 Redis List 维护当前会话最近 K 轮活跃对话，确保多轮指代消解与连贯性。
- L2 (中期会话滚动摘要 / Rolling Summary Memory): 
  当会话长度超限时，自动触发轻量 LLM 增量压缩前序历史为摘要，避免长会话 Token 爆炸。
- L3 (长期用户画像与语义偏好 / Profile Memory): 
  基于 Redis Hash 维护用户的长效习惯与偏好（如技术栈、语言、格式偏好），跨会话主动注入。
"""

import json
import logging
import time
from typing import List, Dict, Any, Optional
import redis

from app.core.config import get_settings
from app.services.llm import LLMService

logger = logging.getLogger(__name__)
settings = get_settings()


class MemoryService:
    """分层记忆管理服务"""

    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url or settings.REDIS_URL
        self._redis_client: Optional[redis.Redis] = None
        self._fallback_memory: Dict[str, Any] = {} # 内存降级兜底

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
                    max_connections=20
                )
                r = redis.Redis(connection_pool=pool)
                r.ping()
                self._redis_client = r
                logger.info("✅ [MemoryService] Redis 连接成功: %s", self.redis_url)
            except Exception as e:
                logger.warning("⚠️ [MemoryService] Redis 无法连接 (%s)，自动降级为本地内存缓存", str(e))
                self._redis_client = None
        return self._redis_client

    # ==================== L1: 短期活跃会话记忆 ====================

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        ttl: int = 86400 * 7
    ) -> None:
        """
        向当前会话追加一条消息 (原子入队)
        """
        msg_obj = {
            "role": role,
            "content": content,
            "timestamp": time.time()
        }
        msg_json = json.dumps(msg_obj, ensure_ascii=False)
        key = f"chat:session:{session_id}:messages"

        r = self.client
        if r:
            try:
                r.rpush(key, msg_json)
                r.expire(key, ttl)
                return
            except Exception as e:
                logger.error("Redis rpush 失败: %s", e)

        # 降级内存
        if key not in self._fallback_memory:
            self._fallback_memory[key] = []
        self._fallback_memory[key].append(msg_obj)

    def get_recent_messages(self, session_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        获取最近的 N 条对话记录 (保持时序)
        """
        key = f"chat:session:{session_id}:messages"
        r = self.client
        if r:
            try:
                # 获取最后 limit 条
                raw_items = r.lrange(key, -limit, -1)
                return [json.loads(item) for item in raw_items]
            except Exception as e:
                logger.error("Redis lrange 失败: %s", e)

        # 降级内存
        items = self._fallback_memory.get(key, [])
        return items[-limit:]

    def get_all_messages_count(self, session_id: str) -> int:
        """获取当前会话总消息数"""
        key = f"chat:session:{session_id}:messages"
        r = self.client
        if r:
            try:
                return r.llen(key)
            except Exception:
                pass
        return len(self._fallback_memory.get(key, []))

    def clear_session(self, session_id: str) -> None:
        """清空指定会话的全部记忆 (L1 + L2)"""
        msg_key = f"chat:session:{session_id}:messages"
        summary_key = f"chat:session:{session_id}:summary"
        r = self.client
        if r:
            try:
                r.delete(msg_key, summary_key)
            except Exception as e:
                logger.error("Redis delete 失败: %s", e)

        self._fallback_memory.pop(msg_key, None)
        self._fallback_memory.pop(summary_key, None)

    # ==================== L2: 中期滚动会话摘要 ====================

    def get_summary(self, session_id: str) -> Optional[str]:
        """获取当前会话的背景摘要"""
        key = f"chat:session:{session_id}:summary"
        r = self.client
        if r:
            try:
                return r.get(key)
            except Exception:
                pass
        return self._fallback_memory.get(key)

    def set_summary(self, session_id: str, summary: str, ttl: int = 86400 * 7) -> None:
        """存储更新后的会话摘要"""
        key = f"chat:session:{session_id}:summary"
        r = self.client
        if r:
            try:
                r.setex(key, ttl, summary)
                return
            except Exception as e:
                logger.error("Redis setex summary 失败: %s", e)
        self._fallback_memory[key] = summary

    def update_summary_if_needed(
        self,
        session_id: str,
        llm_service: LLMService,
        threshold: int = 6,
        keep_recent: int = 4
    ) -> Optional[str]:
        """
        增量摘要压缩：当总消息数超过 threshold 时，将较早的历史消息压缩为摘要，
        仅保留最近 keep_recent 条原始消息活跃。
        """
        total_count = self.get_all_messages_count(session_id)
        if total_count <= threshold:
            return self.get_summary(session_id)

        # 读取需要被压缩的旧消息 (除最后 keep_recent 之外的所有消息)
        key = f"chat:session:{session_id}:messages"
        r = self.client
        older_messages = []
        if r:
            try:
                raw_older = r.lrange(key, 0, -(keep_recent + 1))
                older_messages = [json.loads(m) for m in raw_older]
            except Exception as e:
                logger.error("读取需压缩消息失败: %s", e)
        else:
            items = self._fallback_memory.get(key, [])
            older_messages = items[:-keep_recent]

        if not older_messages:
            return self.get_summary(session_id)

        # 构建增量压缩 Prompt
        prev_summary = self.get_summary(session_id) or "无前序背景。"
        formatted_dialog = "\n".join([f"{m['role'].upper()}: {m['content']}" for m in older_messages])

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
                max_tokens=300
            )
            if new_summary and new_summary.strip():
                clean_summary = new_summary.strip()
                self.set_summary(session_id, clean_summary)
                logger.info("🧠 [MemoryService] 会话 %s 增量摘要更新完成 (共压缩 %d 条消息)", session_id, len(older_messages))
                return clean_summary
        except Exception as e:
            logger.error("LLM 生成摘要失败: %s", e)

        return self.get_summary(session_id)

    # ==================== L3: 长期用户画像与偏好 ====================

    def get_user_profile(self, user_id: str) -> Dict[str, str]:
        """获取用户的长效画像与偏好配置"""
        key = f"chat:user:{user_id}:profile"
        r = self.client
        if r:
            try:
                return r.hgetall(key) or {}
            except Exception as e:
                logger.error("Redis hgetall 失败: %s", e)
        return self._fallback_memory.get(key, {})

    def set_user_preference(self, user_id: str, field: str, value: str) -> None:
        """存储用户特定的偏好标签"""
        key = f"chat:user:{user_id}:profile"
        r = self.client
        if r:
            try:
                r.hset(key, field, value)
                return
            except Exception as e:
                logger.error("Redis hset 失败: %s", e)

        if key not in self._fallback_memory:
            self._fallback_memory[key] = {}
        self._fallback_memory[key][field] = value

    def extract_preference_if_any(
        self,
        user_id: str,
        user_text: str,
        llm_service: Optional[LLMService] = None
    ) -> None:
        if llm_service is None:
            # 轻量级本地规则提取备选
            if '倾向于' in user_text or '喜欢' in user_text or '偏好' in user_text:
                self.set_user_preference(user_id, 'preference', user_text[:100])
            return
        """
        从用户提问中安全提取长期偏好（防误判与对抗过滤）
        避免 '你知道我喜欢什么吗' 被误写入记忆
        """
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
                max_tokens=100
            )
            # 解析 JSON
            res = res.strip().replace("```json", "").replace("```", "").strip()
            data = json.loads(res)
            if isinstance(data, dict):
                for k, v in data.items():
                    if k and v:
                        self.set_user_preference(user_id, str(k), str(v))
                        logger.info("🎯 [MemoryService] 识别并写入用户 %s 长期偏好: %s -> %s", user_id, k, v)
        except Exception:
            pass

    # ==================== 统一上下文组装器 ====================

    def assemble_context_for_prompt(
        self,
        session_id: str,
        user_id: str = "default_user",
        recent_limit: int = 6
    ) -> Dict[str, Any]:
        """
        为 Agent 和 LLM 统一组装三层记忆上下文：
        - L3: 用户偏好
        - L2: 前序滚动摘要
        - L1: 最近活跃消息列表
        """
        # 1. 读取 L3 长期偏好
        profile = self.get_user_profile(user_id)
        profile_text = ""
        if profile:
            profile_lines = [f"- {k}: {v}" for k, v in profile.items()]
            profile_text = "【用户长期偏好与环境】:\n" + "\n".join(profile_lines)

        # 2. 读取 L2 增量摘要
        summary = self.get_summary(session_id)
        summary_text = ""
        if summary:
            summary_text = f"【前序会话背景摘要】:\n{summary}"

        # 3. 读取 L1 活跃消息
        recent_msgs = self.get_recent_messages(session_id, limit=recent_limit)

        return {
            "profile_text": profile_text,
            "summary_text": summary_text,
            "recent_messages": recent_msgs
        }


# 全局单例
memory_service = MemoryService()

