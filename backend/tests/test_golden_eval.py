"""
离线 Golden Testset 自动化评测基准
研发单位：辽宁大学 · 辽宁省公共舆情与网络安全信息系统重点实验室
评测对象：
1. 岗位真实度与合规检测 (Fraud vs Safe)
2. 简历-JD 双向匹配度与 STAR 事实保真约束 (Truth Preservation)
3. 技术依赖图谱拓扑追问链有效性 (Graph Probing Completeness)
"""

import pytest
from app.services.job_fraud_detector import job_fraud_detector, FraudRiskLevel
from app.services.career_matcher import career_matcher_service
from app.services.graphrag_service import graphrag_service


GOLDEN_TEST_CASES = [
    {
        "id": "CASE-01-SAFE-JD",
        "type": "fraud_detection",
        "title": "大模型与搜索后端研发工程师",
        "jd": "熟练掌握 Python/FastAPI 与 PostgreSQL/Redis 高并发架构，深入理解 RAG 向量检索与精排，统招硕士以上学历。",
        "expected_risk": FraudRiskLevel.SAFE,
        "is_fraud": False
    },
    {
        "id": "CASE-02-TRAP-LOAN",
        "type": "fraud_detection",
        "title": "高薪零基础人工智能学徒",
        "jd": "无需任何经验与学历，包分配工作，入职前需统一参加为期3个月定制化岗前实训，可办理学费分期实训贷款2万元。",
        "expected_risk": FraudRiskLevel.HIGH_RISK,
        "is_fraud": True
    },
    {
        "id": "CASE-03-OVERSEAS-SCAM",
        "type": "fraud_detection",
        "title": "海外数据录入专员",
        "jd": "月薪三万包机票签证，工作地点老挝/缅北特区，包吃包住包往返机票，护照公司统一管理，高额提成日结。",
        "expected_risk": FraudRiskLevel.HIGH_RISK,
        "is_fraud": True
    }
]


@pytest.mark.asyncio
async def test_golden_fraud_detection_benchmark():
    """验证合规与防欺诈离线黄金测试集识别准确率达到 100%"""
    success_count = 0
    for case in GOLDEN_TEST_CASES:
        res = await job_fraud_detector.analyze(
            job_title=case["title"],
            company="评测基准测试企业",
            job_description=case["jd"],
            deep_llm_audit=False
        )
        if res.is_fraudulent == case["is_fraud"]:
            success_count += 1
    accuracy = success_count / len(GOLDEN_TEST_CASES)
    assert accuracy == 1.0, f"Golden fraud set accuracy fell below 100%: {accuracy}"


@pytest.mark.asyncio
async def test_golden_resume_star_truth_preservation():
    """验证 STAR 重写建议恪守事实保真（Truth Preservation），对无实测数据强制给出补充标记"""
    vague_resume = """
    项目经历：
    基于 Redis 实现了高并发限流和缓存，提升了接口访问速度。
    参与了大模型检索增强 RAG 系统的构建，完成了混合召回。
    """
    sample_jd = """
    要求精通 Redis 高并发限流、PostgreSQL 向量检索与高并发系统优化。
    """
    res = await career_matcher_service.analyze_and_optimize(vague_resume, sample_jd)
    
    assert res.overall_match_score > 0
    assert len(res.star_optimizations) >= 2
    
    # 验证是否包含事实保真占位符
    has_truth_marker = False
    for item in res.star_optimizations:
        combined_text = f"{item.star_rewrite} {item.result}"
        if "请" in combined_text or "补充" in combined_text or "真实" in combined_text or "占位" in combined_text or "填入" in combined_text:
            has_truth_marker = True
            break
    assert has_truth_marker, "STAR rewrite violated truth-preservation guardrail: missing metric prompt marker"


def test_golden_graphrag_topological_chain():
    """验证技术依赖图谱能够针对核心技术（如 Redis）生成具备逻辑依赖的多跳追问拓扑链路"""
    subgraph = graphrag_service.search_subgraph("Redis 高并发与缓存雪崩", max_depth=2)
    assert len(subgraph.nodes) >= 2
    assert len(subgraph.traversal_paths) >= 1
    assert "GraphRAG" in subgraph.graph_context or "Redis" in subgraph.graph_context


