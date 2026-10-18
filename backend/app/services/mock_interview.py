"""
智能模拟面试服务
研发单位：辽宁大学 · 辽宁省公共舆情与网络安全信息系统重点实验室
核心能力：
1. 基于简历与上一轮回答进行 4 阶递进追问 (Probing Questioning)
2. 支持学生/导师自定义配置面试官 Prompt
3. 交互式实时打分复盘与递进追问
"""

import re
import json
import logging
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

from sqlmodel import Session

from app.core.database import engine
from app.models import FileDocument
from app.services.embedding import EmbeddingService
from app.services.llm import LLMService
from app.services.prompt_service import prompt_workshop_service
from app.services.retrieval import RetrievalService
from app.services.vector_store import VectorStoreService

logger = logging.getLogger(__name__)


from enum import Enum

class ProbingStage(str, Enum):
    """追问阶梯阶段定义"""
    STAGE_1_DESIGN_MOTIVATION = "STAGE_1_DESIGN_MOTIVATION"       # 选型动机与项目事实
    STAGE_2_CORE_MECHANISM = "STAGE_2_CORE_MECHANISM"             # 核心原理与底层机制
    STAGE_3_ENGINEERING_BOUNDARY = "STAGE_3_ENGINEERING_BOUNDARY" # 生产极端边界与高并发容错
    STAGE_4_EVIDENCE_QUANTIFICATION = "STAGE_4_EVIDENCE_QUANTIFICATION" # 量化指标与压测收益
    STAGE_WRAPUP = "STAGE_WRAPUP"                                 # 面试收敛复盘


class ProbingAction(str, Enum):
    """自适应追问动作决策"""
    DEEP_PROBE = "DEEP_PROBE"         # 纵向深入追问（推进到下一阶或深挖）
    PIVOT_FALLBACK = "PIVOT_FALLBACK" # 横向概念降维（候选人表示不会/答错，主动降低难度引导并记录盲区）
    WRAPUP = "WRAPUP"                 # 完成考察阶段，收敛复盘


class InterviewTurnResponse(BaseModel):
    """面试/闲聊单轮应答"""
    role: str = "interviewer"
    interviewer_persona: str = Field(
        default="大厂资深架构师 · 技术主考官",
        description="面试考官设定"
    )
    reply_text: str = Field(description="考官或导师回答内容")
    is_probing: bool = Field(default=False, description="是否属于技能深度递进追问")
    current_stage: ProbingStage = Field(
        default=ProbingStage.STAGE_1_DESIGN_MOTIVATION,
        description="当前考察阶梯阶段"
    )
    probing_action: ProbingAction = Field(
        default=ProbingAction.DEEP_PROBE,
        description="自适应决策动作: DEEP_PROBE 纵向深入 / PIVOT_FALLBACK 降维引导 / WRAPUP 收敛"
    )
    current_skill_focus: Optional[str] = Field(default=None, description="当前探测的核心技能节点")
    score_for_last_answer: Optional[int] = Field(default=None, ge=1, le=10, description="对学生上一轮回答的评分(1-10)")
    feedback: Optional[str] = Field(default=None, description="针对学生上一轮回答的优点与不足分析")
    identified_gaps: List[str] = Field(default_factory=list, description="本次追问识别出的技术薄弱点与盲区")
    identified_strengths: List[str] = Field(default_factory=list, description="本次追问识别出的技术亮点与深度体现")
    grounding_citations: List[Dict[str, Any]] = Field(default_factory=list, description="本轮出题实际引用的简历材料 chunk")
    grounding_available: bool = Field(default=False, description="本轮是否检索到可用于出题的简历材料")
    recommended_reading: List[str] = Field(default_factory=list, description="技术补强推荐阅读")


