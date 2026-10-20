"""Prompt 注册表的本地 fallback 与变量渲染测试（不联网）。"""

import pytest

from app.services.prompt_registry import (
    DEFAULT_PROMPTS,
    prompt_registry,
    render_default,
    trace_metadata,
)


def test_default_prompts_cover_agent_nodes():
    assert {
        "agent.intent",
        "agent.system",
        "agent.grading",
        "agent.answer",
        "agent.chat",
    } <= set(DEFAULT_PROMPTS)


def test_render_default_replaces_only_double_brace_variables():
    template = 'JSON {"k": 1} and {{value}}'
    assert render_default(template, {"value": "x"}) == 'JSON {"k": 1} and x'


def test_resolve_uses_code_fallback_without_langfuse():
    resolved = prompt_registry.resolve("agent.answer", source_hint="resume.pdf")
    assert resolved.source == "code"
    assert "resume.pdf" in resolved.text
    assert resolved.version is None


def test_unknown_prompt_raises():
    with pytest.raises(KeyError):
        prompt_registry.resolve("agent.missing")


def test_trace_metadata_is_langfuse_friendly():
    resolved = prompt_registry.resolve("agent.chat")
    metadata = trace_metadata(resolved)
    assert metadata["prompt_key"] == "agent.chat"
    assert metadata["prompt_version"] == "code-default"
    assert metadata["prompt_source"] == "code"


class _FallbackPrompt:
    version = 0
    labels = ["production"]

    def compile(self, **kwargs):
        return "should not be used"


class _FallbackClient:
    def get_prompt(self, *args, **kwargs):
        return _FallbackPrompt()


def test_version_zero_means_sdk_fallback(monkeypatch):
    from app.core.tracing import tracer

    monkeypatch.setattr(tracer, "_client", _FallbackClient())
    monkeypatch.setattr(tracer, "_enabled", True)
    monkeypatch.setattr(tracer, "_init_done", True)

    resolved = prompt_registry.resolve("agent.chat")
    assert resolved.source == "code-fallback"
    assert resolved.version is None
    assert resolved.text == DEFAULT_PROMPTS["agent.chat"]
