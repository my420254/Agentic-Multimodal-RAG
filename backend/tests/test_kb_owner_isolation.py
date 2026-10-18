"""
知识库 owner 级隔离测试（临时 SQLite，不连 agent_db）。

覆盖：
- B 的列表看不到 A 的私有 KB，但能看到公共 KB；
- B 访问 A 的 KB 详情/文件/召回/聊天统一 404；
- A 自己可以访问。
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine

from app.core.database import get_session
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models import FileDocument, FileStatus, KnowledgeBase, User


@pytest.fixture(scope="module")
def engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture(scope="module")
def fixture_data(engine):
    with Session(engine, expire_on_commit=False) as session:
        user_a = User(
            student_id=f"kb_a_{uuid.uuid4().hex[:8]}",
            password_hash=hash_password("Test@123456"),
            role="student",
            status="active",
        )
        user_b = User(
            student_id=f"kb_b_{uuid.uuid4().hex[:8]}",
            password_hash=hash_password("Test@123456"),
            role="student",
            status="active",
        )
        session.add_all([user_a, user_b])
        session.commit()
        session.refresh(user_a)
        session.refresh(user_b)

        public_kb = KnowledgeBase(
            id=f"kb_public_{uuid.uuid4().hex[:8]}",
            name="公共知识库",
            owner_id=None,
            embedding_model="sys_embedding",
            vlm_model="default",
        )
        private_kb = KnowledgeBase(
            id=f"kb_private_{uuid.uuid4().hex[:8]}",
            name="A 的私有简历库",
            owner_id=str(user_a.id),
            embedding_model="sys_embedding",
            vlm_model="default",
        )
        session.add_all([public_kb, private_kb])
        session.commit()

        file_doc = FileDocument(
            id=f"file_{uuid.uuid4().hex[:8]}",
            kb_id=private_kb.id,
            name="a_resume.pdf",
            local_path="/tmp/a_resume.pdf",
            size=100,
            status=FileStatus.READY,
        )
        session.add(file_doc)
        session.commit()

        return {
            "user_a": user_a,
            "user_b": user_b,
            "public_kb": public_kb,
            "private_kb": private_kb,
            "file": file_doc,
            "token_a": create_access_token(str(user_a.id), "student"),
            "token_b": create_access_token(str(user_b.id), "student"),
        }


@pytest.fixture(scope="module")
def client(engine):
    def override_get_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    test_client = TestClient(app)
    yield test_client
    test_client.close()
    app.dependency_overrides.pop(get_session, None)


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_private_kb_hidden_from_other_user_list(client, fixture_data):
    response = client.get("/api/v1/knowledge-bases", headers=_headers(fixture_data["token_b"]))
    assert response.status_code == 200, response.text
    ids = [item["id"] for item in response.json()["data"]]
    assert fixture_data["private_kb"].id not in ids
    assert fixture_data["public_kb"].id in ids


def test_private_kb_all_endpoints_404_for_other_user(client, fixture_data):
    kb_id = fixture_data["private_kb"].id
    file_id = fixture_data["file"].id
    headers_b = _headers(fixture_data["token_b"])
    headers_a = _headers(fixture_data["token_a"])

    assert client.get(f"/api/v1/knowledge-bases/{kb_id}", headers=headers_a).status_code == 200
    assert client.get(f"/api/v1/knowledge-bases/{kb_id}", headers=headers_b).status_code == 404
    assert client.get(f"/api/v1/knowledge-bases/{kb_id}/files", headers=headers_b).status_code == 404
    assert client.get(f"/api/v1/files/{file_id}", headers=headers_b).status_code == 404
    assert client.get(f"/api/v1/files/{file_id}/chunks", headers=headers_b).status_code == 404

    assert client.post(
        f"/api/v1/knowledge-bases/{kb_id}/recall",
        headers=headers_b,
        json={"query": "测试", "top_k": 3},
    ).status_code == 404
    assert client.post(
        "/api/v1/chat/completions",
        headers=headers_b,
        json={
            "messages": [{"role": "user", "content": "测试"}],
            "kb_ids": [kb_id],
            "stream": True,
        },
    ).status_code == 404


def test_public_kb_visible_to_both(client, fixture_data):
    kb_id = fixture_data["public_kb"].id
    for token in (fixture_data["token_a"], fixture_data["token_b"]):
        assert client.get(f"/api/v1/knowledge-bases/{kb_id}", headers=_headers(token)).status_code == 200