def test_golden_memory_cross_user_isolation():
    """验证三层记忆管理系统严格落实用户级与会话级权限物理隔离（杜绝跨用户画像污染与会话串线）"""
    from app.services.memory_service import memory_service
    user_a = "student_user_alpha_101"
    user_b = "student_user_beta_202"
    session_a = "session_mock_a_001"
    session_b = "session_mock_b_002"

    try:
        # 1. 模拟用户 A 偏好写入 (Go 语言微服务)
        memory_service.set_user_preference(user_a, "target_language", "GoFrame / Gin")
        memory_service.add_message(user_a, session_a, "user", "我的主修方向是 Go 语言微服务与 Kafka。")

        # 2. 模拟用户 B 偏好写入 (Python 深度学习)
        memory_service.set_user_preference(user_b, "target_language", "Python PyTorch")
        memory_service.add_message(user_b, session_b, "user", "我的主修方向是 Python NLP 算法。")

        # 3. 校验用户 A 的画像与上下文
        ctx_a = memory_service.assemble_context_for_prompt(user_id=user_a, session_id=session_a)
        assert "GoFrame" in ctx_a["profile_text"]
        assert "PyTorch" not in ctx_a["profile_text"]
        assert any("Go 语言微服务" in m["content"] for m in ctx_a["recent_messages"])
        assert not any("PyTorch" in m["content"] for m in ctx_a["recent_messages"])

        # 4. 校验用户 B 的画像与上下文
        ctx_b = memory_service.assemble_context_for_prompt(user_id=user_b, session_id=session_b)
        assert "PyTorch" in ctx_b["profile_text"]
        assert "GoFrame" not in ctx_b["profile_text"]
        assert any("Python NLP" in m["content"] for m in ctx_b["recent_messages"])
        assert not any("GoFrame" in m["content"] for m in ctx_b["recent_messages"])

    finally:
        # 清理测试状态
        memory_service.clear_session(user_a, session_a)
        memory_service.clear_session(user_b, session_b)


@pytest.mark.asyncio
async def test_golden_agent_adaptive_interview_loop():
    """验证模拟面试 Agent 在遇到候选人知识断层时，能够自适应降维并不再死板推进极端高并发"""
    from app.services.mock_interview import mock_interview_service, ProbingAction, ProbingStage

    # 阶段 1：候选人表明盲区
    res_turn1 = await mock_interview_service.chat(
        messages=[{"role": "user", "content": "关于 Redis 分布式锁看门狗和红锁算法，我平时在实验室单机开发没接触过，不太了解。"}],
        mode="mock_interview",
        user_id="golden_eval_user",
    )
    assert res_turn1.probing_action == ProbingAction.PIVOT_FALLBACK
    assert len(res_turn1.identified_gaps) >= 1
    # 验证降维后不再硬深挖 1000 QPS
    assert "1000+ QPS" not in res_turn1.reply_text

    # 阶段 2：候选人回答基础机制很清晰并讲清原理
    res_turn2 = await mock_interview_service.chat(
        messages=[
            {"role": "user", "content": "关于 Redis 分布式锁看门狗，我平时没接触过。"},
            {"role": "assistant", "content": res_turn1.reply_text},
            {"role": "user", "content": "Redis 核心数据结构有 String、Hash、List、Set、ZSet。String 底层使用 SDS（简单动态字符串），空间预分配并杜绝缓冲区溢出；ZSet 在元素较多时采用 Skiplist 跳表，相较于平衡树/红黑树，跳表在范围查询（ZRANGEBYSCORE）时能沿链表水平扫描，不仅时间复杂度为 O(log N)，而且实现更简单、内存局部性更好。"}
        ],
        mode="mock_interview",
        user_id="golden_eval_user",
    )
    assert res_turn2.probing_action == ProbingAction.DEEP_PROBE
    assert res_turn2.score_for_last_answer is not None and res_turn2.score_for_last_answer >= 6
    assert len(res_turn2.identified_strengths) >= 1


