"""Langfuse tracing 的安全降级与 PII 脱敏测试（不联网）。"""

import pytest

from app.core import tracing as tracing_module
from app.core.tracing import Tracing, hash_user_id, redact_text


def test_hash_user_id_is_stable_and_pseudonymous():
    first = hash_user_id("user-123")
    second = hash_user_id("user-123")
    assert first == second
    assert first != "user-123"
    assert len(first) == 16
    assert hash_user_id(None) is None


def test_redact_text_masks_common_pii(monkeypatch):
    monkeypatch.setattr(tracing_module.settings, "TRACE_CONTENT_MODE", "redacted")
    text = "联系 13800138000 / user@example.com / 学号 2023001"
    redacted = redact_text(text)
    assert "13800138000" not in redacted
    assert "user@example.com" not in redacted
    assert "2023001" not in redacted
    assert "[phone]" in redacted
    assert "[email]" in redacted


def test_redact_text_metadata_mode_hides_long_content(monkeypatch):
    monkeypatch.setattr(tracing_module.settings, "TRACE_CONTENT_MODE", "metadata")
    tracer = Tracing()
    safe = tracer.safe("这是一段很长的简历正文" * 20, key="content")
    assert safe.startswith("[redacted:")
    assert "简历正文" not in safe


def test_tracing_is_noop_without_keys(monkeypatch):
    monkeypatch.setattr(tracing_module.settings, "LANGFUSE_ENABLED", True)
    monkeypatch.setattr(tracing_module.settings, "LANGFUSE_PUBLIC_KEY", None)
    monkeypatch.setattr(tracing_module.settings, "LANGFUSE_SECRET_KEY", None)

    tracer = Tracing()
    assert tracer.enabled is False
    with tracer.trace(name="test", user_id="u1") as root:
        assert root is None
    with tracer.observation("test.child") as span:
        assert span is None
    assert tracer.callback_handler() is None
    assert tracer.current_trace_id() is None


class _FakeCM:
    def __init__(self):
        self.exited = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.exited = True
        return False


class _FakeClient:
    def __init__(self):
        self.cm = _FakeCM()

    def start_as_current_observation(self, **kwargs):
        return self.cm

    def get_current_trace_id(self):
        return "trace-test"


def test_trace_does_not_swallow_business_exceptions(monkeypatch):
    import langfuse

    monkeypatch.setattr(langfuse, "propagate_attributes", lambda **kwargs: _FakeCM())

    tracer = Tracing()
    fake = _FakeClient()
    tracer._client = fake
    tracer._enabled = True
    tracer._init_done = True

    with pytest.raises(ValueError, match="business"):
        with tracer.trace(name="test") as root:
            assert root is not None
            raise ValueError("business")

    assert fake.cm.exited is True


def test_tracing_safe_recurses_into_dicts_and_lists(monkeypatch):
    monkeypatch.setattr(tracing_module.settings, "TRACE_CONTENT_MODE", "redacted")
    tracer = Tracing()
    value = {
        "query": "邮箱 a@b.com",
        "items": ["13800138000", {"phone": "13900139000"}],
    }
    safe = tracer.safe(value)
    assert "a@b.com" not in str(safe)
    assert "13800138000" not in str(safe)
    assert "13900139000" not in str(safe)
