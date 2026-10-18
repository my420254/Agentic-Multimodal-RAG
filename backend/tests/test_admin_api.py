"""Admin 控制面接口测试（临时 SQLite，不连 agent_db）。"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine

from app.core.database import get_session
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models import User


@pytest.fixture(scope="module")
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture(scope="module")
def data(engine):
    with Session(engine) as s:
        admin = User(student_id=f"admin_{uuid.uuid4().hex[:6]}", password_hash=hash_password("Admin@123456"), role="admin")
        student = User(student_id=f"student_{uuid.uuid4().hex[:6]}", password_hash=hash_password("Test@123456"), role="student")
        s.add_all([admin, student])
        s.commit()
        s.refresh(admin)
        s.refresh(student)
        return {
            "admin": admin,
            "student": student,
            "admin_token": create_access_token(admin.id, "admin"),
            "student_token": create_access_token(student.id, "student"),
        }


@pytest.fixture(scope="module")
def client(engine):
    def override():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = override
    c = TestClient(app)
    yield c
    c.close()
    app.dependency_overrides.pop(get_session, None)


def _h(token):
    return {"Authorization": f"Bearer {token}"}


def test_student_forbidden_admin_forbidden(client, data):
    assert client.get("/api/v1/admin/overview", headers=_h(data["student_token"])).status_code == 403
    assert client.get("/api/v1/admin/overview", headers=_h(data["admin_token"])).status_code == 200


def test_admin_create_user(client, data):
    sid = f"created_{uuid.uuid4().hex[:6]}"
    resp = client.post(
        "/api/v1/admin/users",
        headers=_h(data["admin_token"]),
        json={"student_id": sid, "password": "New@123456", "role": "student"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["student_id"] == sid
    login = client.post("/api/v1/auth/login", json={"student_id": sid, "password": "New@123456"})
    assert login.status_code == 200


def test_admin_users_and_password_reset(client, data):
    resp = client.get("/api/v1/admin/users", headers=_h(data["admin_token"]))
    assert resp.status_code == 200
    assert resp.json()["total"] >= 2

    target = data["student"].id
    resp = client.patch(
        f"/api/v1/admin/users/{target}",
        headers=_h(data["admin_token"]),
        json={"status": "disabled"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "disabled"
    assert client.post(
        "/api/v1/auth/login",
        json={"student_id": data["student"].student_id, "password": "Test@123456"},
    ).status_code == 401

    resp = client.patch(
        f"/api/v1/admin/users/{target}",
        headers=_h(data["admin_token"]),
        json={"status": "active"},
    )
    assert resp.status_code == 200

    resp = client.post(
        f"/api/v1/admin/users/{target}/reset-password",
        headers=_h(data["admin_token"]),
    )
    assert resp.status_code == 200
    temp = resp.json()["temp_password"]
    assert client.post(
        "/api/v1/auth/login",
        json={"student_id": data["student"].student_id, "password": temp},
    ).status_code == 200


def test_admin_api_key_auth_and_revoke(client, data):
    resp = client.post(
        "/api/v1/admin/api-keys",
        headers=_h(data["admin_token"]),
        json={"name": "test-key", "scopes": ["chat:read"], "expires_days": 1},
    )
    assert resp.status_code == 200
    body = resp.json()
    raw = body["key"]
    key_id = body["api_key"]["id"]
    assert raw.startswith("sk_live_")

    me = client.get("/api/v1/auth/me", headers=_h(raw))
    assert me.status_code == 200
    assert me.json()["id"] == data["admin"].id

    # chat:read key 不能进 admin（角色是 admin，但 scope 不够）
    assert client.get("/api/v1/admin/overview", headers=_h(raw)).status_code == 403

    assert client.delete(f"/api/v1/admin/api-keys/{key_id}", headers=_h(data["admin_token"])).status_code == 200
    assert client.get("/api/v1/auth/me", headers=_h(raw)).status_code == 401


def test_change_password(client, data):
    sid = f"pwd_{uuid.uuid4().hex[:6]}"
    resp = client.post(
        "/api/v1/admin/users",
        headers=_h(data["admin_token"]),
        json={"student_id": sid, "password": "Old@123456", "role": "student"},
    )
    assert resp.status_code == 200
    login = client.post("/api/v1/auth/login", json={"student_id": sid, "password": "Old@123456"})
    assert login.status_code == 200
    token = login.json()["access_token"]

    resp = client.post(
        "/api/v1/auth/change-password",
        headers=_h(token),
        json={"old_password": "Old@123456", "new_password": "New@654321"},
    )
    assert resp.status_code == 200
    assert client.post("/api/v1/auth/login", json={"student_id": sid, "password": "Old@123456"}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"student_id": sid, "password": "New@654321"}).status_code == 200


def test_metrics_and_observability_endpoints(client, data):
    r = client.get("/metrics")
    assert r.status_code == 200
    assert "rag_http_requests_total" in r.text

    r = client.get("/api/v1/admin/observability/summary", headers=_h(data["admin_token"]))
    assert r.status_code == 200
    assert "total_requests" in r.json()

    r = client.get("/api/v1/admin/request-logs", headers=_h(data["admin_token"]))
    assert r.status_code == 200
    assert "items" in r.json()


def test_admin_prompt_versioning_and_audit(client, data):
    key = "mock_interviewer"
    resp = client.post(
        "/api/v1/admin/prompts",
        headers=_h(data["admin_token"]),
        json={"key": key, "content": "TEST_GLOBAL_PROMPT_V1 {retrieved_context}"},
    )
    assert resp.status_code == 200
    version = resp.json()["version"]
    assert version >= 1

    resp = client.post(
        f"/api/v1/admin/prompts/{key}/publish",
        headers=_h(data["admin_token"]),
        json={"version": version},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "active"

    resp = client.get(f"/api/v1/admin/prompts/{key}/versions", headers=_h(data["admin_token"]))
    assert resp.status_code == 200
    assert any(v["version"] == version and v["status"] == "active" for v in resp.json()["items"])

    resp = client.get("/api/v1/admin/audit-logs", headers=_h(data["admin_token"]))
    assert resp.status_code == 200
    actions = [x["action"] for x in resp.json()["items"]]
    assert "prompt.publish" in actions
    assert "api_key.revoke" in actions
