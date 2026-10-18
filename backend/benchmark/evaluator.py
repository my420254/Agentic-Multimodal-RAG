"""
Agent 评测核心评分引擎 (Evaluator)
覆盖：
1. 结果层：任务完成率、命中率 (Hit Rate)、答案准确率、幻觉率
2. 过程层：意图识别准确率、工具调用合规率、步骤数、死循环发生率
3. 成本层：端到端延迟 (Latency)、Token 消耗预估
"""

import re
from typing import Dict, Any, List

class AgentEvaluator:
    """自动化评估器"""

    REFUSAL_PATTERNS = [
        r"未(?:检索|查询|提及|记录|找到)",
        r"没有(?:提供|记录|找到|提及|相关)",
        r"抱歉.*无法",
        r"知识库.*(?:未包含|不存在|没有)",
        r"我不知道",
        r"查无此",
        r"暂未有",
        r"无法提供"
    ]

    @classmethod
    def evaluate_turn(
        cls,
        test_case: Dict[str, Any],
        actual_output: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        对单次 Agent 运行结果进行全维度量化打分
        """
        category = test_case.get("category")
        expected_intent = test_case.get("expected_intent", "qa")
        expected_keywords = test_case.get("expected_keywords", [])
        expected_refusal = test_case.get("expected_refusal", test_case.get("refusal_required", False))
        
        # 实际 Agent 输出数据
        answer = actual_output.get("answer", "")
        intent = actual_output.get("intent", "qa")
        citations = actual_output.get("citations", [])
        steps = actual_output.get("agent_steps", [])
        latency = actual_output.get("latency", 0.0)
        
        # 1. 意图识别准确率
        intent_match = (intent == expected_intent)

        # 2. 检索命中评估 (Hit@K)
        retrieved_text = " ".join([c.get("content", "") for c in citations])
        keyword_hits = 0
        if expected_keywords:
            for kw in expected_keywords:
                # 忽略大小写检查
                if kw.lower() in retrieved_text.lower() or kw.lower() in answer.lower():
                    keyword_hits += 1
            hit_ratio = keyword_hits / len(expected_keywords)
        else:
            hit_ratio = 1.0 if not test_case.get("should_retrieve", True) else 0.0

        # 3. 对抗与防幻觉评分 (拒答判断)
        is_refusal = False
        for pat in cls.REFUSAL_PATTERNS:
            if re.search(pat, answer):
                is_refusal = True
                break

        if expected_refusal:
            # 预期应当拒答
            hallucination_detected = not is_refusal
            task_success = is_refusal
        else:
            hallucination_detected = False
            if expected_intent == "chat":
                # 闲聊只要意图正确且有回答即可
                task_success = (intent == "chat" and len(answer.strip()) > 0)
            else:
                # QA 需关键词命中率 >= 0.5 且不被错误拒答
                task_success = (hit_ratio >= 0.5 and not is_refusal)

        # 4. 过程层与死循环评估
        tool_action_steps = [s for s in steps if s.get("step") == "action"]
        tool_call_count = len(tool_action_steps)
        
        # 检查是否有连续重复调用
        loop_detected = False
        action_contents = [s.get("content", "") for s in tool_action_steps]
        for i in range(1, len(action_contents)):
            if action_contents[i] == action_contents[i - 1]:
                loop_detected = True
                break

        # 5. Token 消耗预估
        prompt_chars = len(test_case.get("query", "")) + sum([len(c.get("content", "")) for c in citations])
        ans_chars = len(answer)
        est_tokens = int(prompt_chars * 0.75 + ans_chars * 1.2)

        return {
            "case_id": test_case.get("id"),
            "category": category,
            "task_success": task_success,
            "intent_match": intent_match,
            "hit_ratio": hit_ratio,
            "hallucination_detected": hallucination_detected,
            "is_refusal": is_refusal,
            "tool_call_count": tool_call_count,
            "total_steps": len(steps),
            "loop_detected": loop_detected,
            "latency": latency,
            "est_tokens": est_tokens,
            "answer_preview": answer[:120] + ("..." if len(answer) > 120 else "")
        }
