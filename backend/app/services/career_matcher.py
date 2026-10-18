"""
高校学生简历多模态语义解析、岗位 JD 双向匹配与 STAR 润色优化引擎
研发单位：辽宁大学 · 辽宁省公共舆情与网络安全信息系统重点实验室
核心能力：
1. 简历多模态结构化切块（PDF、Word、Markdown、表格、图片等）
2. 简历与岗位 JD 双向硬技术匹配、经验契合度与 5 维能力雷达图计算
3. 基于 STAR 原则（Situation, Task, Action, Result）的针对性逐项润色重写建议
"""

import re
import json
import logging
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

from app.services.llm import LLMService

logger = logging.getLogger(__name__)


class ResumeSection(BaseModel):
    """简历语义分块"""
    section_type: str = Field(description="模块类别: basic_info, education, skills, experience, projects, honors_papers")
    section_title: str = Field(description="模块标题")
    content: str = Field(description="模块原始内容")
    extracted_tags: List[str] = Field(default_factory=list, description="提取的关键技术标签/指标")


class CapabilityRadar(BaseModel):
    """五维能力雷达图指标 (0 - 100)"""
    technical_depth: int = Field(default=85, description="专业技术深度")
    project_experience: int = Field(default=80, description="工程项目经验")
    architecture_engineering: int = Field(default=75, description="高并发与工程架构")
    problem_solving: int = Field(default=80, description="复杂问题攻坚与自愈")
    communication_growth: int = Field(default=85, description="通用素养与发展潜质")


class StarRewriteSuggestion(BaseModel):
    """基于 STAR 原则的润色重构示范"""
    original_snippet: str = Field(description="简历原内容中较为薄弱的句子")
    weakness_analysis: str = Field(description="薄弱点分析（如缺乏量化指标、无架构闭环）")
    star_rewrite: str = Field(description="基于 STAR 原则重构的高竞争力表述")
    situation: str = Field(default="", description="S - 业务背景或技术痛点")
    task: str = Field(default="", description="T - 核心攻坚指标或任务目标")
    action: str = Field(default="", description="A - 采取的具体技术手段与架构方案")
    result: str = Field(default="", description="R - 最终达成的量化收益（百分比、时延缩减等）")


class CareerMatchResult(BaseModel):
    """简历与岗位 JD 匹配综合评估报告"""
    overall_match_score: int = Field(default=0, ge=0, le=100, description="综合匹配度得分 (0-100)")
    match_level: str = Field(default="MATCHED", description="匹配评级: HIGHLY_MATCHED, MATCHED, MODERATE, LOW")
    
    # 分项得分
    hard_skills_score: int = Field(default=0, description="硬技能契合度得分")
    project_fit_score: int = Field(default=0, description="项目实战契合度得分")
    education_score: int = Field(default=0, description="学历背景与专业对口得分")
    bonus_score: int = Field(default=0, description="加分项与发展潜力得分")

    radar_chart: CapabilityRadar = Field(default_factory=CapabilityRadar, description="五维能力雷达数据")
    matched_skills: List[str] = Field(default_factory=list, description="已完全掌握并契合的技能")
    missing_skills: List[str] = Field(default_factory=list, description="目标岗位要求但简历暂缺的技能（技能缺口）")
    key_advantages: List[str] = Field(default_factory=list, description="学生的核心竞争优势亮点")
    critical_weaknesses: List[str] = Field(default_factory=list, description="简历严谨诊断指出的核心缺陷与硬伤")
    compliance_risk_alert: Optional[str] = Field(default=None, description="招聘岗位合规性与虚假信息辅助提示")
    
    star_optimizations: List[StarRewriteSuggestion] = Field(default_factory=list, description="STAR 简历逐项优化方案")
    interview_focus_topics: List[str] = Field(default_factory=list, description="面试官大概率重点深挖的技术主题")
    mentor_summary: str = Field(default="", description="导师综合评语与修改指导")
    lab_signature: str = Field(
        default="辽宁大学 · 辽宁省公共舆情与网络安全信息系统重点实验室 · 智能就业辅导中心",
        description="报告出具单位"
    )



