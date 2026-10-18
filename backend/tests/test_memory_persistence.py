"""
PostgreSQL 记忆持久化专项测试（不在 make test-fast 列表里，手动运行）。

验证：
- 会话/消息/摘要/画像写入 PG；
- 换一个空 Redis 实例后仍能从 PG 读回（模拟 Redis 重启或 7 天 TTL 到期）；
- 跨用户 claim 仍然拒绝；
- clear_session 会删除 PG 消息/会话。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

from app.models import InterviewMessage, InterviewSession, UserProfile
from app.services.memory_service import MemoryService


@pytest.fixture(scope="module")
def pg_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


def test_memory_survives_empty_redis(pg_engine):
    uid = f"persist_user_{uuid.uuid4().hex[:8]}"
    sid = f"persist_session_{uuid.uuid4().hex[:8]}"
    other = f"persist_other_{uuid.uuid4().hex[:8]}"

    writer = MemoryService(
        redis_url="redis://localhost:6379/0",
        db_engine=pg_engine,
        persistence=True,
    )
    assert writer.claim_session(uid, sid) is True
    assert writer.claim_session(other, sid) is False
    writer.add_message(uid, sid, "user", "请记住：我的目标岗位是 Agent 开发")
    writer.add_message(uid, sid, "assistant", "已记录")
    writer.set_summary(uid, sid, "用户目标岗位：Agent 开发")
    writer.set_user_preference(uid, "target_role", "Agent 开发")

    # 模拟 Redis 被清空/重启：换一个空的 Redis DB
    reader = MemoryService(
        redis_url="redis://localhost:6379/15",
        db_engine=pg_engine,
        persistence=True,
    )
    assert reader.get_all_messages_count(uid, sid) == 2
    msgs = reader.get_recent_messages(uid, sid)
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert "Agent 开发" in msgs[0]["content"]
    assert reader.get_summary(uid, sid) == "用户目标岗位：Agent 开发"
    assert reader.get_user_profile(uid).get("target_role") == "Agent 开发"
    assert reader.owns_session(uid, sid) is True
    assert reader.owns_session(other, sid) is False

    # 直接查 PG 确认真落库
    with Session(pg_engine) as db:
        assert db.get(InterviewSession, sid).owner_id == uid
        assert len(
            db.exec(
                select(InterviewMessage).where(InterviewMessage.session_id == sid)
            ).all()
        ) == 2
        assert db.exec(
            select(UserProfile).where(
                UserProfile.owner_id == uid,
                UserProfile.field == "target_role",
            )
        ).first().value == "Agent 开发"

    writer.clear_session(uid, sid)
    assert reader.get_all_messages_count(uid, sid) == 0
    assert reader.get_summary(uid, sid) is None
    with Session(pg_engine) as db:
        assert db.get(InterviewSession, sid) is None
        assert db.exec(
            select(InterviewMessage).where(InterviewMessage.session_id == sid)
        ).all() == []

    # 清理 Redis 画像缓存
    try:
        if writer.client is not None:
            writer.client.delete(writer._profile_key(uid))
        if reader.client is not None:
            reader.client.delete(reader._profile_key(uid))
    except Exception:
        pass
