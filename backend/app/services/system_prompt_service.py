"""全局系统提示词版本管理。

与用户级 PromptService 覆盖分开：
- 用户覆盖 > 全局 active > 代码默认；
- 发布新版本时，旧 active 自动归档；
- 所有写操作由 admin API 记录审计日志。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from sqlmodel import Session, select

from app.core.database import engine
from app.models import SystemPrompt


class SystemPromptService:
    def get_active(self, key: str) -> Optional[str]:
        """返回全局 active 提示词正文；无 active 或 DB 不可用时返回 None。"""
        try:
            with Session(engine) as session:
                row = session.exec(
                    select(SystemPrompt)
                    .where(SystemPrompt.key == key, SystemPrompt.status == "active")
                    .order_by(SystemPrompt.version.desc())
                ).first()
                return row.content if row else None
        except Exception:
            return None

    def list_versions(self, key: str, session: Optional[Session] = None) -> List[SystemPrompt]:
        if session is None:
            with Session(engine) as s:
                return self.list_versions(key, s)
        return list(session.exec(
            select(SystemPrompt)
            .where(SystemPrompt.key == key)
            .order_by(SystemPrompt.version.desc())
        ).all())

    def list_keys(self) -> List[str]:
        with Session(engine) as session:
            rows = session.exec(select(SystemPrompt.key).distinct()).all()
            return sorted({r for r in rows if r})

    def get_version(self, key: str, version: int, session: Optional[Session] = None) -> Optional[SystemPrompt]:
        if session is None:
            with Session(engine) as s:
                return self.get_version(key, version, s)
        return session.exec(
            select(SystemPrompt).where(
                SystemPrompt.key == key,
                SystemPrompt.version == version,
            )
        ).first()

    def create_draft(self, key: str, content: str, created_by: Optional[str], session: Optional[Session] = None) -> SystemPrompt:
        if session is None:
            with Session(engine) as s:
                return self.create_draft(key, content, created_by, s)
        latest = session.exec(
            select(SystemPrompt)
            .where(SystemPrompt.key == key)
            .order_by(SystemPrompt.version.desc())
        ).first()
        next_version = (latest.version + 1) if latest else 1
        row = SystemPrompt(
            key=key,
            version=next_version,
            content=content,
            status="draft",
            created_by=created_by,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return row

    def publish(self, key: str, version: int, published_by: Optional[str], session: Optional[Session] = None) -> SystemPrompt:
        if session is None:
            with Session(engine) as s:
                return self.publish(key, version, published_by, s)
        target = session.exec(
            select(SystemPrompt).where(
                SystemPrompt.key == key,
                SystemPrompt.version == version,
            )
        ).first()
        if target is None:
            raise KeyError(f"提示词版本不存在: {key} v{version}")
        active_rows = session.exec(
            select(SystemPrompt).where(
                SystemPrompt.key == key,
                SystemPrompt.status == "active",
            )
        ).all()
        for row in active_rows:
            row.status = "archived"
            session.add(row)
        target.status = "active"
        target.published_at = datetime.now(timezone.utc)
        session.add(target)
        session.commit()
        session.refresh(target)
        return target


system_prompt_service = SystemPromptService()