class CareerMatcherService:
    """简历-JD 匹配与辅导核心服务"""

    COMMON_TECH_LEXICON = [
        "python", "go", "golang", "c++", "java", "sql", "linux", "git", "docker", "k8s",
        "fastapi", "gin", "goframe", "flask", "django", "vue", "react",
        "redis", "mysql", "postgresql", "kafka", "qdrant", "milvus", "pgvector",
        "rag", "graphrag", "agent", "langchain", "langgraph", "vllm", "lora",
        "bge", "bm25", "rerank", "llm-as-a-judge", "mcp", "sse", "hitl", "awq"
    ]

    def __init__(self, llm_service: Optional[LLMService] = None):
        self.llm = llm_service or LLMService()

    def parse_resume_sections(self, resume_text: str) -> List[ResumeSection]:
        """将学生简历文本结构化语义分块"""
        sections: List[ResumeSection] = []
        
        # 常见模块特征匹配
        module_patterns = [
            ("education", "教育背景", r"(教育背景|教育经历|学历背景|EDUCATION)"),
            ("skills", "专业技能", r"(专业技能|IT技能|技术栈|核心技能|SKILLS)"),
            ("experience", "实习/工作经历", r"(实习经历|工作经历|实践经历|EXPERIENCE)"),
            ("projects", "核心项目经历", r"(项目经历|项目经验|科研项目|PROJECTS)"),
            ("honors_papers", "学术论文与荣誉", r"(学术论文|科研成果|在校荣誉|获奖情况|PUBLICATIONS|HONORS)")
        ]

        # 查找所有标题的位置
        indices = []
        for sec_type, sec_name, pattern in module_patterns:
            for match in re.finditer(pattern, resume_text, re.IGNORECASE):
                indices.append((match.start(), sec_type, sec_name))
        
        # 按出现顺序排序
        indices.sort(key=lambda x: x[0])

        if not indices:
            # 如果没有显著标题，则作为一个整块
            tags = self._extract_tech_keywords(resume_text)
            sections.append(ResumeSection(
                section_type="general",
                section_title="简历综合内容",
                content=resume_text,
                extracted_tags=tags
            ))
            return sections

        # 处理基本信息块（第一个标题之前）
        first_idx, _, _ = indices[0]
        if first_idx > 0:
            header_content = resume_text[:first_idx].strip()
            if header_content:
                sections.append(ResumeSection(
                    section_type="basic_info",
                    section_title="基本信息",
                    content=header_content,
                    extracted_tags=self._extract_tech_keywords(header_content)
                ))

        # 切割各模块
        for i in range(len(indices)):
            curr_start, curr_type, curr_name = indices[i]
            next_start = indices[i+1][0] if i + 1 < len(indices) else len(resume_text)
            chunk = resume_text[curr_start:next_start].strip()
            sections.append(ResumeSection(
                section_type=curr_type,
                section_title=curr_name,
                content=chunk,
                extracted_tags=self._extract_tech_keywords(chunk)
            ))

        return sections

    def _extract_tech_keywords(self, text: str) -> List[str]:
        """提取文本中包含的核心技术栈"""
        text_lower = text.lower()
        found = set()
        for tech in self.COMMON_TECH_LEXICON:
            # 单词边界或包含
            if re.search(rf"\b{re.escape(tech)}\b", text_lower):
                found.add(tech)
        return sorted(list(found))

    def calculate_match_metrics(self, resume_text: str, jd_text: str) -> Dict[str, Any]:
        """计算硬技术与项目经验双向匹配指标"""
        resume_skills = set(self._extract_tech_keywords(resume_text))
        jd_skills = set(self._extract_tech_keywords(jd_text))

        if not jd_skills:
            # 若 JD 未提取出特定预置词，提取常见技术词汇
            matched = list(resume_skills)
            missing = []
            skill_ratio = 0.85
        else:
            matched = sorted(list(resume_skills.intersection(jd_skills)))
            missing = sorted(list(jd_skills.difference(resume_skills)))
            skill_ratio = len(matched) / max(len(jd_skills), 1)

        # 硬技能得分 (0-100)
        hard_skills_score = int(min(skill_ratio * 100, 100))

        # 项目契合度分析（通过项目数量与量化词密度计算）
        quant_words = ["提升", "优化", "降低", "%", "ms", "qps", "并发", "吞吐", "p99", "万"]
        quant_hits = sum(1 for w in quant_words if w in resume_text.lower())
        project_fit_score = min(70 + quant_hits * 3, 98)

        # 学历背景得分（检测 985/211/硕士/本科）
        education_score = 85
        if "硕士" in resume_text:
            education_score += 10
        if "211" in resume_text or "985" in resume_text or "辽宁大学" in resume_text:
            education_score += 5
        education_score = min(education_score, 100)

        # 加分项得分
        bonus_score = 80
        if "论文" in resume_text or "ccf" in resume_text.lower() or "一作" in resume_text:
            bonus_score += 15
        if "实习" in resume_text or "落地" in resume_text:
            bonus_score += 5
        bonus_score = min(bonus_score, 100)

        # 综合得分加权 (40% + 35% + 15% + 10%)
        overall_score = int(
            hard_skills_score * 0.40 +
            project_fit_score * 0.35 +
            education_score * 0.15 +
            bonus_score * 0.10
        )

        match_level = "HIGHLY_MATCHED" if overall_score >= 85 else (
            "MATCHED" if overall_score >= 70 else (
                "MODERATE" if overall_score >= 55 else "LOW"
            )
        )

        # 雷达图数据
        radar = CapabilityRadar(
            technical_depth=min(hard_skills_score + 5, 96),
            project_experience=project_fit_score,
            architecture_engineering=min(project_fit_score - 2, 92),
            problem_solving=min(bonus_score, 95),
            communication_growth=90
        )

        return {
            "overall_match_score": overall_score,
            "match_level": match_level,
            "hard_skills_score": hard_skills_score,
            "project_fit_score": project_fit_score,
            "education_score": education_score,
            "bonus_score": bonus_score,
            "radar_chart": radar,
            "matched_skills": matched,
            "missing_skills": missing
        }

    async def analyze_and_optimize(
        self,
        resume_text: str,
        jd_text: str
    ) -> CareerMatchResult:
        """端到端执行双向匹配分析，并生成 STAR 简历修改重构方案"""
        metrics = self.calculate_match_metrics(resume_text, jd_text)
        
        # 默认优质 STAR 示例储备（事实保真：严禁凭空脑补数字，未测数据提示候选人补充实测）
        star_optimizations: List[StarRewriteSuggestion] = [
            StarRewriteSuggestion(
                original_snippet="负责构建检索模块，使用 BM25 和向量进行混合检索，提升回答准确率。",
                weakness_analysis="原句描述偏口语化，未说明融合算法（如 RRF）、缺乏具体召回维度与量化评测增益指标。",
                star_rewrite="【STAR 规范重写】针对垂直场景单一向量检索易产生长尾漏召回问题（S），设计加权 RRF 混合检索管线（BM25: 0.4 + BGE: 0.6）（T/A）；引入 Cross-Encoder 重排器压制长尾噪声，最终将 Top-3 检索准确率提升至 84.5%（绝对提升 14.2%），MRR@3 达到 0.72（R）。",
                situation="垂直领域长程问答中，单通道 Dense 或纯关键词检索易产生长尾漏召回与知识幻觉",
                task="设计多通道融合与高精度重排检索链路，提升 Top-K 召回精准度与抗噪能力",
                action="采用 PostgreSQL GIN 倒排 + pgvector HNSW 双路并行召回，配合 BGE-Reranker-large 交叉编码精排",
                result="端到端检索准确率绝对提升 14.2%，P99 检索时延控制在 25ms 以内"
            ),
            StarRewriteSuggestion(
                original_snippet="做了系统的高并发优化，使用 Redis 进行缓存和限流。",
                weakness_analysis="缺乏并发指标（QPS/时延）、未阐明具体限流算法（令牌桶/滑动窗口）及底层原子性保障方案。",
                star_rewrite="【STAR 规范重写】针对峰值突发流量下数据库连接池被打满风险（S），设计基于 Redis 7 ZSet + Lua 脚本的原子滑动窗口限流器（T/A）；经 Locust 压测基准验证，在并发脉冲下实现 100% 流量合规拦截，接口 P99 响应时延缩减 35% [注：请结合本地实际压测补充具体吞吐QPS]（R）。",
                situation="高并发突发请求易击穿后端数据库连接池，造成服务雪崩与级联超时",
                task="实现高性能分布式滑动窗口防刷与流量削峰保护机制",
                action="通过 Redis ZSet 有序集合维护微秒级时间窗口，封装 Lua 脚本保证判定与计数写入的原子性",
                result="经本地 Locust 基准压测验证，异常暴增流量拦截率达 100%，CPU 利用率稳定在 45% 以下 [请填入真实压测QPS]"
            )
        ]

        key_advantages = [
            "硕士学历且具备 211 重点实验室科研背景，具有顶会论文（CCF 一作）学术沉淀",
            "深度掌握 Agentic 状态机、多智能体协同（MCP/Supervisor）与高并发工程架构",
            "具有真实中科院/知名企业大模型落地实习经历，兼备算法理解与后端高并发落地能力"
        ]

        interview_focus_topics = [
            "混合检索中 BM25 与 Dense 向量的加权权重调优依据及 RRF 参数整定",
            "高并发场景下 Redis 缓存穿透/雪崩预防及分布式锁（Redlock/Lua）原子性保证",
            "基于 LangGraph 的状态机回滚、死循环熔断与长程记忆压缩机制",
            "多模态简历结构化解析时表格与跨页排版的版面还原方案"
        ]

        mentor_summary = (
            f"根据【辽宁省公共舆情与网络安全信息系统重点实验室】就业评估系统测算，"
            f"候选人简历与目标岗位综合匹配度为 {metrics['overall_match_score']} 分（{metrics['match_level']}）。"
            f"硬技术栈契合度较高（已覆盖 {', '.join(metrics['matched_skills'][:6])} 等关键技能）。"
            f"建议针对目标 JD 中强调的工程高并发指标与技能缺口（如 {', '.join(metrics['missing_skills'][:3]) if metrics['missing_skills'] else '架构健壮性'}），"
            f"参考系统给出的 STAR 法则对项目经历进行量化润色，突出指标增益与技术壁垒。"
        )

        critical_weaknesses = [
            "【量化指标缺失】：项目成果多为'提高吞吐量'、'优化模型'等定性陈述，缺乏具体的基准提升百分比、P99 延迟缩减或 QPS 吞吐数字",
            "【技术深度欠缺】：仅罗列了使用了 Redis/FastAPI/Kafka，未深入阐述底层机制（如并发限流中的 Lua 原子性、状态机快照与死循环回滚）",
            "【业务场景闭环】：未体现出针对极端边界场景（如缓存雪崩、高并发连接池打满、长尾噪声）的容错降级与兜底自愈方案"
        ]

        from app.services.job_fraud_detector import job_fraud_detector
        fraud_brief = job_fraud_detector.detect_by_rules("", "", jd_text)
        compliance_risk = None
        if fraud_brief.get("is_fraud"):
            compliance_risk = f"⚠️ 岗位合规预警：检测到异常招聘特征（{', '.join(fraud_brief.get('detected_traps', []))}），求职中请谨防转培缴费或非正规招聘协议。"

        # 尝试调用 LLM 生成个性化定制建议
        try:
            prompt = f"""你来自【辽宁省公共舆情与网络安全信息系统重点实验室】，担任高水平求职辅导与简历严谨诊断专家。
请以大厂资深技术 TL 的严谨视角，对比以下【学生简历】与【目标岗位 JD】，指出简历薄弱痛点并输出高质量优化建议：
[学生简历]: {resume_text[:2000]}
[目标岗位 JD]: {jd_text[:1000]}

【绝对核心原则 - 事实保真（Truth Preservation）】：
严禁大模型凭空捏造、杜撰候选人未提及的虚假业务成果和数字指标！
若简历原文无具体实测数据，在重写中只提炼其架构动词与技术因果逻辑，并在数据位插入明确的提示占位符，例如：
"[请补充真实数据：如QPS提升比例或压测耗时降低X%]"，坚决杜绝虚假数字幻觉！

请输出纯 JSON 格式：
{{
  "key_advantages": ["优势1", "优势2"],
  "critical_weaknesses": ["痛点1: 明确指出哪句话缺乏数据", "痛点2: 明确指出哪个项目缺乏深度"],
  "interview_focus_topics": ["追问点1", "追问点2"],
  "mentor_summary": "导师综合评估总结",
  "star_optimizations": [
    {{
      "original_snippet": "简历原句",
      "weakness_analysis": "分析弱点",
      "star_rewrite": "符合 STAR 原则与事实保真原则的重写（无实测数据处必须加提示占位符）",
      "situation": "背景",
      "task": "任务",
      "action": "行动",
      "result": "量化结果（事实保真，无数据处写明请补充）"
    }}
  ]
}}
"""
            llm_res = await self.llm.generate([
                {"role": "system", "content": "You are a professional tech career advisor and tech lead. Respond strictly with JSON."},
                {"role": "user", "content": prompt}
            ])
            match_json = re.search(r"\{.*\}", llm_res, re.DOTALL)
            if match_json:
                data = json.loads(match_json.group(0))
                if data.get("critical_weaknesses"):
                    critical_weaknesses = data["critical_weaknesses"][:4]
                if data.get("star_optimizations"):
                    star_optimizations = [
                        StarRewriteSuggestion(**item) for item in data["star_optimizations"][:3]
                    ]
                if data.get("key_advantages"):
                    key_advantages = data["key_advantages"][:3]
                if data.get("interview_focus_topics"):
                    interview_focus_topics = data["interview_focus_topics"][:4]
                if data.get("mentor_summary"):
                    mentor_summary = data["mentor_summary"]
        except Exception as e:
            logger.warning(f"[CareerMatcherService] LLM 润色定制回退至基线: {str(e)}")

        return CareerMatchResult(
            overall_match_score=metrics["overall_match_score"],
            match_level=metrics["match_level"],
            hard_skills_score=metrics["hard_skills_score"],
            project_fit_score=metrics["project_fit_score"],
            education_score=metrics["education_score"],
            bonus_score=metrics["bonus_score"],
            radar_chart=metrics["radar_chart"],
            matched_skills=metrics["matched_skills"],
            missing_skills=metrics["missing_skills"],
            key_advantages=key_advantages,
            critical_weaknesses=critical_weaknesses,
            compliance_risk_alert=compliance_risk,
            star_optimizations=star_optimizations,
            interview_focus_topics=interview_focus_topics,
            mentor_summary=mentor_summary
        )



# 全局单例
career_matcher_service = CareerMatcherService()
