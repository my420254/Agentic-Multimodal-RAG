#!/usr/bin/env python3
"""
把 legacy local.db 里的 4 个模型配置（LLM/Embedding/VLM/Rerank）迁到 PostgreSQL。

只迁移配置，不打印/api_key；已存在的 id 跳过。用于让前端设置页和 Rerank 选型
能读到与 .env 一致的模型列表。
"""

from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT / "backend"
LEGACY_DB = BACKEND_DIR / "local.db"
os.chdir(BACKEND_DIR)
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlmodel import Session, select  # noqa: E402

from app.core.database import engine  # noqa: E402
from app.models import CustomModel, ModelType  # noqa: E402


def _dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(str(value))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def main() -> int:
    if not LEGACY_DB.exists():
        print(f"[错误] legacy 数据库不存在: {LEGACY_DB}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(f"file:{LEGACY_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("select * from custom_models").fetchall()
    conn.close()

    engine.echo = False
    with Session(engine) as session:
        for row in rows:
            if session.get(CustomModel, row["id"]) is not None:
                print(f"[跳过] {row['name']}")
                continue
            session.add(
                CustomModel(
                    id=row["id"],
                    name=row["name"],
                    model_type=ModelType(str(row["model_type"]).lower()),
                    base_url=row["base_url"],
                    api_key=row["api_key"],
                    model_name=row["model_name"],
                    context_length=row["context_length"],
                    is_active=bool(row["is_active"]),
                    created_at=_dt(row["created_at"]),
                    updated_at=_dt(row["updated_at"]),
                )
            )
            session.commit()
            print(f"[创建] {row['name']} ({row['model_type']}, {row['model_name']})")

        models = session.exec(select(CustomModel)).all()
        print(f"[完成] PostgreSQL custom_models = {len(models)}")
        for model in models:
            print(f"  - {model.name} / {model.model_type.value} / {model.model_name} / active={model.is_active}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
