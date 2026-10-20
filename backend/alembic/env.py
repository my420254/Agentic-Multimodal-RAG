from logging.config import fileConfig
import sys
from pathlib import Path

from sqlmodel import SQLModel

from alembic import context

# 让 alembic 在 backend/ 下直接运行时能 import app.*
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import get_settings  # noqa: E402
from app.core.database import engine  # noqa: E402
import app.models  # noqa: F401,E402  确保所有表注册到 SQLModel.metadata

config = context.config
settings = get_settings()
# 使用应用同一份 DATABASE_URL；% 需要转义以适配 configparser
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL.replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata

# HNSW 索引由 migration 里的 op.execute / init_db 手动维护，不在 SQLModel metadata 中；
# 让 alembic check 忽略它，避免误判为“待删除索引”。
HNSW_INDEX = "ix_document_chunks_embedding_hnsw"


def include_object(object, name, type_, reflected, compare_to):
    if type_ == "index" and name == HNSW_INDEX:
        return False
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=settings.DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # 复用应用 engine，避免 alembic.ini 里再维护一份连接串
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
