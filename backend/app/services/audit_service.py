"""后台写操作审计。"""

from __future__ import annotations

import json
from typing import Any, Optional

from sqlmodel import Session

from app.models import AuditLog


def record_audit(
    session: Session,
    *,
    actor_id: Optional[str],
    action: str,
    target_type: str,
    target_id: Optional[str] = None,
    detail: Optional[Any] = None,
) -> AuditLog:
    row = AuditLog(
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=json.dumps(detail, ensure_ascii=False, default=str) if detail is not None else None,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row
