"""
FastAPI 鉴权依赖。

W1 的唯一用户身份来源：Authorization: Bearer <access_token>。
任何 Body / Query 里的 user_id 都不参与身份判定（C2 起由业务路由强制使用本依赖）。
"""

import hashlib
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import Session, select

from app.core.database import get_session
from app.core.security import InvalidTokenError, TokenExpiredError, decode_token
from app.models import ApiKey, User

# auto_error=False：缺少/非 Bearer 头时由我们自己返回统一的 401 JSON，
# 而不是 FastAPI 默认的 403。
bearer_scheme = HTTPBearer(auto_error=False)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _api_key_user(token: str, session: Session, request: Optional[Request] = None) -> Optional[User]:
    """Bearer sk_... 的外部 API Key 认证；只存 hash，不存明文。"""
    if not token.startswith("sk_"):
        return None
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    key = session.exec(select(ApiKey).where(ApiKey.key_hash == digest)).first()
    if key is None or key.revoked_at is not None:
        return None
    now = datetime.now(timezone.utc)
    if key.expires_at is not None:
        expires = key.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires <= now:
            return None
    user = session.get(User, key.owner_id)
    if user is None or user.deleted_at is not None or user.status != "active":
        return None
    key.last_used_at = now
    session.add(key)
    session.commit()
    if request is not None:
        request.state.auth_method = "api_key"
        request.state.api_key_scopes = {s.strip() for s in (key.scopes or "").split(",") if s.strip()}
    return user


def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    session: Session = Depends(get_session),
) -> User:
    """解析 JWT access token 或 sk_ API Key；任何失败一律 401。"""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized("缺少 Bearer access token")

    try:
        payload = decode_token(credentials.credentials, expected_type="access")
    except (TokenExpiredError, InvalidTokenError):
        api_user = _api_key_user(credentials.credentials, session, request)
        if api_user is not None:
            request.state.auth_method = "api_key"
            request.state.user_id = api_user.id
            return api_user
        raise _unauthorized("access token 无效或已过期")

    user_id = payload.get("sub")
    if not isinstance(user_id, str) or not user_id:
        raise _unauthorized("access token 缺少 sub")

    request.state.auth_method = "jwt"
    request.state.user_id = user_id
    user = session.get(User, user_id)
    if user is None or user.deleted_at is not None or user.status != "active":
        # 不区分“用户不存在 / 已注销 / 被禁用”，避免账号枚举。
        raise _unauthorized("账号不存在或不可用")

    return user


def get_current_admin(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> User:
    """仅 admin 可访问；API Key 还必须带 admin:* scope。"""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限",
        )
    if getattr(request.state, "auth_method", None) == "api_key":
        scopes = getattr(request.state, "api_key_scopes", set())
        if "admin:*" not in scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="该 API Key 缺少 admin:* scope",
            )
    return current_user


SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def has_scope(request: Request, required: str) -> bool:
    """JWT 用户走角色/owner 校验；API Key 走 scope 校验。

    约定：
    - ``admin:*`` 拥有全部权限；
    - ``<prefix>:write`` 隐含 ``<prefix>:read``；
    - ``<prefix>:*`` 拥有该前缀全部权限。
    """
    if getattr(request.state, "auth_method", None) != "api_key":
        return True

    scopes = set(getattr(request.state, "api_key_scopes", set()))
    if "admin:*" in scopes or required in scopes:
        return True

    prefix, _, action = required.partition(":")
    if action == "read" and f"{prefix}:write" in scopes:
        return True
    return f"{prefix}:*" in scopes


def _scope_for_request(request: Request) -> Optional[str]:
    """按路由前缀和方法映射所需 scope；未覆盖的路径返回 None。"""
    path = request.url.path
    method = request.method.upper()

    if path.startswith("/api/v1/auth/"):
        return None
    if path.startswith("/api/v1/benchmark/"):
        return "eval:run"
    if path.startswith("/api/v1/chat/"):
        return "chat:read"
    if path.startswith("/api/v1/career/"):
        return "career:read" if method in SAFE_METHODS else "career:write"
    # recall 的 POST 是检索/搜索，不是写操作；只有 DELETE 检索日志算写。
    if path.endswith("/recall") or path.startswith("/api/v1/recall/"):
        return "kb:write" if method == "DELETE" else "kb:read"
    if path.startswith((
        "/api/v1/knowledge-bases",
        "/api/v1/files",
        "/api/v1/chunks",
    )):
        return "kb:read" if method in SAFE_METHODS else "kb:write"
    if path.startswith("/api/v1/settings"):
        # 读配置/模型列表用 kb:read；改配置/模型必须是 admin:*
        return "kb:read" if method in SAFE_METHODS else "admin:*"
    if path.startswith("/api/v1/models"):
        return "kb:read"
    return None


def require_route_scope(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> User:
    """保护性路由的统一 scope 检查；JWT 用户直接放行。"""
    required = _scope_for_request(request)
    if required and not has_scope(request, required):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"该 API Key 缺少 {required} scope",
        )
    return current_user
