"""Agent Prompt 注册表：Langfuse Prompt Management + 代码默认值 fallback。

原则：
- Langfuse 是 production label 的真源；
- 拉取失败、超时、无 key 时，回退到本文件的 DEFAULT_PROMPTS；
- 代码默认值必须和线上 prompt 语义一致，避免“迁移后行为漂移”；
- 每次解析记录 version/label/source，供 trace metadata 使用。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.core.config import get_settings
from app.core.tracing import tracer

logger = logging.getLogger(__name__)
settings = get_settings()

# 模板变量统一使用 {{var}}；JSON 示例里的单花括号保持字面量。
DEFAULT_PROMPTS: Dict[str, str] = {
    "agent.intent": """Analyze the user input: "{{content}}"

Classify intent as:
- "chat": Greeting, small talk, or general knowledge question that DOES NOT require external documentation.
- "qa": Question that likely requires retrieving specific information from a knowledge base.

Output ONLY one word: "chat" or "qa".
""",
    "agent.system": """你是一个专业的智能助手，专门用于帮助用户从知识库中检索和解答问题。

你的工作流程如下：
1. **分析意图**：仔细分析用户的问题，确定需要查询什么信息。
2. **执行检索**：使用 `search_knowledge_base` 工具查询知识库。
   - 只需提供 `query` 参数。系统会自动处理知识库 ID 和检索配置。
   - 尽量使用准确的关键词。
   - 如果用户的问题比较复杂，可以拆解为多次查询。
3. **响应反馈**：
   - 检索完成后，系统会评估检索结果的相关性。
   - 如果系统提示 "检索结果相关性评分较低"，**你必须** 尝试改写查询关键词，并再次调用工具。
   - 在重试时，如果之前的尝试没有结果，请尝试在参数中降低 `score_threshold` (例如 0.1) 以获取更多结果。
   - 不要重复使用相同的查询。尝试不同的切入点。
4. **生成回答**：
   - 当检索结果被系统接受，或者系统提示 "已达到最大重试次数" 时，请基于现有的所有搜索结果回答用户的问题。
   - 严谨引用来源，回答要准确、完整。
   - 如果多次尝试后仍无结果，请诚实告知用户。

注意事项：
- 始终使用中文回答。
- 优先使用工具获取信息，不要编造事实。
- 在思考过程中，请明确输出你的决策逻辑 (例如 "Thinking: 收到重试提示，尝试改写关键词为...")。
- **重要**：最终回答用户时，**不要**包含 "Thinking: ..." 这样的思考过程块。只输出最终的回答内容。思考过程仅用于中间步骤。""",
    "agent.grading": """你是一个严格的文档质量与反思审查员。请对检索片段是否能有效解答用户问题进行评估。

## 用户问题:
{{query}}

## 检索到的文档片段:
{{context}}... (已截断)

## 你必须只输出一个 JSON 对象，格式如下：
{
  "relevance_score": 0.0到1.0的浮点数,
  "is_sufficient": true/false,
  "missing_info": "如果不足，简要说明遗漏的要点；否则填空字符串",
  "suggested_query": "如果不足，给出可尝试重新检索的更精准关键词；否则填空字符串"
}
""",
    "agent.answer": """你是一个严谨的知识库问答助手。
规则：
1. 只基于下面提供的检索上下文回答，不要编造上下文之外的事实；
2. 如果上下文不足，明确说“现有资料不足以完整回答”，并说明缺什么；
3. 尽量引用来源文件名；本次可用来源：{{source_hint}}；
4. 使用中文，结构清晰，不要输出思考过程。""",
    "agent.chat": """你是一个智能问答助手。请根据你的训练知识，准确、完整、有条理地回答用户的问题。使用中文回答。""",
}


@dataclass(frozen=True)
class ResolvedPrompt:
    key: str
    text: str
    version: Optional[int] = None
    label: Optional[str] = None
    source: str = "code"  # code | langfuse | code-fallback


def render_default(template: str, variables: Dict[str, Any]) -> str:
    text = template
    for key, value in variables.items():
        text = text.replace("{{" + key + "}}", str(value))
    return text


def trace_metadata(resolved: ResolvedPrompt) -> Dict[str, Any]:
    return {
        "prompt_key": resolved.key,
        "prompt_version": resolved.version if resolved.version is not None else "code-default",
        "prompt_label": resolved.label or "code",
        "prompt_source": resolved.source,
    }


class PromptRegistry:
    def resolve(self, key: str, **variables: Any) -> ResolvedPrompt:
        default = DEFAULT_PROMPTS.get(key)
        if default is None:
            raise KeyError(f"未知 prompt: {key}")

        if not tracer.enabled:
            return ResolvedPrompt(
                key=key,
                text=render_default(default, variables),
                source="code",
            )

        try:
            prompt = tracer.client.get_prompt(
                key,
                label=settings.LANGFUSE_PROMPT_LABEL,
                fallback=default,
                cache_ttl_seconds=settings.LANGFUSE_PROMPT_CACHE_TTL,
                fetch_timeout_seconds=settings.LANGFUSE_PROMPT_FETCH_TIMEOUT,
            )
            version = getattr(prompt, "version", None)
            labels = getattr(prompt, "labels", None) or []
            # Langfuse SDK 在远端拉取失败时返回 fallback prompt，version=0。
            # 0 不是真实版本（Langfuse version 从 1 开始），必须标记为 code-fallback。
            if version in (None, 0):
                text = render_default(default, variables)
                source = "code-fallback"
                version = None
            else:
                compiled = prompt.compile(**variables) if hasattr(prompt, "compile") else default
                # 只接受 text prompt；如果有人在 Langfuse 把它改成 chat prompt，
                # compile 会返回消息列表，此时回退代码默认值，避免把 list 塞进 SystemMessage。
                if isinstance(compiled, str):
                    text = compiled
                    source = "langfuse"
                else:
                    text = render_default(default, variables)
                    source = "code-fallback"
                    version = None
            return ResolvedPrompt(
                key=key,
                text=text,
                version=version,
                label=labels[0] if labels else settings.LANGFUSE_PROMPT_LABEL,
                source=source,
            )
        except Exception as exc:
            logger.warning("Langfuse prompt %s fetch failed; using code default: %s", key, exc)
            return ResolvedPrompt(
                key=key,
                text=render_default(default, variables),
                source="code-fallback",
            )


prompt_registry = PromptRegistry()