class MockInterviewService:
    """智能模拟面试与求职辅导核心服务"""

    UNKNOWN_PATTERNS = [
        "没接触过", "不了解", "不太清楚", "没做过", "不会", "不太懂",
        "没有深入研究", "忘了", "不熟悉", "没搞过", "还没学到", "不太确定"
    ]

    def __init__(self, llm_service: Optional[LLMService] = None):
        self.llm = llm_service or LLMService()

    def _determine_stage(self, turn_count: int, is_fallback: bool = False) -> ProbingStage:
        """根据会话轮次与当前状态计算建议考察阶梯"""
        if is_fallback:
            return ProbingStage.STAGE_2_CORE_MECHANISM
        if turn_count <= 1:
            return ProbingStage.STAGE_1_DESIGN_MOTIVATION
        elif turn_count == 2:
            return ProbingStage.STAGE_2_CORE_MECHANISM
        elif turn_count == 3:
            return ProbingStage.STAGE_3_ENGINEERING_BOUNDARY
        elif turn_count == 4:
            return ProbingStage.STAGE_4_EVIDENCE_QUANTIFICATION
        else:
            return ProbingStage.STAGE_WRAPUP

    async def chat(
        self,
        messages: List[Dict[str, str]],
        mode: str = "mock_interview",  # 仅支持 mock_interview
        target_role: str = "AI Agent / 高并发研发工程师",
        resume_summary: str = "",
        custom_prompt: Optional[str] = None,
        *,
        user_id: str,
        kb_ids: Optional[List[str]] = None,
        resume_file_id: Optional[str] = None,
    ) -> InterviewTurnResponse:
        """多轮模拟面试（提示词按 user_id 隔离）"""
        if not isinstance(user_id, str) or not user_id.strip():
            raise ValueError("user_id is required and must come from the authenticated token")
        if mode != "mock_interview":
            raise ValueError("仅支持 mock_interview 模式；心理疏导请使用智能对话")

        last_user_msg = messages[-1]["content"] if messages else "老师好，我准备好了。"
        user_turn_count = len([m for m in messages if m.get("role") == "user"])

        # 0. 先检索简历/项目材料，再出题；resume_file_id 用于锁定一份简历
        grounding_context = ""
        grounding_citations: List[Dict[str, Any]] = []
        if kb_ids:
            try:
                query_text = f"{target_role} {last_user_msg}"[:500]
                results: List[Dict[str, Any]] = []
                with Session(engine) as session:
                    if resume_file_id:
                        file_doc = session.get(FileDocument, resume_file_id)
                        if file_doc and file_doc.kb_id in kb_ids:
                            query_vector = await EmbeddingService().embed_query(query_text)
                            results = VectorStoreService().query_pgvector(
                                session, file_doc.kb_id, query_vector,
                                top_k=4, file_id=resume_file_id,
                            )
                            for r in results:
                                r["file_name"] = file_doc.name
                                r["location_info"] = f"第 {r.get('metadata', {}).get('page_number') or 1} 页"
                    if not results:
                        results, _ = await RetrievalService().search(
                            session,
                            query=query_text,
                            kb_ids=kb_ids,
                            search_mode="hybrid",
                            top_k=4,
                            use_cache=False,
                            log_retrieval=False,
                        )
                for idx, r in enumerate(results, 1):
                    content = (r.get("content") or "").strip()
                    if not content:
                        continue
                    citation = {
                        "chunk_id": r.get("id"),
                        "file_name": r.get("file_name") or "简历材料",
                        "location": r.get("location_info") or "",
                        "score": round(float(r.get("score") or 0), 4),
                        "content": content[:500],
                    }
                    grounding_citations.append(citation)
                    grounding_context += (
                        f"[{idx}] {citation['file_name']} | {citation['location']}\n"
                        f"{content[:700]}\n\n"
                    )
            except Exception as e:
                logger.warning(f"[MockInterviewService] 简历检索失败，降级为无材料出题: {e}")

        if not grounding_context:
            grounding_context = "（本轮未检索到简历/项目材料；不要编造候选人经历，只问岗位通用问题。）"
        grounding_available = bool(grounding_citations)

        # 1. 技术模拟面试模式 (4 阶状态机)
        current_focus = target_role or "高并发架构"

        # 判断用户是否明确表示不会 / 盲区
        is_unknown_signal = any(p in last_user_msg for p in self.UNKNOWN_PATTERNS)
        target_stage = self._determine_stage(user_turn_count, is_fallback=is_unknown_signal)

        # 构建具备自适应分支规则的 System Prompt
        stage_guidance = f"""当前建议阶段：{target_stage.value}
自适应原则要求：
1. 若候选人明确表示“不了解/没做过/不会”或表现出知识断层（触发盲区信号：{is_unknown_signal}）：
   - 【严禁继续硬问高阶工程极限场景或压测指标】；
   - 动作设为 PIVOT_FALLBACK；
   - 态度中肯鼓励：“没关系，这块属于进阶考点”，主动执行【横向概念降维】，降低难度询问该技术的前置基础原理或关联基础机制；
   - 在 identified_gaps 中如实记录盲区。
2. 若候选人回答逻辑清晰、原理扎实（score >= 8）：
   - 动作设为 DEEP_PROBE；
   - 顺着阶段阶梯纵向推进（选型设计 -> 底层核心原理 -> 生产极端容错 -> 量化复盘与压测）；
   - 在 identified_strengths 中如实记录亮点。
3. 若会话轮次已较深入（turn >= 4）或已覆盖关键考点：
   - 动作可设为 WRAPUP，进行本次技术考察阶段小结。
4. 【材料约束】：只能基于本轮材料中出现的经历出题；材料没有的经历不要问；下一问至少引用一个材料技术点，并在 grounding_chunk_ids 中列出 chunk id。"""

        if custom_prompt and custom_prompt.strip():
            system_prompt = (
                f"{custom_prompt}\n\n【本轮检索到的简历/项目材料】\n{grounding_context}\n"
                f"\n【状态机自适应指导】:\n{stage_guidance}"
            )
        else:
            tpl = prompt_workshop_service.get_template(user_id, "mock_interviewer")
            base_prompt = prompt_workshop_service.format_prompt(
                user_id,
                "mock_interviewer",
                target_role=target_role,
                resume_summary=resume_summary or "熟练掌握 Agent 状态机、Hybrid RAG、FastAPI 高并发与 Redis 缓存治理",
                student_answer=last_user_msg,
                retrieved_context=grounding_context,
            )
            # 自定义旧模板可能没有 {retrieved_context}，追加一次，避免材料约束丢失
            if not tpl or "{retrieved_context}" not in tpl.system_prompt:
                base_prompt += f"\n\n【本轮检索到的简历/项目材料】\n{grounding_context}"
            system_prompt = f"{base_prompt}\n\n【状态机自适应指导】:\n{stage_guidance}"

        try:
            raw_res = await self.llm.generate([
                {
                    "role": "system",
                    "content": "You are an elite tech interviewer at a top tech lab. Strictly respond with pure JSON conforming to schema: {score: int, feedback: str, reply_text: str, is_probing: bool, current_stage: str, probing_action: str, current_skill_focus: str, identified_gaps: list, identified_strengths: list, recommended_reading: list}."
                },
                {
                    "role": "user",
                    "content": f"系统提示要求与候选人背景：\n{system_prompt}\n\n请针对候选人最新回答进行自适应点评、打分与下一步追问：\n候选人回答：{last_user_msg}"
                }
            ])
            match = re.search(r"\{.*\}", raw_res, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                cited_ids = set(data.get("grounding_chunk_ids") or [])
                if cited_ids:
                    selected = [c for c in grounding_citations if c.get("chunk_id") in cited_ids]
                    if selected:
                        grounding_citations = selected
                # 解析 action
                raw_action = data.get("probing_action", "DEEP_PROBE")
                action = ProbingAction.PIVOT_FALLBACK if (is_unknown_signal or raw_action == "PIVOT_FALLBACK") else ProbingAction.DEEP_PROBE
                stage_str = data.get("current_stage", target_stage.value)
                try:
                    stage = ProbingStage(stage_str)
                except Exception:
                    stage = target_stage

                score = int(data.get("score", 5 if is_unknown_signal else 8))
                gaps = data.get("identified_gaps", [])
                if is_unknown_signal and not gaps:
                    gaps.append(f"{current_focus} 进阶工程机制")

                strengths = data.get("identified_strengths", [])
                if score >= 8 and not strengths:
                    strengths.append(f"{current_focus} 基础原理表述扎实")

                return InterviewTurnResponse(
                    role="interviewer",
                    interviewer_persona="大厂资深架构师 · 技术主考官",
                    reply_text=data.get("reply_text", "你的回答逻辑很清晰。"),
                    is_probing=data.get("is_probing", True),
                    current_stage=stage,
                    probing_action=action,
                    current_skill_focus=data.get("current_skill_focus", current_focus),
                    score_for_last_answer=score,
                    feedback=data.get("feedback", "技术概念阐述准确，若能结合容错与度量指标将更具说服力。"),
                    identified_gaps=gaps,
                    identified_strengths=strengths,
                    grounding_citations=grounding_citations,
                    grounding_available=grounding_available,
                    recommended_reading=data.get("recommended_reading", ["《高性能系统架构设计》", "《分布式技术原理与实战》"])
                )
        except Exception as e:
            logger.warning(f"[MockInterviewService] 面试官 LLM 异常回退: {str(e)}")

        # 降级备用分支（严格遵循状态机自适应分支）
        if is_unknown_signal:
            return InterviewTurnResponse(
                role="interviewer",
                interviewer_persona="大厂资深架构师 · 技术主考官",
                reply_text=f"没关系，【{current_focus}】的这一进阶容错场景在校招中确实偏向拔高考点。那我们换一个更基础、贴近工程落地的角度：你能先聊聊你在项目中是如何搭建其基础服务、以及最常用的核心数据结构或配置参数吗？",
                is_probing=True,
                current_stage=ProbingStage.STAGE_2_CORE_MECHANISM,
                probing_action=ProbingAction.PIVOT_FALLBACK,
                current_skill_focus=current_focus,
                score_for_last_answer=5,
                feedback="坦诚认知自己的技术边界是成熟工程师的良好素质；建议在复盘中重点强化该组件的高并发进阶机制。",
                identified_gaps=[f"{current_focus} 进阶故障容错与极端场景治理"],
                identified_strengths=[],
                grounding_citations=grounding_citations,
                grounding_available=grounding_available,
                recommended_reading=["《技术核心原理深度剖析》", "《高频技术面试高分答题指南》"]
            )
        else:
            return InterviewTurnResponse(
                role="interviewer",
                interviewer_persona="大厂资深架构师 · 技术主考官",
                reply_text=f"刚才你谈到了【{current_focus}】的实现机制。根据大厂核心能力考核标准，我们推进到工程验证层面：在实际项目中，你当时是如何对该功能进行边界测试或压测验证的？遇到了哪些潜在的性能瓶颈？",
                is_probing=True,
                current_stage=target_stage,
                probing_action=ProbingAction.DEEP_PROBE,
                current_skill_focus=current_focus,
                score_for_last_answer=8,
                feedback="基础原理阐述清晰，若能在后续回答中突出量化压测数据与边界保护机制，会更具竞争力。",
                identified_gaps=[],
                identified_strengths=[f"{current_focus} 核心选型与机制理解准确"],
                recommended_reading=["《大模型 RAG 工业级落地实践》", "《高并发系统限流与降级设计》"]
            )


# 全局单例
mock_interview_service = MockInterviewService()
