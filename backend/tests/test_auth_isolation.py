"""
W1 · C3 跨用户越权与鉴权矩阵（30 条）。

隔离方式（已与需求方确认）：
- 认证/租户测试使用内存 SQLite + FastAPI dependency_overrides，不连接 agent_db；
- 不触发真实 LLM：interview_chat 的 404 分支在 LLM 之前返回；
- 需要 200 的 body 注入用例使用 fake chat 返回；
- 会话数据写入真实 Redis（唯一 UUID key，测试结束清理）。

矩阵（共 30 条）：
1. 无 token / 空 token / 伪造签名 / 过期 / refresh 当 access 等  8 条 → 401
2. 过期 refresh 换 access                                        2 条 → 401
3. A 的 token 访问 B 的 4 个会话 × 3 个操作（GET/DELETE/chat）    12 条 → 404
4. body/query 塞 user_id=B 被忽略                                4 条 → 200 且数据归 A
5. 删除 B 的资源                                                 2 条 → 404 且 B 数据仍在
6. token 中 sub 被篡改为 B                                       2 条 → 401

说明：HANDOFF 原矩阵里的 material/report/profile 在 W1 尚无独立表/接口
（本轮明确不建 materials/sessions/reports 表），按已确认方案，12 条资源越权
落到当前唯一的资源——session（4 个 B 会话 × GET/DELETE/interview chat）。
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine

from app.core.config import get_settings
from app.core.database import get_session
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
)
from app.main import app
from app.models import User
from app.services.memory_service import memory_service
from app.services.mock_interview import InterviewTurnResponse
from app.services.prompt_service import prompt_workshop_service

settings = get_settings()

# ==================== 静态红线：默认用户必须清零 ====================

_APP_DIR = Path(__file__).resolve().parents[1] / "app"
for _source_path in _APP_DIR.rglob("*.py"):
    _source_text = _source_path.read_text(encoding="utf-8")
    assert "default_user" not in _source_text, f"{_source_path} 仍包含 default_user"
    assert "default_student" not in _source_text, f"{_source_path} 仍包含 default_student"


# ==================== base64url 工具（篡改 payload 用） ====================

def _b64url_decode(segment: str) -> bytes:
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _tamper_sub(token: str, new_sub: str) -> str:
    """只改 payload 的 sub，保留原签名；服务端必须因签名不匹配返回 401。"""
    header, payload, signature = token.split(".")
    data = json.loads(_b64url_decode(payload))
    data["sub"] = new_sub
    tampered_payload = _b64url_encode(
        json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    )
    return f"{header}.{tampered_payload}.{signature}"


# ==================== fixtures ====================

@pytest.fixture(scope="module")
def test_engine():
    """独立内存 SQLite；TestClient 多线程共享同一连接。"""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def client(test_engine):
    """不进入 lifespan，避免 init_db() 落到 agent_db。"""
    def override_get_session():
        with Session(test_engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    test_client = TestClient(app)
    yield test_client
    test_client.close()
    app.dependency_overrides.pop(get_session, None)


@pytest.fixture(scope="module")
def users(test_engine):
    now = datetime.now(timezone.utc)
    with Session(test_engine, expire_on_commit=False) as session:
        user_a = User(
            student_id="w1_user_a",
            email="w1_user_a@test.local",
            password_hash=hash_password("Test@123456"),
            role="student",
            status="active",
        )
        user_b = User(
            student_id="w1_user_b",
            email="w1_user_b@test.local",
            password_hash=hash_password("Test@123456"),
            role="student",
            status="active",
        )
        disabled = User(
            student_id="w1_user_disabled",
            email="w1_user_disabled@test.local",
            password_hash=hash_password("Test@123456"),
            role="student",
            status="disabled",
        )
        deleted = User(
            student_id="w1_user_deleted",
            email="w1_user_deleted@test.local",
            password_hash=hash_password("Test@123456"),
            role="student",
            status="active",
            deleted_at=now,
        )
        session.add_all([user_a, user_b, disabled, deleted])
        session.commit()
        for user in (user_a, user_b, disabled, deleted):
            session.refresh(user)

        result = {
            "a": user_a,
            "b": user_b,
            "disabled": disabled,
            "deleted": deleted,
        }
    return result


@pytest.fixture(scope="module")
def tokens(users):
    return {
        "a": create_access_token(str(users["a"].id), users["a"].role),
        "b": create_access_token(str(users["b"].id), users["b"].role),
        "refresh_a": create_refresh_token(str(users["a"].id), users["a"].role),
        "disabled": create_access_token(str(users["disabled"].id), "student"),
        "deleted": create_access_token(str(users["deleted"].id), "student"),
    }


@pytest.fixture(scope="module")
def auth_a(tokens):
    return {"Authorization": f"Bearer {tokens['a']}"}


@pytest.fixture(scope="module")
def auth_b(tokens):
    return {"Authorization": f"Bearer {tokens['b']}"}


@pytest.fixture(scope="module")
def b_sessions(users):
    """B 的 4 个资源会话 + 2 个删除专用会话。"""
    b_id = str(users["b"].id)
    sids = [f"w1_b_session_{uuid.uuid4().hex}" for _ in range(4)]
    delete_sids = [f"w1_b_delete_{uuid.uuid4().hex}" for _ in range(2)]

    for sid in sids + delete_sids:
        assert memory_service.claim_session(b_id, sid) is True
        memory_service.add_message(b_id, sid, "user", f"B_SECRET::{sid}")

    yield {"sids": sids, "delete_sids": delete_sids}

    for sid in sids + delete_sids:
        memory_service.clear_session(b_id, sid)


@pytest.fixture(scope="module")
def invalid_access_headers(users, tokens):
    now = datetime.now(timezone.utc)
    a_id = str(users["a"].id)
    wrong_secret = "wrong-access-secret-" + "x" * 40

    def _encode(sub: str, token_type: str, secret: str, exp_delta: timedelta) -> str:
        return jwt.encode(
            {
                "sub": sub,
                "role": "student",
                "type": token_type,
                "iat": now - timedelta(minutes=1),
                "exp": now + exp_delta,
            },
            secret,
            algorithm=settings.JWT_ALG,
        )

    return {
        "no_header": {},
        "empty_bearer": {"Authorization": "Bearer "},
        "malformed": {"Authorization": "Bearer not-a-jwt"},
        "forged_signature": {
            "Authorization": f"Bearer {_encode(a_id, 'access', wrong_secret, timedelta(minutes=15))}"
        },
        "expired_access": {
            "Authorization": f"Bearer {_encode(a_id, 'access', settings.JWT_SECRET, timedelta(hours=-1))}"
        },
        "refresh_as_access": {"Authorization": f"Bearer {tokens['refresh_a']}"},
        "disabled_user": {"Authorization": f"Bearer {tokens['disabled']}"},
        "deleted_user": {"Authorization": f"Bearer {tokens['deleted']}"},
    }


@pytest.fixture(scope="module")
def invalid_refresh_tokens(users):
    now = datetime.now(timezone.utc)
    a_id = str(users["a"].id)
    expired_payload = {
        "sub": a_id,
        "role": "student",
        "type": "refresh",
        "iat": now - timedelta(days=8),
        "exp": now - timedelta(days=1),
    }
    return {
        "expired_refresh": jwt.encode(
            expired_payload,
            settings.JWT_SECRET,
            algorithm=settings.JWT_ALG,
        ),
        "expired_refresh_forged": jwt.encode(
            expired_payload,
            "wrong-refresh-secret-" + "y" * 40,
            algorithm=settings.JWT_ALG,
        ),
    }


@pytest.fixture(autouse=True)
def isolate_external_calls(monkeypatch):
    """越权用例不得触发真实 LLM，也不受限流状态影响。"""
    monkeypatch.setattr(
        "app.api.career.global_rate_limiter.is_allowed",
        lambda *args, **kwargs: True,
    )

    async def _llm_must_not_be_called(*args, **kwargs):
        raise AssertionError("认证/越权测试不应调用真实 LLM")

    monkeypatch.setattr(
        "app.api.career.mock_interview_service.chat",
        _llm_must_not_be_called,
    )
    yield


@pytest.fixture(scope="module", autouse=True)
def cleanup_user_scoped_state(users):
    """即使某个用例失败，也不把测试数据留在 Redis 里。"""
    yield

    uids = [
        str(users[key].id)
        for key in ("a", "b", "disabled", "deleted")
    ]
    redis_client = memory_service.client
    if redis_client is not None:
        try:
            for uid in uids:
                for key in redis_client.scan_iter(f"u:{uid}:*"):
                    redis_client.delete(key)
            for key in redis_client.scan_iter("session_owner:*"):
                if redis_client.get(key) in uids:
                    redis_client.delete(key)
        except Exception:
            pass

    # Redis 不可用时的内存降级清理
    try:
        with memory_service._fallback_lock:
            for key in list(memory_service._fallback_memory):
                if any(key.startswith(f"u:{uid}:") for uid in uids):
                    memory_service._fallback_memory.pop(key, None)
                elif key.startswith("session_owner:") and memory_service._fallback_memory[key] in uids:
                    memory_service._fallback_memory.pop(key, None)
    except Exception:
        pass

    for uid in uids:
        for template_key in prompt_workshop_service.DEFAULT_TEMPLATES:
            try:
                prompt_workshop_service.reset_template(uid, template_key)
            except Exception:
                pass


# ==================== 1) 8 条访问 token 401 ====================

_ACCESS_CASES = [
    "no_header",
    "empty_bearer",
    "malformed",
    "forged_signature",
    "expired_access",
    "refresh_as_access",
    "disabled_user",
    "deleted_user",
]


@pytest.mark.parametrize("case", _ACCESS_CASES)
def test_invalid_access_token_returns_401(client, invalid_access_headers, case):
    response = client.get(
        "/api/v1/career/prompts",
        headers=invalid_access_headers[case],
    )
    assert response.status_code == 401, f"{case}: {response.status_code} {response.text}"


# ==================== 2) 2 条 refresh 401 ====================

_REFRESH_CASES = ["expired_refresh", "expired_refresh_forged"]


@pytest.mark.parametrize("case", _REFRESH_CASES)
def test_invalid_refresh_token_returns_401(client, invalid_refresh_tokens, case):
    response = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": invalid_refresh_tokens[case]},
    )
    assert response.status_code == 401, f"{case}: {response.status_code} {response.text}"


# ==================== 3) 12 条跨用户会话 404 ====================

_SESSION_OPS = ["get_memory", "delete", "interview_chat"]


@pytest.mark.parametrize("op", _SESSION_OPS)
@pytest.mark.parametrize("sid_index", range(4))
def test_cross_user_session_access_returns_404(
    client,
    auth_a,
    users,
    b_sessions,
    op,
    sid_index,
):
    sid = b_sessions["sids"][sid_index]

    if op == "get_memory":
        response = client.get(
            f"/api/v1/career/interview/session/{sid}/memory",
            headers=auth_a,
        )
    elif op == "delete":
        response = client.delete(
            f"/api/v1/career/interview/session/{sid}",
            headers=auth_a,
        )
    else:
        response = client.post(
            "/api/v1/career/interview/chat",
            headers=auth_a,
            json={
                "session_id": sid,
                "messages": [{"role": "user", "content": "越权尝试"}],
            },
        )

    assert response.status_code == 404, f"{op}/{sid}: {response.status_code} {response.text}"

    # B 的归属与数据必须原样保留
    b_id = str(users["b"].id)
    assert memory_service.owns_session(b_id, sid) is True
    assert memory_service.get_all_messages_count(b_id, sid) >= 1


# ==================== 4) 4 条 body/query user_id 注入被忽略 ====================

def test_body_user_id_ignored_on_interview_chat(client, auth_a, users, monkeypatch):
    a_id = str(users["a"].id)
    b_id = str(users["b"].id)
    sid = f"w1_a_chat_{uuid.uuid4().hex}"

    async def fake_chat(**kwargs):
        return InterviewTurnResponse(reply_text="FAKE_ANSWER")

    monkeypatch.setattr("app.api.career.mock_interview_service.chat", fake_chat)

    try:
        response = client.post(
            "/api/v1/career/interview/chat",
            headers=auth_a,
            json={
                "session_id": sid,
                "user_id": b_id,  # 必须被忽略
                "messages": [{"role": "user", "content": "我是 A"}],
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["reply_text"] == "FAKE_ANSWER"

        assert memory_service.owns_session(a_id, sid) is True
        assert memory_service.owns_session(b_id, sid) is False
        assert memory_service.get_all_messages_count(a_id, sid) == 2
        assert memory_service.get_all_messages_count(b_id, sid) == 0
    finally:
        memory_service.clear_session(a_id, sid)


def test_body_user_id_ignored_on_prompt_update(client, auth_a, auth_b, users):
    a_id = str(users["a"].id)
    b_id = str(users["b"].id)
    try:
        response = client.post(
            "/api/v1/career/prompts",
            headers=auth_a,
            json={
                "key": "mock_interviewer",
                "system_prompt": "A_ONLY_PROMPT",
                "user_id": b_id,  # 必须被忽略
            },
        )
        assert response.status_code == 200, response.text

        data_a = client.get("/api/v1/career/prompts", headers=auth_a).json()
        data_b = client.get("/api/v1/career/prompts", headers=auth_b).json()

        assert data_a["mock_interviewer"]["system_prompt"] == "A_ONLY_PROMPT"
        assert data_a["mock_interviewer"]["is_custom"] is True
        assert data_b["mock_interviewer"]["is_custom"] is False
        assert "A_ONLY_PROMPT" not in data_b["mock_interviewer"]["system_prompt"]
    finally:
        prompt_workshop_service.reset_template(a_id, "mock_interviewer")
        prompt_workshop_service.reset_template(b_id, "mock_interviewer")


def test_query_user_id_ignored_on_prompt_read(client, auth_a, users):
    a_id = str(users["a"].id)
    b_id = str(users["b"].id)
    try:
        prompt_workshop_service.update_template(a_id, "mock_interviewer", "A_QUERY_ONLY")
        prompt_workshop_service.update_template(b_id, "mock_interviewer", "B_QUERY_ONLY")

        response = client.get(
            f"/api/v1/career/prompts?user_id={b_id}",
            headers=auth_a,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["mock_interviewer"]["system_prompt"] == "A_QUERY_ONLY"
        assert "B_QUERY_ONLY" not in data["mock_interviewer"]["system_prompt"]
    finally:
        prompt_workshop_service.reset_template(a_id, "mock_interviewer")
        prompt_workshop_service.reset_template(b_id, "mock_interviewer")


def test_body_user_id_ignored_on_prompt_reset(client, auth_a, users):
    a_id = str(users["a"].id)
    b_id = str(users["b"].id)
    try:
        prompt_workshop_service.update_template(a_id, "mock_interviewer", "A_RESET")
        prompt_workshop_service.update_template(b_id, "mock_interviewer", "B_RESET")

        response = client.post(
            "/api/v1/career/prompts/reset",
            headers=auth_a,
            json={"key": "mock_interviewer", "user_id": b_id},  # 必须被忽略
        )
        assert response.status_code == 200, response.text

        template_a = prompt_workshop_service.get_template(a_id, "mock_interviewer")
        template_b = prompt_workshop_service.get_template(b_id, "mock_interviewer")
        assert template_a.is_custom is False
        assert "A_RESET" not in template_a.system_prompt
        assert template_b.is_custom is True
        assert template_b.system_prompt == "B_RESET"
    finally:
        prompt_workshop_service.reset_template(a_id, "mock_interviewer")
        prompt_workshop_service.reset_template(b_id, "mock_interviewer")


# ==================== 5) 2 条删除 B 资源 404 + 数据保留 ====================

@pytest.mark.parametrize("sid_index", range(2))
def test_delete_other_user_session_returns_404_and_keeps_data(
    client,
    auth_a,
    users,
    b_sessions,
    sid_index,
):
    sid = b_sessions["delete_sids"][sid_index]
    response = client.delete(
        f"/api/v1/career/interview/session/{sid}",
        headers=auth_a,
    )
    assert response.status_code == 404, f"{sid}: {response.status_code} {response.text}"

    b_id = str(users["b"].id)
    assert memory_service.owns_session(b_id, sid) is True
    assert memory_service.get_all_messages_count(b_id, sid) >= 1


# ==================== 6) 2 条 sub 篡改 401 ====================

_TAMPER_CASES = ["payload_tampered", "payload_tampered_wrong_secret"]


@pytest.mark.parametrize("case", _TAMPER_CASES)
def test_tampered_sub_returns_401(client, tokens, users, case):
    b_id = str(users["b"].id)
    access_token = tokens["a"]

    if case == "payload_tampered":
        token = _tamper_sub(access_token, b_id)
    else:
        _, payload, _ = access_token.split(".")
        data = json.loads(_b64url_decode(payload))
        data["sub"] = b_id
        token = jwt.encode(
            data,
            "wrong-sub-secret-" + "z" * 40,
            algorithm=settings.JWT_ALG,
        )

    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401, f"{case}: {response.status_code} {response.text}"
