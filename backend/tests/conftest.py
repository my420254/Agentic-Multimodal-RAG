import os
import sys
import uuid
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

# 确保 backend 目录在 sys.path 中
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

# W1：JWT_SECRET 在应用配置中是必填项、无默认值。测试进程使用专用测试密钥，
# 避免为了跑测试在生产配置里写死密钥。必须在导入 app 之前设置。
os.environ.setdefault(
    "JWT_SECRET",
    "test-only-jwt-secret-do-not-use-in-production-0123456789",
)
# 记忆默认持久化到 agent_db；测试进程关闭，避免污染生产库。
# 持久化专项测试会显式传入临时 SQLite engine 并 persistence=True。
os.environ.setdefault("MEMORY_PERSISTENCE", "false")

from app.main import app
from app.core.database import engine, get_session
from app.core.security import create_access_token, hash_password
from app.models.models import KnowledgeBase, User


@pytest.fixture(scope="session")
def client():
    """提供统一的 FastAPI TestClient"""
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="function")
def db_session():
    """提供数据库会话 fixture"""
    with Session(engine) as session:
        yield session


@pytest.fixture(scope="function")
def auth_headers():
    """
    为需要登录的既有接口测试创建临时用户并签发 access token。

    仅用于非安全专项测试（chat / career 功能回归）；越权矩阵在
    tests/test_auth_isolation.py 中使用独立的临时 SQLite 库。
    """
    with Session(engine, expire_on_commit=False) as session:
        user = User(
            student_id=f"test_{uuid.uuid4().hex[:16]}",
            email=None,
            password_hash=hash_password("Test@123456"),
            role="student",
            status="active",
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        user_id = str(user.id)
        token = create_access_token(user_id, user.role)

    yield {"Authorization": f"Bearer {token}"}

    with Session(engine) as session:
        existing = session.get(User, user_id)
        if existing is not None:
            session.delete(existing)
            session.commit()


@pytest.fixture(scope="session")
def enterprise_kb_id():
    """返回生产级企业知识库 ID"""
    return "kb_sre_enterprise"
