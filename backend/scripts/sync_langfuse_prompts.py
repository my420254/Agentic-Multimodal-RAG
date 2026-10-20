#!/usr/bin/env python3
"""把 Agent 代码默认 prompt 同步到 Langfuse Prompt Management。

幂等：内容相同则跳过；内容变化则创建新 version，并把 production label 指过去。
只同步 prompt 文本，不含任何用户数据。
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import get_settings  # noqa: E402
from app.core.tracing import tracer  # noqa: E402
from app.services.prompt_registry import DEFAULT_PROMPTS  # noqa: E402

settings = get_settings()


def main() -> int:
    if not tracer.enabled:
        print("Langfuse 未启用：请先在 backend/.env 配置 LANGFUSE_PUBLIC_KEY / SECRET_KEY", file=sys.stderr)
        return 2
    if not tracer.client.auth_check():
        print("Langfuse auth_check 失败：检查 key/host", file=sys.stderr)
        return 2

    label = settings.LANGFUSE_PROMPT_LABEL
    for name, text in DEFAULT_PROMPTS.items():
        try:
            existing = tracer.client.get_prompt(name, label=label)
            if getattr(existing, "prompt", None) == text:
                print(f"[skip] {name} v{getattr(existing, 'version', '?')} 已是最新")
                continue
            print(f"[update] {name}: 内容变化，创建新 version")
        except Exception:
            print(f"[create] {name}")

        created = tracer.client.create_prompt(
            name=name,
            prompt=text,
            labels=[label],
            type="text",
            commit_message="sync from backend/app/services/prompt_registry.py",
        )
        print(f"         -> {name} v{getattr(created, 'version', '?')} label={label}")

    tracer.flush()
    print("[done] prompts flushed to Langfuse")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
