#!/usr/bin/env python3
"""创建/提升本地 admin 账号。用法：
  ADMIN_STUDENT_ID=admin ADMIN_PASSWORD='Admin@123456' python3 scripts/seed_admin.py
"""
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
os.chdir(BACKEND)
sys.path.insert(0, str(BACKEND))

from sqlmodel import Session, select  # noqa: E402

from app.core.database import engine, init_db  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models import User  # noqa: E402

student_id = os.getenv("ADMIN_STUDENT_ID", "admin")
password = os.getenv("ADMIN_PASSWORD", "Admin@123456")

init_db()
with Session(engine) as session:
    user = session.exec(select(User).where(User.student_id == student_id)).first()
    if user is None:
        user = User(
            student_id=student_id,
            password_hash=hash_password(password),
            role="admin",
            status="active",
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        print(f"created admin: {student_id} / {password}")
    else:
        user.role = "admin"
        user.status = "active"
        if os.getenv("RESET_ADMIN_PASSWORD") == "1":
            user.password_hash = hash_password(password)
        session.add(user)
        session.commit()
        print(f"promoted existing user: {student_id} (password unchanged unless RESET_ADMIN_PASSWORD=1)")
