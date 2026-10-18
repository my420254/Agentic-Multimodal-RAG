"""后台控制面 API：账号、API Key、模型、系统提示词、审计。

仅 admin 可访问；所有写操作落 audit_logs。
"""

from __future__ import annotations

import hashlib
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlmodel import Session, func, select

from app.core.database import get_session
from app.core.deps import get_current_admin
from app.core.security import hash_password
from app.models import ApiKey, AuditLog, CustomModel, KnowledgeBase, ModelType, RequestLog, SystemPrompt, User
from app.services.audit_service import record_audit
from app.services.prompt_service import prompt_workshop_service
from app.services.system_prompt_service import system_prompt_service

router = APIRouter(
    prefix="/admin",
    tags=["Admin"],
    dependencies=[Depends(get_current_admin)],
)

VALID_ROLES = {"student", "admin"}
VALID_STATUS = {"active", "disabled"}


class UserCreateRequest(BaseModel):
    student_id: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=8, max_length=72)
    email: Optional[str] = None
    role: str = "student"


class UserUpdateRequest(BaseModel):
    role: Optional[str] = None
    status: Optional[str] = None


class ApiKeyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    owner_id: Optional[str] = None
    scopes: List[str] = Field(default_factory=lambda: ["chat:read", "kb:read"])
    expires_days: Optional[int] = Field(default=None, ge=1, le=3650)


class ModelCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    model_type: str
    base_url: str
    api_key: str = ""
    model_name: str
    context_length: int = 4096
    is_active: bool = True


class ModelUpdateRequest(BaseModel):
    name: Optional[str] = None
    model_type: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model_name: Optional[str] = None
    context_length: Optional[int] = None
    is_active: Optional[bool] = None


class PromptCreateRequest(BaseModel):
    key: str
    content: str = Field(min_length=1)


class PromptPublishRequest(BaseModel):
    version: int = Field(ge=1)


def _mask_key(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}***{value[-4:]}"


def _user_out(user: User) -> Dict[str, Any]:
    return {
        "id": user.id,
        "student_id": user.student_id,
        "email": user.email,
        "role": user.role,
        "status": user.status,
        "created_at": user.created_at,
        "deleted_at": user.deleted_at,
    }


def _api_key_out(row: ApiKey) -> Dict[str, Any]:
    return {
        "id": row.id,
        "owner_id": row.owner_id,
        "name": row.name,
        "key_prefix": row.key_prefix,
        "scopes": [s for s in (row.scopes or "").split(",") if s],
        "last_used_at": row.last_used_at,
        "expires_at": row.expires_at,
        "revoked_at": row.revoked_at,
        "created_at": row.created_at,
    }


def _model_out(row: CustomModel) -> Dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "model_type": row.model_type.value if hasattr(row.model_type, "value") else str(row.model_type),
        "base_url": row.base_url,
        "model_name": row.model_name,
        "context_length": row.context_length,
        "is_active": row.is_active,
        "api_key_masked": _mask_key(row.api_key),
        "created_at": row.created_at,
    }


def _prompt_out(row: SystemPrompt, include_content: bool = True) -> Dict[str, Any]:
    data = {
        "id": row.id,
        "key": row.key,
        "version": row.version,
        "status": row.status,
        "created_by": row.created_by,
        "created_at": row.created_at,
        "published_at": row.published_at,
    }
    if include_content:
        data["content"] = row.content
    return data


