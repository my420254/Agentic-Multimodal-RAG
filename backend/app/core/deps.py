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
