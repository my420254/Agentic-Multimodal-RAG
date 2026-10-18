#!/usr/bin/env python3
"""
W1 演示账号初始化（仅限本地 dev）。

创建两个测试账号：
    2023001 / 2023002
默认密码：Test@123456（可用 SEED_PASSWORD 环境变量覆盖）

用法（JWT_SECRET 必须已配置，但本脚本只做密码哈希，不会签发 token）：
    cd /home/yang/Agentic-Multimodal-RAG
    JWT_SECRET="$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')" \
        python3 scripts/seed_demo_users.py

安全边界：
- 只允许 ENV=dev；ENV 为其他值直接退出。
- 不打印密码哈希；固定演示密码会打印警告。
- 幂等：已存在的学号跳过，不覆盖密码。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlmodel import Session, select  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.database import engine, init_db  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models import User  # noqa: E402

DEFAULT_DEV_PASSWORD = "Test@123456"
DEMO_USERS = (
    {"student_id": "2023001", "email": "2023001@lnu.edu.cn"},
    {"student_id": "2023002", "email": "2023002@lnu.edu.cn"},
)


def main() -> int:
    settings = get_settings()
    if settings.ENV != "dev":
        print(f"[拒绝] 当前 ENV={settings.ENV}；seed 脚本仅允许在 dev 环境运行。", file=sys.stderr)
        return 2

    password = os.environ.get("SEED_PASSWORD", DEFAULT_DEV_PASSWORD)
    if len(password.encode("utf-8")) > 72:
        print("[拒绝] SEED_PASSWORD 超过 bcrypt 的 72 字节上限。", file=sys.stderr)
        return 2

    init_db()
    # dev 环境引擎默认 echo=True，会把 password_hash 打进 SQL 日志；seed 时关闭。
    engine.echo = False

    created = 0
    with Session(engine) as session:
        for item in DEMO_USERS:
            existing = session.exec(
                select(User).where(User.student_id == item["student_id"])
            ).first()
            if existing is not None:
                print(f"[跳过] 学号 {item['student_id']} 已存在（id={existing.id}）")
                continue

            user = User(
                student_id=item["student_id"],
                email=item["email"],
                password_hash=hash_password(password),
                role="student",
                status="active",
            )
            session.add(user)
            session.commit()
            session.refresh(user)
            created += 1
            print(f"[创建] 学号 {user.student_id} · id={user.id} · email={user.email}")

    print(f"\n完成：新建 {created} 个账号，库中演示账号应共 {len(DEMO_USERS)} 个。")
    if password == DEFAULT_DEV_PASSWORD:
        print(f"[警告] 仅限本地开发使用固定演示密码：{password}")
        print("[警告] 不要在生产环境运行本脚本；不要把这个密码写进任何部署配置。")
    else:
        print("[提示] 本次使用 SEED_PASSWORD 环境变量，未在输出中回显。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
