"""
应用配置模块
"""

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import List, Optional
import os


def _sanitize_no_proxy() -> None:
    """
    清洗 NO_PROXY 中 httpx 无法解析的条目。

    当前环境包含 `<local>` 与 `[::1]`，httpx 在 trust_env=True 时会把它们当作
    代理 URL 解析，抛出 `Invalid port: ':1]'`，导致 embedding/LLM 全部失败。
    这里只移除非法项，保留 localhost/127.0.0.1 等有效直连规则；不修改代理地址。
    """
    invalid = {"<local>", "[::1]", "::1"}
    for key in ("NO_PROXY", "no_proxy"):
        raw = os.environ.get(key)
        if not raw:
            continue
        parts = []
        for item in raw.split(","):
            item = item.strip()
            if item and item.lower() not in invalid:
                parts.append(item)
        os.environ[key] = ",".join(parts)


_sanitize_no_proxy()


class Settings(BaseSettings):
    """应用配置"""

    # 服务配置
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    ENV: str = "dev"
    # PostgreSQL 启动时自动执行 Alembic upgrade head；生产多实例建议 false，独立跑 migration
    AUTO_MIGRATE: bool = True
    # 逗号分隔；不要在生产使用 *。前端默认 3000，Vite 默认 5173。
    CORS_ORIGINS: str = (
        "http://127.0.0.1:3000,http://localhost:3000,"
        "http://127.0.0.1:3001,http://localhost:3001,"
        "http://127.0.0.1:5173,http://localhost:5173"
    )
    # /ready：LLM 不可用是否视为未就绪；默认只标记 degraded
    READY_REQUIRE_LLM: bool = False
    READY_CHECK_LLM: bool = True

    # 数据库与存储 (生产级 PostgreSQL + Redis)
    DATABASE_URL: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/agent_db"
    REDIS_URL: str = "redis://localhost:6379/0"
    CHROMA_DB_DIR: str = "./storage/chroma_db"
    VECTOR_BACKEND: str = "pgvector"  # pgvector | chroma
    REQUEST_LOG_ENABLED: bool = True  # 写 request_logs（测试环境关闭）
    TOOL_TIMEOUT_SECONDS: float = 20.0
    TOOL_MAX_RETRIES: int = 1
    PGVECTOR_DIM: int = 1024
    UPLOAD_DIR: str = "./storage/uploads"
    IMAGE_DIR: str = "./storage/images"

    # LLM 配置
    LLM_BASE_URL: str = "http://localhost:11434/v1"
    LLM_API_KEY: str = "ollama"
    LLM_MODEL: str = "qwen2.5:7b"

    # Embedding 配置
    EMBEDDING_BASE_URL: str = "http://localhost:11434/v1"
    EMBEDDING_API_KEY: str = "ollama"
    EMBEDDING_MODEL: str = "nomic-embed-text-v1.5-multimodal-my-nomic-v1.5-8k"
    EMBEDDING_MAX_CONTEXT_LENGTH: int = 8196  # Embedding 模型最大上下文长度

    # VLM 配置
    VLM_BASE_URL: str = "http://localhost:11434/v1"
    VLM_API_KEY: str = "ollama"
    VLM_MODEL: str = "llava:7b"

    # 任务配置
    MAX_PARSING_WORKERS: int = 10

    # 切分配置
    CHUNK_SIZE: int = 500
    CHUNK_OVERLAP: int = 50

    # VLM 提示词
    VLM_PROMPT: str = "请详细描述这张图片的内容，包括图表中的数据趋势、关键文字信息。"

    # 文件限制
    MAX_FILE_SIZE: int = 100 * 1024 * 1024  # 100MB
    ALLOWED_EXTENSIONS: List[str] = [".pdf", ".docx", ".xlsx", ".csv", ".txt", ".md", ".jpg", ".jpeg", ".png", ".bmp", ".webp"]

    # ==================== 检索配置 ====================
    RETRIEVAL_TOP_K: int = 100              # 粗筛数量
    RETRIEVAL_DEFAULT_MODE: str = "hybrid"  # 默认检索模式: vector | fulltext | hybrid
    RETRIEVAL_VECTOR_WEIGHT: float = 0.7    # 默认向量权重
    RETRIEVAL_BM25_WEIGHT: float = 0.3      # 默认 BM25 权重

    # BM25 检索配置
    BM25_K1: float = 1.5                    # BM25 词频饱和参数
    BM25_B: float = 0.75                    # BM25 文档长度归一化参数
    BM25_TOP_K: int = 50                    # BM25 检索返回数量

    # ==================== Rerank 配置 ====================
    RERANK_MAX_CONTEXT: int = 8196          # Rerank 单批最大 token
    RERANK_DEFAULT_TOP_K: int = 20          # 默认 Rerank 返回数量
    RERANK_MIN_TOP_K: int = 5               # 最小 Rerank 返回数量
    RERANK_MAX_TOP_K: int = 50              # 最大 Rerank 返回数量

    # ==================== 上下文扩展配置 ====================
    CONTEXT_WINDOW_SIZE: int = 1            # 前后上下文 chunk 数
    MAX_PARENT_LENGTH: int = 4000           # 父文档最大拼接长度（字符）

    # ==================== 缓存配置 ====================
    RETRIEVAL_CACHE_TTL: int = 300          # 检索缓存 TTL（秒）
    RETRIEVAL_CACHE_ENABLED: bool = True    # 是否启用检索缓存

    # ==================== 对话配置 ====================
    MAX_CHAT_HISTORY_ROUNDS: int = 20       # 最大保留历史对话轮数

    # ==================== 鉴权配置 ====================
    # 必填，无默认值：未配置或过短时应用启动直接失败，绝不使用内置密钥兜底。
    JWT_SECRET: str = Field(
        ...,
        min_length=32,
        repr=False,
        description="JWT 签名密钥（至少 32 字符）。仅从环境变量/本地 .env 注入。",
    )
    JWT_ALG: str = "HS256"
    ACCESS_TTL_MIN: int = 15
    REFRESH_TTL_DAYS: int = 7

    # ==================== 记忆持久化 ====================
    # true：会话/消息/画像以 PostgreSQL 为真源，Redis 仅作缓存（重启/过期不丢）；
    # false：兼容旧行为，仅 Redis/内存（测试可关闭，避免污染 agent_db）。
    MEMORY_PERSISTENCE: bool = True

    # ==================== Langfuse / tracing ====================
    # 没有 public/secret key 时自动 no-op，不影响聊天与测试。
    LANGFUSE_ENABLED: bool = True
    LANGFUSE_PUBLIC_KEY: Optional[str] = None
    LANGFUSE_SECRET_KEY: Optional[str] = None
    LANGFUSE_HOST: str = "https://cloud.langfuse.com"
    # metadata：只发长度/ID；redacted：正则脱敏后发送；full：仅自托管环境
    TRACE_CONTENT_MODE: str = "redacted"
    # Prompt Management：production label + 本地缓存 + 失败回退代码默认值
    LANGFUSE_PROMPT_LABEL: str = "production"
    LANGFUSE_PROMPT_CACHE_TTL: int = 300
    LANGFUSE_PROMPT_FETCH_TIMEOUT: float = 2.0

    @field_validator("JWT_SECRET")
    @classmethod
    def validate_jwt_secret(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 32:
            raise ValueError("JWT_SECRET 至少需要 32 个字符，请用 secrets.token_urlsafe 生成")
        if value.lower() in {"change-me", "changeme", "secret", "dev", "test"}:
            raise ValueError("JWT_SECRET 不能使用占位值")
        return value

    @field_validator("JWT_ALG")
    @classmethod
    def validate_jwt_alg(cls, value: str) -> str:
        if value != "HS256":
            raise ValueError("当前仅支持 JWT_ALG=HS256")
        return value

    @field_validator("ACCESS_TTL_MIN", "REFRESH_TTL_DAYS")
    @classmethod
    def validate_positive_ttl(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("ACCESS_TTL_MIN / REFRESH_TTL_DAYS 必须为正整数")
        return value

    @field_validator("TRACE_CONTENT_MODE")
    @classmethod
    def validate_trace_content_mode(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in {"metadata", "redacted", "full"}:
            raise ValueError("TRACE_CONTENT_MODE 必须是 metadata / redacted / full")
        return value

    @property
    def cors_origins(self) -> List[str]:
        return [item.strip() for item in self.CORS_ORIGINS.split(",") if item.strip()]

    class Config:
        env_file = (".env", "backend/.env")
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    """获取配置单例"""
    return Settings()


# 确保存储目录存在
def ensure_directories():
    """确保必要的目录存在"""
    settings = get_settings()
    dirs = [
        settings.UPLOAD_DIR,
        settings.IMAGE_DIR,
        settings.CHROMA_DB_DIR,
    ]
    for d in dirs:
        os.makedirs(d, exist_ok=True)
