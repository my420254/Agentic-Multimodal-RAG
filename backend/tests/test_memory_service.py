import uuid

from app.services.memory_service import MemoryService


def test_l1_short_term_sliding_window():
    """测试 L1 短期滑动窗口记忆存取（按 user_id 隔离）"""
    mem = MemoryService()
    test_user = f"test_user_{uuid.uuid4().hex[:8]}"
    test_session = f"test_session_{uuid.uuid4().hex[:8]}"

    for i in range(5):
        mem.add_message(
            test_user,
            test_session,
            "user" if i % 2 == 0 else "assistant",
            f"消息-{i}",
        )

    assert mem.get_all_messages_count(test_user, test_session) == 5

    recent = mem.get_recent_messages(test_user, test_session, limit=3)
    assert len(recent) == 3
    assert recent[-1]["content"] == "消息-4"

    mem.clear_session(test_user, test_session)
    assert mem.get_all_messages_count(test_user, test_session) == 0


def test_l2_mid_term_session_summary():
    """测试 L2 中期会话增量摘要缓存"""
    mem = MemoryService()
    test_user = f"test_user_{uuid.uuid4().hex[:8]}"
    test_session = f"test_session_{uuid.uuid4().hex[:8]}"

    assert mem.get_summary(test_user, test_session) is None

    test_summary = "用户正在排查线上 K8s 集群中微服务 Pod OOM 崩溃事件"
    mem.set_summary(test_user, test_session, test_summary)
    cached_summary = mem.get_summary(test_user, test_session)
    assert cached_summary == test_summary

    mem.clear_session(test_user, test_session)
    assert mem.get_summary(test_user, test_session) is None


def test_l3_long_term_user_preference_extraction():
    """测试 L3 长期偏好记忆自适应提取与冲突更新"""
    mem = MemoryService()
    test_user = f"test_user_{uuid.uuid4().hex[:8]}"

    msg1 = "我平时排障更倾向于使用 Linux 命令行工具和 kubectl"
    mem.extract_preference_if_any(test_user, msg1)
    profile = mem.get_user_profile(test_user)
    assert len(profile) > 0

    mem.set_user_preference(test_user, "format", "紧凑表格与逐步操作命令")
    updated_profile = mem.get_user_profile(test_user)
    assert updated_profile.get("format") == "紧凑表格与逐步操作命令"


def test_assemble_context_for_prompt():
    """测试三层记忆向 LLM 上下文的标准装配"""
    mem = MemoryService()
    test_user = f"test_user_{uuid.uuid4().hex[:8]}"
    test_session = f"test_session_{uuid.uuid4().hex[:8]}"

    mem.set_summary(test_user, test_session, "历史摘要：讨论了 Redis 缓存雪崩")
    mem.set_user_preference(test_user, "language", "Python")

    context_dict = mem.assemble_context_for_prompt(
        user_id=test_user,
        session_id=test_session,
    )
    assert isinstance(context_dict, dict)
    assert "profile_text" in context_dict
    assert "summary_text" in context_dict
    assert "Python" in context_dict["profile_text"]
    assert "Redis 缓存雪崩" in context_dict["summary_text"]