@router.get("/overview")
async def overview(
    admin: User = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    def count(model):
        return int(session.exec(select(func.count()).select_from(model)).one())

    return {
        "users": count(User),
        "knowledge_bases": count(KnowledgeBase),
        "models": count(CustomModel),
        "api_keys": count(ApiKey),
        "system_prompts": count(SystemPrompt),
        "audit_logs": count(AuditLog),
        "request_logs": count(RequestLog),
    }


# ==================== 用户 ====================

@router.get("/users")
async def list_users(
    query: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    admin: User = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    statement = select(User)
    if query:
        statement = statement.where(
            (User.student_id.contains(query)) | (User.email.contains(query))
        )
    total = int(session.exec(
        select(func.count()).select_from(User).where(
            (User.student_id.contains(query)) | (User.email.contains(query))
        ) if query else select(func.count()).select_from(User)
    ).one())
    rows = session.exec(
        statement.order_by(User.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {"items": [_user_out(u) for u in rows], "total": total, "page": page, "page_size": page_size}


@router.post("/users")
async def create_user(
    req: UserCreateRequest,
    admin: User = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    if req.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail="role 只能是 student/admin")
    existing = session.exec(select(User).where(User.student_id == req.student_id)).first()
    if existing is not None:
        raise HTTPException(status_code=400, detail="学号/账号已存在")
    if req.email:
        existing_email = session.exec(select(User).where(User.email == req.email)).first()
        if existing_email is not None:
            raise HTTPException(status_code=400, detail="邮箱已存在")
    user = User(
        student_id=req.student_id,
        email=req.email,
        password_hash=hash_password(req.password),
        role=req.role,
        status="active",
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    record_audit(session, actor_id=admin.id, action="user.create", target_type="user",
                 target_id=user.id, detail={"student_id": user.student_id, "role": user.role})
    return _user_out(user)


@router.patch("/users/{user_id}")
async def update_user(
    user_id: str,
    req: UserUpdateRequest,
    admin: User = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    target = session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if req.role is not None and req.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail="role 只能是 student/admin")
    if req.status is not None and req.status not in VALID_STATUS:
        raise HTTPException(status_code=400, detail="status 只能是 active/disabled")

    becoming_non_admin = (
        target.role == "admin"
        and ((req.role is not None and req.role != "admin") or (req.status is not None and req.status != "active"))
    )
    if becoming_non_admin:
        active_admins = int(session.exec(
            select(func.count()).select_from(User).where(User.role == "admin", User.status == "active")
        ).one())
        if active_admins <= 1:
            raise HTTPException(status_code=400, detail="不能禁用/降级最后一个 active 管理员")

    changes = {}
    if req.role is not None and req.role != target.role:
        changes["role"] = [target.role, req.role]
        target.role = req.role
    if req.status is not None and req.status != target.status:
        changes["status"] = [target.status, req.status]
        target.status = req.status
    session.add(target)
    session.commit()
    session.refresh(target)
    if changes:
        record_audit(session, actor_id=admin.id, action="user.update", target_type="user",
                     target_id=target.id, detail={"student_id": target.student_id, "changes": changes})
    return _user_out(target)


@router.post("/users/{user_id}/reset-password")
async def reset_user_password(
    user_id: str,
    admin: User = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    target = session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    temp_password = "Tmp@" + secrets.token_urlsafe(9)
    target.password_hash = hash_password(temp_password)
    session.add(target)
    session.commit()
    record_audit(session, actor_id=admin.id, action="user.reset_password", target_type="user",
                 target_id=target.id, detail={"student_id": target.student_id})
    return {"user_id": target.id, "temp_password": temp_password, "message": "临时密码只显示一次，请让用户登录后修改"}


# ==================== API Key ====================

@router.get("/api-keys")
async def list_api_keys(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    admin: User = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    total = int(session.exec(select(func.count()).select_from(ApiKey)).one())
    rows = session.exec(
        select(ApiKey).order_by(ApiKey.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    ).all()
    return {"items": [_api_key_out(r) for r in rows], "total": total, "page": page, "page_size": page_size}


@router.post("/api-keys")
async def create_api_key(
    req: ApiKeyCreateRequest,
    admin: User = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    owner_id = req.owner_id or admin.id
    owner = session.get(User, owner_id)
    if owner is None:
        raise HTTPException(status_code=404, detail="Key 所属用户不存在")
    raw = "sk_live_" + secrets.token_urlsafe(32)
    row = ApiKey(
        owner_id=owner.id,
        name=req.name,
        key_prefix=raw[:12],
        key_hash=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        scopes=",".join(req.scopes),
        expires_at=(datetime.now(timezone.utc) + timedelta(days=req.expires_days)) if req.expires_days else None,
        created_by=admin.id,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    record_audit(session, actor_id=admin.id, action="api_key.create", target_type="api_key",
                 target_id=row.id, detail={"name": row.name, "owner_id": owner.id, "scopes": req.scopes})
    return {"api_key": _api_key_out(row), "key": raw, "message": "明文 Key 只显示一次"}


@router.delete("/api-keys/{key_id}")
async def revoke_api_key(
    key_id: str,
    admin: User = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    row = session.get(ApiKey, key_id)
    if row is None:
        raise HTTPException(status_code=404, detail="API Key 不存在")
    if row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
        session.add(row)
        session.commit()
        record_audit(session, actor_id=admin.id, action="api_key.revoke", target_type="api_key",
                     target_id=row.id, detail={"name": row.name, "prefix": row.key_prefix})
    return _api_key_out(row)


# ==================== 模型 ====================

@router.get("/models")
async def list_models(
    admin: User = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    rows = session.exec(select(CustomModel).order_by(CustomModel.created_at.desc())).all()
    return {"items": [_model_out(r) for r in rows], "total": len(rows)}


@router.post("/models")
async def create_model(
    req: ModelCreateRequest,
    admin: User = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    try:
        model_type = ModelType(req.model_type)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的 model_type")
    row = CustomModel(
        name=req.name,
        model_type=model_type,
        base_url=req.base_url,
        api_key=req.api_key,
        model_name=req.model_name,
        context_length=req.context_length,
        is_active=req.is_active,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    record_audit(session, actor_id=admin.id, action="model.create", target_type="model",
                 target_id=row.id, detail={"name": row.name, "type": req.model_type})
    return _model_out(row)


@router.patch("/models/{model_id}")
async def update_model(
    model_id: str,
    req: ModelUpdateRequest,
    admin: User = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    row = session.get(CustomModel, model_id)
    if row is None:
        raise HTTPException(status_code=404, detail="模型不存在")
    changes = {}
    for field in ("name", "base_url", "model_name", "context_length", "is_active"):
        value = getattr(req, field)
        if value is not None:
            setattr(row, field, value)
            changes[field] = value
    if req.model_type is not None:
        try:
            row.model_type = ModelType(req.model_type)
            changes["model_type"] = req.model_type
        except ValueError:
            raise HTTPException(status_code=400, detail="无效的 model_type")
    if req.api_key is not None and req.api_key.strip():
        row.api_key = req.api_key
        changes["api_key"] = "updated"
    session.add(row)
    session.commit()
    session.refresh(row)
    if changes:
        record_audit(session, actor_id=admin.id, action="model.update", target_type="model",
                     target_id=row.id, detail={"changes": changes})
    return _model_out(row)


@router.delete("/models/{model_id}")
async def delete_model(
    model_id: str,
    admin: User = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    row = session.get(CustomModel, model_id)
    if row is None:
        raise HTTPException(status_code=404, detail="模型不存在")
    session.delete(row)
    session.commit()
    record_audit(session, actor_id=admin.id, action="model.delete", target_type="model",
                 target_id=model_id, detail={"name": row.name})
    return {"ok": True}


@router.post("/models/{model_id}/test")
async def test_model(
    model_id: str,
    admin: User = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    row = session.get(CustomModel, model_id)
    if row is None:
        raise HTTPException(status_code=404, detail="模型不存在")
    started = time.perf_counter()
    if not (row.base_url or "").startswith(("http://", "https://")):
        return {"ok": False, "latency_ms": 0, "error": "本地模型路径不支持在线测试，请在部署环境验证"}
    try:
        from openai import OpenAI
        client = OpenAI(api_key=row.api_key or "none", base_url=row.base_url, timeout=15)
        if row.model_type in (ModelType.LLM, ModelType.VLM):
            resp = client.chat.completions.create(
                model=row.model_name,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
                temperature=0,
            )
            result = resp.choices[0].message.content or "ok"
        elif row.model_type == ModelType.EMBEDDING:
            resp = client.embeddings.create(model=row.model_name, input="ping")
            result = f"dim={len(resp.data[0].embedding)}"
        else:
            import httpx
            url = row.base_url.rstrip("/")
            if not url.endswith("/rerank"):
                url += "/rerank"
            resp = httpx.post(
                url,
                headers={"Authorization": f"Bearer {row.api_key}"},
                json={"model": row.model_name, "query": "ping", "documents": ["ping"], "top_n": 1},
                timeout=15,
            )
            result = f"status={resp.status_code}"
            resp.raise_for_status()
        latency = (time.perf_counter() - started) * 1000
        record_audit(session, actor_id=admin.id, action="model.test", target_type="model",
                     target_id=row.id, detail={"ok": True, "latency_ms": round(latency, 1)})
        return {"ok": True, "latency_ms": round(latency, 1), "result": str(result)[:200]}
    except Exception as e:
        latency = (time.perf_counter() - started) * 1000
        return {"ok": False, "latency_ms": round(latency, 1), "error": str(e)[:300]}


# ==================== 系统提示词 ====================

VALID_PROMPT_KEYS = set(prompt_workshop_service.DEFAULT_TEMPLATES.keys())


@router.get("/prompts")
async def list_prompts(
    admin: User = Depends(get_current_admin),
):
    items = []
    for key in sorted(VALID_PROMPT_KEYS):
        versions = system_prompt_service.list_versions(key)
        active = next((v for v in versions if v.status == "active"), None)
        items.append({
            "key": key,
            "name": prompt_workshop_service.DEFAULT_TEMPLATES[key].name,
            "active_version": active.version if active else None,
            "versions": len(versions),
        })
    return {"items": items, "total": len(items)}


@router.get("/prompts/{key}/versions")
async def list_prompt_versions(
    key: str,
    admin: User = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    if key not in VALID_PROMPT_KEYS:
        raise HTTPException(status_code=404, detail="未知的系统提示词 key")
    return {"items": [_prompt_out(v) for v in system_prompt_service.list_versions(key, session)]}


@router.post("/prompts")
async def create_prompt_draft(
    req: PromptCreateRequest,
    admin: User = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    if req.key not in VALID_PROMPT_KEYS:
        raise HTTPException(status_code=400, detail="未知的系统提示词 key")
    row = system_prompt_service.create_draft(req.key, req.content, admin.id, session)
    return _prompt_out(row)


@router.post("/prompts/{key}/publish")
async def publish_prompt(
    key: str,
    req: PromptPublishRequest,
    admin: User = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    if key not in VALID_PROMPT_KEYS:
        raise HTTPException(status_code=404, detail="未知的系统提示词 key")
    try:
        row = system_prompt_service.publish(key, req.version, admin.id, session)
    except KeyError:
        raise HTTPException(status_code=404, detail="提示词版本不存在")
    record_audit(session, actor_id=admin.id, action="prompt.publish", target_type="system_prompt",
                 target_id=row.id, detail={"key": key, "version": req.version})
    return _prompt_out(row)


@router.post("/prompts/{key}/rollback")
async def rollback_prompt(
    key: str,
    req: PromptPublishRequest,
    admin: User = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    return await publish_prompt(key, req, admin, session)


# ==================== 观测 ====================

@router.get("/request-logs")
async def list_request_logs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    admin: User = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    total = int(session.exec(select(func.count()).select_from(RequestLog)).one())
    rows = session.exec(
        select(RequestLog).order_by(RequestLog.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    ).all()
    return {
        "items": [
            {
                "id": r.id,
                "method": r.method,
                "path": r.path,
                "status_code": r.status_code,
                "duration_ms": r.duration_ms,
                "user_id": r.user_id,
                "client_ip": r.client_ip,
                "created_at": r.created_at,
            }
            for r in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/observability/summary")
async def observability_summary(
    admin: User = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    total = int(session.exec(select(func.count()).select_from(RequestLog)).one())
    errors = int(session.exec(
        select(func.count()).select_from(RequestLog).where(RequestLog.status_code >= 400)
    ).one())
    avg_latency = session.exec(select(func.avg(RequestLog.duration_ms))).one()
    top_rows = session.exec(
        select(RequestLog.path, func.count().label("cnt"))
        .group_by(RequestLog.path)
        .order_by(func.count().desc())
        .limit(10)
    ).all()
    return {
        "total_requests": total,
        "error_requests": errors,
        "error_rate": round(errors / total, 4) if total else 0.0,
        "avg_latency_ms": round(float(avg_latency), 2) if avg_latency is not None else 0.0,
        "top_paths": [{"path": p, "count": int(c)} for p, c in top_rows],
        "metrics_endpoint": "/metrics",
    }


# ==================== 审计 ====================

@router.get("/audit-logs")
async def list_audit_logs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    admin: User = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    total = int(session.exec(select(func.count()).select_from(AuditLog)).one())
    rows = session.exec(
        select(AuditLog).order_by(AuditLog.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    ).all()
    return {
        "items": [
            {
                "id": r.id,
                "actor_id": r.actor_id,
                "action": r.action,
                "target_type": r.target_type,
                "target_id": r.target_id,
                "detail": r.detail,
                "created_at": r.created_at,
            }
            for r in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
