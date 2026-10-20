"""API Key scope 与 CORS/异常响应的安全回归测试（不联网）。"""

import asyncio
from types import SimpleNamespace

from app.core.deps import _scope_for_request, has_scope
from app.main import global_exception_handler


def _request(auth_method: str | None, scopes=None, *, method="GET", path="/api/v1/x"):
    return SimpleNamespace(
        method=method,
        url=SimpleNamespace(path=path),
        state=SimpleNamespace(
            auth_method=auth_method,
            api_key_scopes=set(scopes or []),
        ),
    )


def test_jwt_users_bypass_api_key_scope_checks():
    assert has_scope(_request("jwt"), "kb:write") is True


def test_api_key_requires_exact_scope():
    assert has_scope(_request("api_key", ["chat:read"]), "chat:read") is True
    assert has_scope(_request("api_key", ["chat:read"]), "kb:read") is False


def test_write_implies_read_and_admin_is_super_scope():
    assert has_scope(_request("api_key", ["kb:write"]), "kb:read") is True
    assert has_scope(_request("api_key", ["admin:*"]), "career:write") is True


def test_route_to_scope_mapping():
    assert _scope_for_request(_request(None, method="GET", path="/api/v1/knowledge-bases")) == "kb:read"
    assert _scope_for_request(_request(None, method="POST", path="/api/v1/knowledge-bases")) == "kb:write"
    assert _scope_for_request(_request(None, method="GET", path="/api/v1/career/prompts")) == "career:read"
    assert _scope_for_request(_request(None, method="POST", path="/api/v1/career/match")) == "career:write"
    assert _scope_for_request(_request(None, method="GET", path="/api/v1/benchmark/records")) == "eval:run"
    assert _scope_for_request(_request(None, method="POST", path="/api/v1/chat/completions")) == "chat:read"
    assert _scope_for_request(_request(None, method="POST", path="/api/v1/knowledge-bases/kb1/recall")) == "kb:read"
    assert _scope_for_request(_request(None, method="DELETE", path="/api/v1/recall/retrieval-logs/log1")) == "kb:write"
    assert _scope_for_request(_request(None, method="PUT", path="/api/v1/settings")) == "admin:*"
    assert _scope_for_request(_request(None, method="POST", path="/api/v1/auth/login")) is None


def test_exception_handler_does_not_leak_internal_message():
    request = SimpleNamespace(
        method="GET",
        url=SimpleNamespace(path="/api/v1/boom"),
        state=SimpleNamespace(request_id="req_test"),
    )
    response = asyncio.run(global_exception_handler(request, RuntimeError("secret-db-password")))
    body = response.body.decode("utf-8")
    assert "secret-db-password" not in body
    assert "req_test" in body
    assert response.headers["X-Request-Id"] == "req_test"
