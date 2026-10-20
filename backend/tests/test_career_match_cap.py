"""求职域匹配的跨领域封顶测试（不联网）。"""

from app.services.career_matcher import career_matcher_service


def test_cross_domain_resume_is_capped_low():
    resume = """
    学前教育 / 行政管理本科。
    核心技能：幼儿保教、奥尔夫音乐、蒙台梭利教具、钢琴弹唱、儿童舞蹈编排。
    实习：幼儿园大班带班教师，负责 32 名幼儿的一日作息与家园沟通。
    """
    jd = "大模型 Agent 工程师：熟悉 Python、LangGraph、RAG、向量检索、Agent 工程。"
    metrics = career_matcher_service.calculate_match_metrics(resume, jd)
    assert metrics["match_level"] == "LOW"
    assert metrics["overall_match_score"] <= 45
    assert "python" in metrics["missing_skills"]


def test_matching_security_resume_is_not_capped():
    resume = """
    网络空间安全本科，熟练掌握 Python、Linux。
    熟悉 Prompt Injection、Jailbreak、护栏、RAG 安全评测、OWASP Top 10。
    """
    jd = "大模型安全工程师：熟悉 Prompt Injection、Jailbreak、护栏、Python 安全开发。"
    metrics = career_matcher_service.calculate_match_metrics(resume, jd)
    assert metrics["match_level"] in {"MATCHED", "HIGHLY_MATCHED"}
    assert metrics["overall_match_score"] >= 70
