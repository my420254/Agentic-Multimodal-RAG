"""
数据库连接配置
"""

from pathlib import Path

from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy.pool import StaticPool
from sqlalchemy import text
from app.core.config import get_settings

settings = get_settings()

# 创建数据库引擎
if "postgresql" in settings.DATABASE_URL or "postgres" in settings.DATABASE_URL:
    engine = create_engine(
        settings.DATABASE_URL,
        echo=settings.ENV == "dev",
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
    )
else:
    # 兼容 SQLite
    connect_args = {"check_same_thread": False, "timeout": 30} if "sqlite" in settings.DATABASE_URL else {}
    is_memory_db = ":memory:" in settings.DATABASE_URL
    engine = create_engine(
        settings.DATABASE_URL,
        echo=settings.ENV == "dev",
        connect_args=connect_args,
        poolclass=StaticPool if is_memory_db else None, 
    )

    from sqlalchemy import event
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


def _run_alembic_upgrade() -> None:
    """在 PostgreSQL 上执行 Alembic upgrade head。

    新增表/列请走 ``alembic revision --autogenerate``，不要再依赖 create_all。
    """
    from alembic import command
    from alembic.config import Config

    backend_dir = Path(__file__).resolve().parents[2]
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    command.upgrade(cfg, "head")


def init_db():
    """初始化数据库。

    - PostgreSQL：Alembic upgrade head（AUTO_MIGRATE=true 时）；
    - SQLite（测试/临时库）：保留 create_all，因为 alembic baseline 使用 pgvector 类型。
    """
    is_pg = "postgresql" in settings.DATABASE_URL or "postgres" in settings.DATABASE_URL
    if is_pg:
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        if settings.AUTO_MIGRATE:
            _run_alembic_upgrade()
        # baseline migration 已包含；这里保留幂等兜底，兼容未 stamp 的旧库。
        with engine.begin() as conn:
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_document_chunks_embedding_hnsw "
                "ON document_chunks USING hnsw (embedding vector_cosine_ops)"
            ))
    else:
        SQLModel.metadata.create_all(engine)


def get_session():
    """获取数据库会话"""
    with Session(engine) as session:
        yield session
