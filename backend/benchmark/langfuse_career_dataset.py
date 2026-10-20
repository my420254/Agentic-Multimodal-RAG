#!/usr/bin/env python3
"""求职域 Langfuse Dataset / Experiment（非 PII 合成简历）。

数据来自 data/benchmark_resumes/ 的合成简历（假姓名/假联系方式），
覆盖：
- 简历 × JD 匹配：安全岗正样本、跨领域低匹配样本；
- 岗位反欺诈：正常 JD、培训贷、境外诱导。

真实简历 42 条 golden 和 10 条 grounding 仍留在本机，不上传 Cloud。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

BACKEND_DIR = Path(__file__).resolve().parent.parent
ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import httpx  # noqa: E402

from app.core.tracing import tracer  # noqa: E402

DATASET_NAME = "career_demo_v1"
EXPERIMENT_NAME = "career_quality_baseline"
BASE = os.getenv("E2E_BASE_URL", "http://127.0.0.1:8000")
STUDENT = os.getenv("E2E_STUDENT_ID", "2023001")
PASSWORD = os.getenv("E2E_PASSWORD", "Test@123456")
RESUME_DIR = ROOT / "data" / "benchmark_resumes"


def _resume(name: str) -> str:
    return (RESUME_DIR / name).read_text(encoding="utf-8")


CASES: List[Dict[str, Any]] = [
    {
        "id": "M01",
        "task": "match",
        "resume_file": "03_prompt_injection_case.md",
        "resume_text": _resume("03_prompt_injection_case.md"),
        "jd_text": "大模型安全工程师：熟悉 Prompt Injection、Jailbreak、护栏、Python 安全开发。",
        "expected": {"match_level": ["MATCHED", "HIGHLY_MATCHED"], "min_score": 70},
    },
    {
        "id": "M02",
        "task": "match",
        "resume_file": "04_ood_mismatch_case.md",
        "resume_text": _resume("04_ood_mismatch_case.md"),
        "jd_text": "大模型 Agent 工程师：熟悉 Python、LangGraph、RAG、向量检索、Agent 工程。",
        "expected": {"match_level": ["LOW"], "max_score": 54},
    },
    {
        "id": "F01",
        "task": "fraud",
        "job_title": "大模型 Agent 研发工程师",
        "company": "某科技有限公司",
        "job_description": "熟悉 Python、LangGraph、RAG、向量检索，有 Agent 项目经验优先。",
        "expected": {"is_fraudulent": False},
    },
    {
        "id": "F02",
        "task": "fraud",
        "job_title": "高薪 AI 学徒",
        "company": "某培训公司",
        "job_description": "无需经验，包分配，入职前需参加 3 个月实训并办理学费分期贷款 2 万元。",
        "expected": {"is_fraudulent": True, "risk_level": ["SUSPICIOUS", "HIGH_RISK"]},
    },
    {
        "id": "F03",
        "task": "fraud",
        "job_title": "海外数据录入专员",
        "company": "某跨境公司",
        "job_description": "月薪三万包机票签证，工作地点老挝/缅北特区，护照公司统一管理。",
        "expected": {"is_fraudulent": True, "risk_level": ["SUSPICIOUS", "HIGH_RISK"]},
    },
]


def golden_cases(limit: int = 0) -> List[Dict[str, Any]]:
    items = [
        {
            "id": case["id"],
            "input": {k: v for k, v in case.items() if k not in {"id", "expected"}},
            "expected_output": case["expected"],
            "metadata": {
                "case_id": case["id"],
                "task": case["task"],
                "pii": False,
                "source": "data/benchmark_resumes (synthetic)",
            },
        }
        for case in CASES
    ]
    return items[:limit] if limit else items


def ensure_dataset(client, items: List[Dict[str, Any]]) -> List[Any]:
    try:
        dataset = client.get_dataset(DATASET_NAME)
        existing = {item.id for item in dataset.items}
        print(f"[dataset] 已存在 {DATASET_NAME}，现有 {len(existing)} 条")
    except Exception:
        client.create_dataset(
            name=DATASET_NAME,
            description="求职域合成简历评测：简历×JD 匹配 + 岗位反欺诈（非 PII）",
            metadata={"source": "data/benchmark_resumes", "version": "v1"},
        )
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

    return client.get_dataset(DATASET_NAME).items


def login(client: httpx.Client) -> str:
    resp = client.post(
        f"{BASE}/api/v1/auth/login",
        json={"student_id": STUDENT, "password": PASSWORD},
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def run_task(client: httpx.Client, token: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}"}
    if input_data["task"] == "match":
        resp = client.post(
            f"{BASE}/api/v1/career/match",
            headers=headers,
            json={"resume_text": input_data["resume_text"], "jd_text": input_data["jd_text"]},
            timeout=180,
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "overall_match_score": data.get("overall_match_score"),
            "match_level": data.get("match_level"),
            "missing_skills": data.get("missing_skills") or [],
            "star_rewrite_count": len(data.get("star_optimizations") or []),
        }

    resp = client.post(
        f"{BASE}/api/v1/career/fraud-check",
        headers=headers,
        json={
            "job_title": input_data["job_title"],
            "company": input_data.get("company", ""),
            "job_description": input_data["job_description"],
            "deep_audit": False,
        },
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    return {
        "is_fraudulent": data.get("is_fraudulent"),
        "risk_level": data.get("risk_level"),
        "risk_score": data.get("risk_score"),
    }


def match_level_ok(*, input, output, expected_output, metadata, **kwargs):
    from langfuse.experiment import Evaluation

    expected = (expected_output or {}).get("match_level")
    if not expected:
        return Evaluation(name="match_level_ok", value=True, data_type="BOOLEAN", comment="not a match case")
    actual = (output or {}).get("match_level")
    return Evaluation(
        name="match_level_ok",
        value=actual in expected,
        data_type="BOOLEAN",
        comment=f"actual={actual}, expected={expected}",
    )


def score_range_ok(*, input, output, expected_output, metadata, **kwargs):
    from langfuse.experiment import Evaluation

    expected = expected_output or {}
    actual = (output or {}).get("overall_match_score")
    if actual is None:
        return Evaluation(name="score_range_ok", value=True, data_type="BOOLEAN", comment="not a match case")
    low = expected.get("min_score", 0)
    high = expected.get("max_score", 100)
    return Evaluation(
        name="score_range_ok",
        value=low <= actual <= high,
        data_type="BOOLEAN",
        comment=f"actual={actual}, expected=[{low},{high}]",
    )


def fraud_label_ok(*, input, output, expected_output, metadata, **kwargs):
    from langfuse.experiment import Evaluation

    expected = (expected_output or {}).get("is_fraudulent")
    if expected is None:
        return Evaluation(name="fraud_label_ok", value=True, data_type="BOOLEAN", comment="not a fraud case")
    actual = (output or {}).get("is_fraudulent")
    return Evaluation(
        name="fraud_label_ok",
        value=actual == expected,
        data_type="BOOLEAN",
        comment=f"actual={actual}, expected={expected}",
    )


def has_star_rewrite(*, input, output, expected_output, metadata, **kwargs):
    from langfuse.experiment import Evaluation

    if input.get("task") != "match":
        return Evaluation(name="has_star_rewrite", value=True, data_type="BOOLEAN", comment="not a match case")
    count = (output or {}).get("star_rewrite_count", 0)
    return Evaluation(
        name="has_star_rewrite",
        value=count > 0,
        data_type="BOOLEAN",
        comment=f"{count} rewrites",
    )


def run_experiment(client_lf, items: List[Any], limit: int = 0) -> None:
    selected = items[:limit] if limit else items
    with httpx.Client(timeout=180, trust_env=False) as http_client:
        token = login(http_client)

        def task(*, item, **kwargs):
            input_data = item.input if hasattr(item, "input") else item.get("input", {})
            return run_task(http_client, token, input_data)

        run_name = f"{EXPERIMENT_NAME}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
        result = client_lf.run_experiment(
            name=EXPERIMENT_NAME,
            run_name=run_name,
            description="求职域：简历×JD 匹配 + 岗位反欺诈（合成数据，非 PII）",
            data=selected,
            task=task,
            evaluators=[match_level_ok, score_range_ok, fraud_label_ok, has_star_rewrite],
            max_concurrency=1,
            metadata={
                "git_commit": subprocess.check_output(
                    ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True
                ).strip(),
                "dataset": DATASET_NAME,
            },
        )
        print(result.format(include_item_results=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--run-experiment", action="store_true")
    args = parser.parse_args()

    items = golden_cases(args.limit)
    if args.dry_run:
        print(json.dumps(items, ensure_ascii=False, indent=2))
        return 0
    if not tracer.enabled:
        print("Langfuse 未启用：请先在 backend/.env 配置 key", file=sys.stderr)
        return 2
    if not tracer.client.auth_check():
        print("Langfuse auth_check 失败", file=sys.stderr)
        return 2

    dataset_items = ensure_dataset(tracer.client, items)
    print(f"[dataset] {DATASET_NAME}: {len(dataset_items)} items")
    if args.run_experiment:
        run_experiment(tracer.client, dataset_items, args.limit)
    tracer.flush()
    print("[done] flushed to Langfuse")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
