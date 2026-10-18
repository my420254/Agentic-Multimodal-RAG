"""
账号与 JWT 接口（W1 · C1）。

- POST /api/v1/auth/login   学号 + 密码换 access/refresh
- POST /api/v1/auth/refresh 用 refresh 换新的一对 token
- GET  /api/v1/auth/me      用 access 读取当前账号
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.core.database import get_session
from app.core.deps import get_current_user
from app.core.security import (
    InvalidTokenError,
    TokenExpiredError,
    create_token_pair,
    decode_token,
    verify_password,
)
from app.models import User

router = APIRouter(prefix="/auth", tags=["Auth"])


class LoginRequest(BaseModel):
    student_id: str = Field(min_length=1, max_length=64, description="学号")
    password: str = Field(min_length=1, max_length=256, description="密码")


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1, description="登录时下发的 refresh token")


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="access token 有效期（秒）")


class UserOut(BaseModel):
    id: str
    student_id: str
    email: Optional[str] = None
    role: str
    status: str
    created_at: datetime


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _active_user(session: Session, user_id: str) -> Optional[User]:
    user = session.get(User, user_id)
    if user is None or user.deleted_at is not None or user.status != "active":
        return None
    return user


@router.post("/login", response_model=TokenPair)
def login(req: LoginRequest, session: Session = Depends(get_session)) -> TokenPair:
    """学号 + 密码登录。失败一律 401，不区分“学号不存在”与“密码错误”。"""
    student_id = req.student_id.strip()
    user = session.exec(select(User).where(User.student_id == student_id)).first()

    if user is None or not verify_password(req.password, user.password_hash):
        raise _unauthorized("学号或密码错误")

    if user.deleted_at is not None or user.status != "active":
        raise _unauthorized("账号不可用")

    pair = create_token_pair(str(user.id), user.role)
    return TokenPair(**pair)


@router.post("/refresh", response_model=TokenPair)
def refresh(req: RefreshRequest, session: Session = Depends(get_session)) -> TokenPair:
    """用 refresh token 换一对新 token；过期/伪造/拿 access 来换均 401。"""
    try:
        payload = decode_token(req.refresh_token, expected_type="refresh")
    except TokenExpiredError:
        raise _unauthorized("refresh token 已过期")
    except InvalidTokenError:
        raise _unauthorized("refresh token 无效")

    user_id = payload.get("sub")
    if not isinstance(user_id, str) or not user_id:
        raise _unauthorized("refresh token 缺少 sub")

    user = _active_user(session, user_id)
    if user is None:
        raise _unauthorized("refresh token 对应的账号不可用")

    pair = create_token_pair(str(user.id), user.role)
    return TokenPair(**pair)


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)) -> UserOut:
    """返回当前 token 对应的账号；无 token / 过期 / 伪造一律 401。"""
    return UserOut(
        id=str(current_user.id),
        student_id=current_user.student_id,
        email=current_user.email,
        role=current_user.role,
        status=current_user.status,
        created_at=current_user.created_at,
    )
