"""
FastAPI 鉴权依赖。

W1 的唯一用户身份来源：Authorization: Bearer <access_token>。
任何 Body / Query 里的 user_id 都不参与身份判定（C2 起由业务路由强制使用本依赖）。
"""

from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import Session

from app.core.database import get_session
from app.core.security import InvalidTokenError, TokenExpiredError, decode_token
from app.models import User

# auto_error=False：缺少/非 Bearer 头时由我们自己返回统一的 401 JSON，
# 而不是 FastAPI 默认的 403。
bearer_scheme = HTTPBearer(auto_error=False)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    session: Session = Depends(get_session),
) -> User:
    """解析 access token 并加载当前用户；任何失败一律 401。"""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized("缺少 Bearer access token")

    try:
        payload = decode_token(credentials.credentials, expected_type="access")
    except TokenExpiredError:
        raise _unauthorized("access token 已过期")
    except InvalidTokenError:
        raise _unauthorized("access token 无效")

    user_id = payload.get("sub")
    if not isinstance(user_id, str) or not user_id:
        raise _unauthorized("access token 缺少 sub")

    user = session.get(User, user_id)
    if user is None or user.deleted_at is not None or user.status != "active":
        # 不区分“用户不存在 / 已注销 / 被禁用”，避免账号枚举。
        raise _unauthorized("账号不存在或不可用")

    return user
