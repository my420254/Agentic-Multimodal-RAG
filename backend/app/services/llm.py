"""
LLM 服务
"""

from openai import AsyncOpenAI, APIConnectionError, RateLimitError, InternalServerError
import httpx
from typing import List, Dict, AsyncGenerator, Any
from langchain_openai import ChatOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, before_sleep_log
import logging

from app.core.config import get_settings
from app.core.circuit_breaker import llm_circuit_breaker

settings = get_settings()
logger = logging.getLogger(__name__)

class LLMService:
    """LLM 服务 (集成重试 + 三态熔断保护)"""

    def __init__(self, base_url: str = None, api_key: str = None, model: str = None):
        self.base_url = base_url or settings.LLM_BASE_URL
        
        # 自动修正 base_url: 如果包含 /chat/completions 后缀则移除
        if self.base_url:
            self.base_url = self.base_url.rstrip("/")
            if self.base_url.endswith("/chat/completions"):
                self.base_url = self.base_url[:-17]
            self.base_url = self.base_url.rstrip("/")

        self.api_key = api_key or settings.LLM_API_KEY
        if model in [None, "", "sys_llm", "default", "system"]:
            self.model = settings.LLM_MODEL
        else:
            self.model = model
        self._client = None
        self.circuit_breaker = llm_circuit_breaker

    def _get_client(self):
        if not self._client:
            self._client = AsyncOpenAI(
                base_url=self.base_url,
                api_key=self.api_key,
                timeout=120.0,
                http_client=httpx.AsyncClient(
                    trust_env=True
                )
            )
        return self._client

    @retry(
        retry=retry_if_exception_type((APIConnectionError, RateLimitError, InternalServerError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        before_sleep=before_sleep_log(logger, logging.WARNING)
    )
    async def rewrite_query(self, query: str) -> str:
        """问题改写 (受熔断器保护)"""
        system_prompt = """你是一个问题优化助手。请将用户输入的口语化问题改写为更清晰、更完整的查询语句。
要求：
1. 保持原意不变
2. 补充缺失的上下文
3. 使用更专业的表述
4. 直接返回改写后的问题，不要添加解释"""

        client = self._get_client()
        
        async def _do_call():
            response = await client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": query},
                ],
                max_tokens=200,
                temperature=0.3,
            )
            return response.choices[0].message.content.strip()

        try:
            return await self.circuit_breaker.call(_do_call)
        except Exception as e:
            logger.error("Rewrite Query Error: %s", e)
            raise e

    @retry(
        retry=retry_if_exception_type((APIConnectionError, RateLimitError, InternalServerError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        before_sleep=before_sleep_log(logger, logging.WARNING)
    )
    async def generate_stream(
        self,
        messages: List[Dict[str, str]],
        system_prompt: str = None,
        model_id: str = None,
        temperature: float = 0.7,
    ) -> AsyncGenerator[str, None]:
        """
        流式生成回答 (带熔断检测与优雅降级)
        """
        # 预先检查熔断器状态，若已处于 OPEN 状态则直接快速失败，避免长时间悬挂
        if self.circuit_breaker.state.value == "open":
            if not self.circuit_breaker._should_attempt_reset():
                raise RuntimeError(f"下游大模型服务熔断保护中 [{self.circuit_breaker.name}]，请稍后重试。")

        client = self._get_client()
        if model_id in [None, "", "sys_llm", "default", "system"]:
            target_model = self.model
        else:
            target_model = model_id

        # 构造消息列表
        request_messages = []
        if system_prompt:
            request_messages.append({"role": "system", "content": system_prompt})
        
        request_messages.extend(messages)

        try:
            logger.debug("Sending streaming request to %s", target_model)
            response = await client.chat.completions.create(
                model=target_model,
                messages=request_messages,
                stream=True,
                temperature=temperature,
            )

            async for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
            
            # 流式成功结束后通知熔断器记录成功
            self.circuit_breaker._record_success()

        except Exception as e:
            self.circuit_breaker._record_failure(e)
            logger.error("LLM Stream Generate Error: %s", e)
            raise e

    @retry(
        retry=retry_if_exception_type((APIConnectionError, RateLimitError, InternalServerError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        before_sleep=before_sleep_log(logger, logging.WARNING)
    )
    async def generate(
        self,
        messages: List[Dict[str, str]],
        system_prompt: str = None,
        model_id: str = None,
    ) -> str:
        """非流式生成回答 (受熔断器保护)"""
        client = self._get_client()
        target_model = model_id or self.model
        request_messages = []

        if system_prompt:
            request_messages.append({"role": "system", "content": system_prompt})

        request_messages.extend(messages)

        async def _do_call():
            response = await client.chat.completions.create(
                model=target_model,
                messages=request_messages,
                max_tokens=2000,
                temperature=0.7,
            )
            return response.choices[0].message.content

        try:
            return await self.circuit_breaker.call(_do_call)
        except Exception as e:
            logger.error("LLM Generate Error: %s", e)
            raise e

    def get_chat_model(self, temperature: float = 0.5, streaming: bool = True, max_tokens: int = None) -> ChatOpenAI:
        """获取 LangChain ChatOpenAI 实例"""
        return ChatOpenAI(
            model=self.model,
            openai_api_key=self.api_key,
            openai_api_base=self.base_url,
            temperature=temperature,
            streaming=streaming,
            max_tokens=max_tokens
        )
