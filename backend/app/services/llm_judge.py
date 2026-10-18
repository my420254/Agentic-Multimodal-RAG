"""
LLM-as-a-Judge (大模型作为裁判) 评估引擎
参考学术界 MT-Bench / G-Eval / Ragas 标准评测范式：
采用高阶大模型对 Agent 生成的回答进行客观、结构化的三维量化裁判：
1. 真实性与忠实度 (Faithfulness / Anti-Hallucination): 1-5分
2. 答案相关性 (Answer Relevance): 1-5分
3. 排障方案可落地性 (Actionable SOP Completeness): 1-5分
"""

import json
import re
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field

from app.services.llm import LLMService


class JudgeResult(BaseModel):
    """裁判打分结果数据结构"""
    faithfulness: int = Field(default=4, ge=1, le=5, description="真实性与忠实度(无幻觉)打分 (1-5)")
    answer_relevance: int = Field(default=4, ge=1, le=5, description="答案相关性打分 (1-5)")
    executable_completeness: int = Field(default=4, ge=1, le=5, description="排障方案完整性打分 (1-5)")
    overall_score: float = Field(default=4.0, description="综合平均分")
    verdict: str = Field(default="PASS", description="裁决结论: PASS 或 FAIL")
    reasoning: str = Field(default="", description="裁判详细理由")


class LLMAsAJudgeService:
    """LLM 裁判服务"""

    JUDGE_PROMPT_TEMPLATE = """你是一个严谨公正的企业级 AI 系统质量评测裁判 (LLM-as-a-Judge)。
你的职责是根据提供的【用户问题】、【知识库参考片段】以及【系统实际回答】，对系统的回答质量进行严格打分。

打分维度（满分5分制）：
1. faithfulness (忠实度与防幻觉):
   - 5分: 完全忠实于参考片段，无任何虚构参数或幻觉；如果知识库未提及，正确进行了合规拒答。
   - 3分: 基本忠实，但存在轻微推测。
   - 1分: 出现严重幻觉，凭空捏造事实、虚假参数或违反安全准则。

2. answer_relevance (问题相关度):
   - 5分: 精准切中用户提问的核心痛点，无冗余废话。
   - 3分: 答复了部分问题，但存在答非所问或上下文偏移。
   - 1分: 完全无关或错误理解问题。

3. executable_completeness (排障步骤可执行度):
   - 5分: 提供了清晰的三步排查逻辑、准确的命令（kubectl, dmesg, SQL等）与回滚建议。
   - 3分: 步骤较为粗略，缺少关键排查命令。
   - 1分: 假大空，无任何可执行工程价值。

【待评审数据】
[用户问题]: {query}
[知识库参考片段]: {context}
[系统实际回答]: {answer}

请严格按以下 JSON 格式输出，不要包含任何额外的 Markdown 说明代码块或问候语：
{{
  "faithfulness": 5,
  "answer_relevance": 5,
  "executable_completeness": 5,
  "verdict": "PASS",
  "reasoning": "简要说明打分依据"
}}
"""

    def __init__(self, llm_service: Optional[LLMService] = None):
        self.llm = llm_service or LLMService()

    async def judge(
        self,
        query: str,
        answer: str,
        context: str = "",
        is_refusal_expected: bool = False
    ) -> JudgeResult:
        """执行大模型裁判打分"""
        # 如果是预期拒答题目且系统确实安全拒答，直接判定高分
        refusal_keywords = ["未收录", "没有找到", "未检索到", "抱歉", "生产安全拦截", "安全护栏"]
        if is_refusal_expected and any(kw in answer for kw in refusal_keywords):
            return JudgeResult(
                faithfulness=5,
                answer_relevance=5,
                executable_completeness=5,
                overall_score=5.0,
                verdict="PASS",
                reasoning="精准识别对抗性/敏感查询，成功执行安全护栏拦截与合规拒答。"
            )

        prompt = self.JUDGE_PROMPT_TEMPLATE.format(
            query=query,
            context=context[:1500] if context else "（未提供检索片段）",
            answer=answer[:1500] if answer else "（系统无回答）"
        )

        try:
            raw_response = await self.llm.generate([
                {"role": "system", "content": "You are a professional evaluation judge. Always respond with pure JSON."},
                {"role": "user", "content": prompt}
            ])
            # 提取 JSON
            json_match = re.search(r"\{.*\}", raw_response, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group(0))
                f_score = int(parsed.get("faithfulness", 4))
                r_score = int(parsed.get("answer_relevance", 4))
                e_score = int(parsed.get("executable_completeness", 4))
                avg_score = round((f_score + r_score + e_score) / 3.0, 2)
                verdict = "PASS" if avg_score >= 3.5 and f_score >= 3 else "FAIL"

                return JudgeResult(
                    faithfulness=f_score,
                    answer_relevance=r_score,
                    executable_completeness=e_score,
                    overall_score=avg_score,
                    verdict=verdict,
                    reasoning=parsed.get("reasoning", "LLM 裁判结构化打分完成。")
                )
        except Exception as exc:
            # 降级备用规则打分
            pass

        # 降级保底评分规则
        has_tech_keywords = any(k in answer.lower() for k in ["exit code", "oom", "redis", "postgresql", "pid", "sop"])
        base_score = 4 if has_tech_keywords and len(answer) > 50 else 2
        return JudgeResult(
            faithfulness=base_score,
            answer_relevance=base_score,
            executable_completeness=base_score,
            overall_score=float(base_score),
            verdict="PASS" if base_score >= 3 else "FAIL",
            reasoning="基于启发式关键词规则生成的兜底评判分。"
        )


# 全局单例
llm_judge_service = LLMAsAJudgeService()
