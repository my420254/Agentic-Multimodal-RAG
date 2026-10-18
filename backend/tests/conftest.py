import os
import sys
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

from app.main import app
from app.core.database import engine, get_session
from app.models.models import KnowledgeBase


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


@pytest.fixture(scope="session")
def enterprise_kb_id():
    """返回生产级企业知识库 ID"""
    return "kb_sre_enterprise"
