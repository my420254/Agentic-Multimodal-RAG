#!/usr/bin/env python3
"""把非 PII 的 SRE Agent 评测集上传到 Langfuse，并可选跑一次 Experiment。

只使用 ``benchmark/agent_eval.py`` 的 10 条 SRE 问题（无真实简历 PII）。
真实简历 / grounding 用例不要用这个脚本上传到 Cloud。

用法：
    cd backend
    JWT_SECRET=... python3 benchmark/langfuse_agent_dataset.py --dry-run
    JWT_SECRET=... python3 benchmark/langfuse_agent_dataset.py
    JWT_SECRET=... python3 benchmark/langfuse_agent_dataset.py --run-experiment --limit 2
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

BACKEND_DIR = Path(__file__).resolve().parent.parent
ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import httpx  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.tracing import tracer  # noqa: E402
from benchmark.agent_eval import CASES, KB_ID  # noqa: E402

settings = get_settings()

DATASET_NAME = "agent_sre_v1"
EXPERIMENT_NAME = "agent_sre_baseline"
DEFAULT_BASE = os.getenv("E2E_BASE_URL", "http://127.0.0.1:8000")
DEFAULT_STUDENT = os.getenv("E2E_STUDENT_ID", "2023001")
DEFAULT_PASSWORD = os.getenv("E2E_PASSWORD", "Test@123456")


def golden_cases(limit: int = 0) -> List[Dict[str, Any]]:
    items = [
        {
            "id": case_id,
            "input": {
                "question": question,
                "kb_ids": [KB_ID],
                "mode": "agent",
                "top_k": 5,
            },
            "expected_output": {"keywords": keywords},
            "metadata": {
                "case_id": case_id,
                "source": "backend/benchmark/agent_eval.py",
                "kb_id": KB_ID,
                "pii": False,
            },
        }
        for case_id, question, keywords in CASES
    ]
    return items[:limit] if limit else items


def ensure_dataset(client, items: List[Dict[str, Any]]) -> List[Any]:
    """创建 dataset 并返回 DatasetItem 列表；已存在的 case 不重复创建。"""
    try:
        dataset = client.get_dataset(DATASET_NAME)
        existing = {item.id for item in dataset.items}
        print(f"[dataset] 已存在 {DATASET_NAME}，现有 {len(existing)} 条")
    except Exception:
        client.create_dataset(
            name=DATASET_NAME,
            description="10 条云原生 SRE Agent 评测用例（非 PII）",
            metadata={"source": "benchmark/agent_eval.py", "version": "v1"},
        )
        dataset = client.get_dataset(DATASET_NAME)
        existing = set()
        print(f"[dataset] 已创建 {DATASET_NAME}")

    for item in items:
        if item["id"] in existing:
            continue
        client.create_dataset_item(
            dataset_name=DATASET_NAME,
            id=item["id"],
            input=item["input"],
            expected_output=item["expected_output"],
            metadata=item["metadata"],
        )
        print(f"[dataset] + {item['id']}")

    # 重新拉取，确保拿到最新 items
    return client.get_dataset(DATASET_NAME).items


async def login(client: httpx.AsyncClient, base: str) -> str:
    resp = await client.post(
        f"{base}/api/v1/auth/login",
        json={"student_id": DEFAULT_STUDENT, "password": DEFAULT_PASSWORD},
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


async def ask_agent(
    client: httpx.AsyncClient,
    token: str,
    question: str,
    *,
    kb_ids: Optional[List[str]] = None,
    top_k: int = 5,
) -> Dict[str, Any]:
    payload = {
        "messages": [{"role": "user", "content": question}],
        "kb_ids": kb_ids or [KB_ID],
        "mode": "agent",
        "stream": True,
        "top_k": top_k,
    }
    started = time.perf_counter()
    answer, citations, steps, done, event = [], [], [], None, None
    async with client.stream(
        "POST",
        f"{DEFAULT_BASE}/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
        timeout=180,
    ) as resp:
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            if line.startswith("event: "):
                event = line[7:].strip()
            elif line.startswith("data: "):
                data = line[6:]
                if event == "answer_chunk":
                    answer.append(json.loads(data).get("content", ""))
                elif event == "rag_result":
                    citations = json.loads(data).get("citations", []) or citations
                elif event == "agent_thought":
                    steps.append(json.loads(data))
                elif event == "done":
                    done = json.loads(data)
    total_ms = (time.perf_counter() - started) * 1000
    return {
        "answer": "".join(answer),
        "citations": citations,
        "steps": steps,
        "tool_errors": [s for s in steps if s.get("step") == "tool_error"],
        "langfuse_trace_id": (done or {}).get("langfuse_trace_id"),
        "total_ms": round(total_ms, 2),
    }


def keyword_hit(*, input, output, expected_output, metadata, **kwargs):
    from langfuse.experiment import Evaluation

    keywords = (expected_output or {}).get("keywords", [])
    answer = (output or {}).get("answer", "").lower()
    hits = [kw for kw in keywords if kw.lower() in answer]
    ratio = len(hits) / len(keywords) if keywords else 0.0
    return Evaluation(
        name="keyword_hit",
        value=round(ratio, 4),
        comment=f"{len(hits)}/{len(keywords)} keywords; hits={hits}",
    )


def citation_present(*, input, output, expected_output, metadata, **kwargs):
    from langfuse.experiment import Evaluation

    count = len((output or {}).get("citations") or [])
    return Evaluation(
        name="citation_present",
        value=bool(count),
        data_type="BOOLEAN",
        comment=f"{count} citations",
    )


def no_tool_error(*, input, output, expected_output, metadata, **kwargs):
    from langfuse.experiment import Evaluation

    errors = (output or {}).get("tool_errors") or []
    return Evaluation(
        name="no_tool_error",
        value=not bool(errors),
        data_type="BOOLEAN",
        comment=f"{len(errors)} tool errors",
    )


async def run_experiment(client_lf, items: List[Any], limit: int = 0) -> None:
    selected = items[:limit] if limit else items
    token_holder: Dict[str, str] = {}

    async with httpx.AsyncClient(timeout=180, trust_env=True) as http_client:
        token_holder["token"] = await login(http_client, DEFAULT_BASE)

        async def task(*, item, **kwargs):
            input_data = item.input if hasattr(item, "input") else item.get("input", {})
            result = await ask_agent(
                http_client,
                token_holder["token"],
                input_data["question"],
                kb_ids=input_data.get("kb_ids"),
                top_k=input_data.get("top_k", 5),
            )
            return result

        run_name = f"{EXPERIMENT_NAME}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
        result = client_lf.run_experiment(
            name=EXPERIMENT_NAME,
            run_name=run_name,
            description="SRE Agent baseline: keyword hit / citation present / no tool error",
            data=selected,
            task=task,
            evaluators=[keyword_hit, citation_present, no_tool_error],
            max_concurrency=1,
            metadata={
                "git_commit": subprocess.check_output(
                    ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True
                ).strip(),
                "kb_id": KB_ID,
                "mode": "agent",
            },
        )
        print(result.format(include_item_results=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 条")
    parser.add_argument("--dry-run", action="store_true", help="只打印，不上传/不运行")
    parser.add_argument("--run-experiment", action="store_true", help="上传后跑一次 Experiment")
    args = parser.parse_args()

    items = golden_cases(args.limit)
    if args.dry_run:
        print(json.dumps(items, ensure_ascii=False, indent=2))
        return 0

    if not tracer.enabled:
        print(
            "Langfuse 未启用：请先在 backend/.env 配置 LANGFUSE_PUBLIC_KEY / SECRET_KEY",
            file=sys.stderr,
        )
        return 2
    if not tracer.client.auth_check():
        print("Langfuse auth_check 失败：检查 key/host", file=sys.stderr)
        return 2

    dataset_items = ensure_dataset(tracer.client, items)
    print(f"[dataset] {DATASET_NAME}: {len(dataset_items)} items")

    if args.run_experiment:
        asyncio.run(run_experiment(tracer.client, dataset_items, args.limit))

    tracer.flush()
    print("[done] flushed to Langfuse")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
