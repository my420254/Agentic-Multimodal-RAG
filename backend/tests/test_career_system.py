"""
高校就业辅导与反欺诈 Agent 完整功能测试集
研发单位：辽宁大学 · 辽宁省公共舆情与网络安全信息系统重点实验室
"""

import uuid

import pytest
from httpx import AsyncClient
from app.main import app
from app.services.job_fraud_detector import job_fraud_detector, FraudRiskLevel
from app.services.career_matcher import career_matcher_service
from app.services.mock_interview import mock_interview_service
from app.core.rate_limiter import SlidingWindowRateLimiter


@pytest.mark.asyncio
async def test_job_fraud_detector_safe_jd():
    """测试正规真实招聘 JD 判定为 SAFE"""
    safe_jd = """
    岗位职责：
    1. 负责大模型 Agent 架构设计与开发，熟悉 LangGraph 与 FastAPI 异步服务；
    2. 参与 Hybrid RAG 检索管线调优，优化向量与全文混合检索召回率；
    3. 配合团队完成 Docker 容器化部署与微服务接口联调。
    岗位要求：
    计算机相关专业硕士及以上学历，熟悉 Python 与 Linux 常用命令，具备良好的团队沟通协作能力。
    """
    res = await job_fraud_detector.analyze(
        job_title="大模型研发实习生",
        company="某知名科技研发中心",
        job_description=safe_jd,
        deep_llm_audit=False
    )
    assert res.risk_level == FraudRiskLevel.SAFE
    assert res.is_fraudulent is False
    assert res.risk_score < 25
    assert len(res.safety_warnings) > 0


@pytest.mark.asyncio
async def test_job_fraud_detector_training_loan_trap():
    """测试典型转培训贷骗局识别（高危拦截）"""
    fraud_jd = """
    招聘初级软件开发工程师，不限专业无须经验，底薪 8000。
    入职前需统一参加为期 3 个月的定制化岗前实训，需缴纳实训费 19800 元，可办理学费分期实训贷款，
    承诺包就业，签订保过协议，培训费入职后从薪资中分期扣除。
    """
    res = await job_fraud_detector.analyze(
        job_title="初级开发储备干部",
        company="XX创新教育科技有限公司",
        job_description=fraud_jd,
        deep_llm_audit=False
    )
    assert res.risk_level in [FraudRiskLevel.SUSPICIOUS, FraudRiskLevel.HIGH_RISK]
    assert res.is_fraudulent is True
    assert "培训贷与套路转培陷阱" in res.detected_traps
    assert res.risk_score >= 35


@pytest.mark.asyncio
async def test_job_fraud_detector_cross_border_scam():
    """测试跨境涉诈高薪诱导陷阱识别（高危拦截）"""
    scam_jd = """
    高薪出海招聘境外客服，工作地点东南亚跨境园区，底薪 30k 起无门槛，
    包机票落地安排，需扣押护照统一管理，免签出境，入职即发万元安置津贴！
    """
    res = await job_fraud_detector.analyze(
        job_title="海外中文客服",
        company="海外国际商务互娱",
        job_description=scam_jd,
        deep_llm_audit=False
    )
    assert res.risk_level in [FraudRiskLevel.SUSPICIOUS, FraudRiskLevel.HIGH_RISK]
    assert res.is_fraudulent is True
    assert "跨境涉诈与灰产诱导" in res.detected_traps


@pytest.mark.asyncio
async def test_career_matcher_resume_section_parsing():
    """测试简历多模块语义分块与关键词识别"""
    sample_resume = """
    张同学 | 辽宁大学 | 硕士
    【专业技能】
    熟练掌握 Python, FastAPI, Go, Docker, Redis, Kafka, LangGraph, Hybrid RAG。
    【实习经历】
    广州省心购科技 - 大模型智能体研发实习生 (2026.07 - 2026.10)
    1. 基于 MCP 协议构建主从多智能体运行时；
    2. 基于 Kafka 构建异步事件驱动链路，时延缩减至 50ms。
    【核心项目经历】
    基于多模态 RAG 的高校求职辅导系统
    采用 PostgreSQL GIN + pgvector 进行混合检索，优化 Top-3 召回。
    【学术论文】
    面向长尾情感分析的轻量化微调框架，CCF 会议一作。
    """
    sections = career_matcher_service.parse_resume_sections(sample_resume)
    assert len(sections) >= 3
    section_types = [s.section_type for s in sections]
    assert "skills" in section_types or "experience" in section_types


@pytest.mark.asyncio
async def test_career_matcher_bidirectional_matching():
    """测试简历与岗位 JD 双向匹配计算、能力雷达与 STAR 重构"""
    sample_resume = """
    张梦洋 - 辽宁大学硕士
    技术栈：Python, FastAPI, Redis, Kafka, LangGraph, PostgreSQL, pgvector, Docker, LoRA.
    项目：构建 Agentic RAG 检索管线，使用 Redis 进行高并发限流，优化系统响应。
    """
    sample_jd = """
    岗位名称：大模型 Agent 架构师
    职责：
    1. 负责 LLM Agent 编排与多智能体系统落地；
    2. 深入掌握 Python, FastAPI, Redis 高并发缓存与限流保护；
    3. 精通 RAG 混合检索及 LangGraph 状态机。
    """
    result = await career_matcher_service.analyze_and_optimize(sample_resume, sample_jd)
    assert result.overall_match_score >= 60
    assert result.radar_chart.technical_depth > 0
    assert len(result.matched_skills) > 0
    assert len(result.star_optimizations) >= 1
    assert result.star_optimizations[0].situation != ""


