"""
密码哈希与 JWT 签发/校验。

实现选择（与 HANDOFF 第 8 节一致）：
- 不用 passlib：本机未安装，且 passlib 与 bcrypt 5.x 存在已知不兼容；
  直接封装 bcrypt 的 hashpw/checkpw。
- 不用 python-jose：本机未安装，PyJWT 2.10.1 已安装且更轻；不引入新框架。
- JWT_SECRET 只能来自 Settings（环境变量 / 本地 .env）。缺失或过短时
  应用启动即失败，这里不做任何默认密钥兜底。
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import bcrypt
import jwt

from app.core.config import get_settings

settings = get_settings()

# bcrypt 只接受前 72 字节。超过时直接拒绝，避免静默截断导致“长密码前缀相同即可登录”。
BCRYPT_MAX_PASSWORD_BYTES = 72


class TokenError(Exception):
    """JWT 校验失败基类。"""


class TokenExpiredError(TokenError):
    """JWT 已过期。"""


class InvalidTokenError(TokenError):
    """JWT 签名、格式、类型或 claims 非法。"""


def _password_bytes(password: str) -> bytes:
    if not isinstance(password, str):
        raise ValueError("password must be a string")
    encoded = password.encode("utf-8")
    if len(encoded) > BCRYPT_MAX_PASSWORD_BYTES:
        raise ValueError(f"password exceeds {BCRYPT_MAX_PASSWORD_BYTES} bytes")
    return encoded


def hash_password(password: str) -> str:
    """生成 bcrypt 哈希（只用于写入 users.password_hash）。"""
    return bcrypt.hashpw(_password_bytes(password), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    """校验密码；任何非法输入/坏哈希都返回 False，绝不抛出到 API 层。"""
    try:
        return bcrypt.checkpw(_password_bytes(password), password_hash.encode("ascii"))
    except (ValueError, TypeError):
        return False


def _create_token(subject: str, role: str, token_type: str, expires_delta: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload: Dict[str, Any] = {
        # 只放最小 claims：sub=user_id、role、type、iat、exp。
        # 不放学号、邮箱、姓名等 PII。
        "sub": str(subject),
        "role": role,
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALG)


def create_access_token(subject: str, role: str = "student") -> str:
    return _create_token(
        subject,
        role,
        "access",
        timedelta(minutes=settings.ACCESS_TTL_MIN),
    )


def create_refresh_token(subject: str, role: str = "student") -> str:
    return _create_token(
        subject,
        role,
        "refresh",
        timedelta(days=settings.REFRESH_TTL_DAYS),
    )


def create_token_pair(subject: str, role: str = "student") -> Dict[str, Any]:
    """签发 access + refresh，并返回 API 需要的元信息。"""
    return {
        "access_token": create_access_token(subject, role),
        "refresh_token": create_refresh_token(subject, role),
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TTL_MIN * 60,
    }


def decode_token(token: str, expected_type: Optional[str] = None) -> Dict[str, Any]:
    """
    校验 JWT 并返回 claims。

    - 固定算法白名单，拒绝 alg=none / 算法混淆。
    - 强制要求 exp / iat / sub / type 存在。
    - expected_type 用于区分 access 与 refresh，防止拿 refresh 调业务接口。
    """
    if not isinstance(token, str) or not token.strip():
        raise InvalidTokenError("empty token")

    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALG],
            options={"require": ["exp", "iat", "sub", "type"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredError("token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise InvalidTokenError("invalid token") from exc

    if expected_type is not None and payload.get("type") != expected_type:
        raise InvalidTokenError(f"expected {expected_type} token")

    if not isinstance(payload.get("sub"), str) or not payload["sub"]:
        raise InvalidTokenError("missing sub claim")

    return payload
