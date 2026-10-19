"""Admin Agent Trace 查询接口测试（临时 SQLite）。"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine

from app.core.database import get_session
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models import AgentTrace, User


@pytest.fixture(scope="module")
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    with Session(eng) as s:
        admin = User(student_id=f"admin_{uuid.uuid4().hex[:6]}", password_hash=hash_password("Admin@123456"), role="admin")
        student = User(student_id=f"student_{uuid.uuid4().hex[:6]}", password_hash=hash_password("Test@123456"), role="student")
        s.add_all([admin, student])
        s.commit()
        s.refresh(admin)
        s.refresh(student)
        trace_id = f"tr_{uuid.uuid4().hex}"
        s.add(AgentTrace(
            trace_id=trace_id,
            user_id=student.id,
            mode="agent",
            query="Redis 故障转移怎么排查",
            answer_preview="先看 cluster info",
            citations_json='[{"fileId":"doc_1","fileName":"redis.md","chunk_id":"c1","score":0.9}]',
            steps_json='[{"step":"action","content":"调用检索"}]',
            tool_calls_json='[{"step":"action","content":"调用检索"}]',
            ttft_ms=120.5,
            total_ms=2400.0,
        ))
        s.commit()
        yield eng, admin, student, trace_id
    eng.dispose()


@pytest.fixture(scope="module")
def client(engine):
    def override():
        with Session(engine[0]) as s:
            yield s

    app.dependency_overrides[get_session] = override
    c = TestClient(app)
    yield c
    c.close()
    app.dependency_overrides.pop(get_session, None)


def _h(user):
    return {"Authorization": f"Bearer {create_access_token(user.id, user.role)}"}


def test_trace_list_and_detail(client, engine):
    _, admin, student, trace_id = engine
    resp = client.get("/api/v1/admin/traces", headers=_h(admin))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] >= 1
    assert any(item["trace_id"] == trace_id for item in body["items"])

    resp = client.get(f"/api/v1/admin/traces/{trace_id}", headers=_h(admin))
    assert resp.status_code == 200, resp.text
    detail = resp.json()
    assert detail["query"] == "Redis 故障转移怎么排查"
    assert detail["citations"][0]["fileId"] == "doc_1"
    assert detail["tool_calls"][0]["step"] == "action"

    assert client.get("/api/v1/admin/traces", headers=_h(student)).status_code == 403