@pytest.mark.asyncio
async def test_mock_interview_probing():
    """测试模拟面试追问"""
    # 测试模拟面试对话
    messages = [
        {"role": "user", "content": "面试官您好，我之前在实习中用 Redis 和 Lua 脚本做过滑动窗口限流。"}
    ]
    res = await mock_interview_service.chat(
        messages=messages,
        mode="mock_interview",
        target_role="高并发后端研发工程师",
        user_id=f"test_user_{uuid.uuid4().hex[:8]}",
    )
    assert res.role == "interviewer"
    assert res.score_for_last_answer is not None
    assert res.is_probing is True
    assert "追问" in res.reply_text or "深入" in res.reply_text or len(res.reply_text) > 20


def test_sliding_window_rate_limiter_limit():
    """测试滑动窗口限流器的阈值保护（不是 1000 QPS 压测）"""
    limiter = SlidingWindowRateLimiter(limit=10, window_seconds=0.5)
    passed_count = 0
    for _ in range(15):
        if limiter.is_allowed("test_client"):
            passed_count += 1
    # 限制阈值为 10，因此前 10 次成功，后 5 次应被拦截
    assert passed_count == 10


def test_career_api_endpoints(client, auth_headers):
    """测试 FastAPI Career 相关对外 REST 接口（W1 起必须带 access token）"""
    # 1. 虚假岗位检测接口
    fraud_resp = client.post(
        "/api/v1/career/fraud-check",
        json={
            "job_title": "储备实习生",
            "company": "测试机构",
            "job_description": "高薪入职，前三个月自费缴纳实训费 12000 元参加岗前技能提升。",
            "deep_audit": False
        },
        headers=auth_headers,
    )
    assert fraud_resp.status_code == 200
    fraud_data = fraud_resp.json()
    assert fraud_data["is_fraudulent"] is True

    # 2. 简历匹配接口
    match_resp = client.post(
        "/api/v1/career/match",
        json={
            "resume_text": "熟练掌握 Python, FastAPI, Docker, Redis",
            "jd_text": "要求熟练掌握 Python 和 Redis"
        },
        headers=auth_headers,
    )
    assert match_resp.status_code == 200
    match_data = match_resp.json()
    assert match_data["overall_match_score"] > 0
    assert "radar_chart" in match_data

    # 3. 面试对话接口
    interview_resp = client.post(
        "/api/v1/career/interview/chat",
        json={
            "messages": [{"role": "user", "content": "我对 FastAPI 异步机制比较熟悉。"}],
            "mode": "mock_interview",
            "target_role": "后端开发"
        },
        headers=auth_headers,
    )
    assert interview_resp.status_code == 200
    turn_data = interview_resp.json()
    assert turn_data["role"] == "interviewer"

    # 4. 提示词工坊接口
    prompts_resp = client.get("/api/v1/career/prompts", headers=auth_headers)
    assert prompts_resp.status_code == 200
    prompts_data = prompts_resp.json()
    assert "mock_interviewer" in prompts_data
    assert "resume_doctor" in prompts_data


def test_prompt_workshop_custom_update():
    """测试提示词工坊用户自定义修改与重置（按用户隔离）"""
    from app.services.prompt_service import prompt_workshop_service
    test_user = f"test_user_{uuid.uuid4().hex[:8]}"
    # 1. 更新提示词
    custom_content = "你是一个更加严肃的大厂 P9 面试官。"
    updated = prompt_workshop_service.update_template(
        test_user, "mock_interviewer", custom_content
    )
    assert updated.is_custom is True
    assert updated.system_prompt == custom_content

    # 2. 恢复默认
    reset_tpl = prompt_workshop_service.reset_template(test_user, "mock_interviewer")
    assert reset_tpl.is_custom is False
    assert "辽宁大学" in reset_tpl.system_prompt


@pytest.mark.asyncio
async def test_mock_interview_adaptive_fallback_on_unknown():
    """测试当候选人明确表示盲区或不了解时，系统自适应触发降维引导(PIVOT_FALLBACK)并记录盲区"""
    from app.services.mock_interview import mock_interview_service, ProbingAction
    res = await mock_interview_service.chat(
        messages=[
            {"role": "user", "content": "关于 Redis 缓存一致性和双写延迟，我在学校项目里没接触过，不太清楚底层细节。"}
        ],
        mode="mock_interview",
        target_role="高并发后端开发",
        user_id=f"test_user_{uuid.uuid4().hex[:8]}",
    )
    assert res.probing_action == ProbingAction.PIVOT_FALLBACK
    assert res.is_probing is True
    # 验证是否包含中肯鼓励引导语，绝不继续硬问 1000 QPS
    assert any(w in res.reply_text for w in ["没关系", "换一个", "基础", "考点", "角度"])
    assert len(res.identified_gaps) >= 1


@pytest.mark.asyncio
async def test_mock_interview_adaptive_advance_on_confident_answer():
    """测试当候选人回答明确且深入时，系统推进到深入工程或压测验证阶段"""
    from app.services.mock_interview import mock_interview_service, ProbingAction
    res = await mock_interview_service.chat(
        messages=[
            {"role": "user", "content": "我使用了 Redis ZSet 实现滑动窗口限流器，通过 Lua 脚本原子性执行 zremrangebyscore 和 zcard，有效避免了超卖。"}
        ],
        mode="mock_interview",
        target_role="高并发后端开发",
        user_id=f"test_user_{uuid.uuid4().hex[:8]}",
    )
    assert res.probing_action == ProbingAction.DEEP_PROBE
    assert res.score_for_last_answer is not None and res.score_for_last_answer >= 6
    assert len(res.identified_strengths) >= 1




