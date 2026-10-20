#!/usr/bin/env python3
"""10 条 SRE 知识库 Agent 评测：答案关键词 + 引用 + 工具错误。"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx

BASE = os.getenv("E2E_BASE_URL", "http://127.0.0.1:8000")
KB_ID = "kb_sre_enterprise"
OUT = Path(__file__).resolve().parent / "agent_eval.json"

CASES = [
    ("A01", "Kubernetes Pod 一直 CrashLoopBackOff，怎么排查？", ["kubectl", "describe", "logs", "CrashLoop"]),
    ("A02", "Pod 被 OOMKilled，Exit Code 137，怎么定位是堆内还是堆外？", ["137", "OOM", "dmesg", "cgroup"]),
    ("A03", "Kubernetes readiness 和 liveness 探针有什么区别？", ["readiness", "liveness", "就绪", "存活"]),
    ("A04", "Redis Cluster 主节点故障后如何自动转移？", ["cluster", "failover", "故障转移", "主从"]),
    ("A05", "Redis 主从切换后客户端连接异常，怎么处理？", ["reconnect", "重连", "拓扑", "cluster"]),
    ("A06", "PostgreSQL 慢查询怎么定位和优化？", ["EXPLAIN", "索引", "慢查询", "执行计划"]),
    ("A07", "PostgreSQL 出现 deadlock detected，怎么查是谁锁了谁？", ["pg_locks", "deadlock", "pg_stat_activity", "锁"]),
    ("A08", "Agent 工具执行为什么要放沙箱？怎么隔离？", ["沙箱", "sandbox", "隔离", "权限"]),
    ("A09", "外部文档里的提示词注入怎么防？", ["注入", "隔离", "边界", "不可信"]),
    ("A10", "Agent 工具权限应该由模型决定还是后端决定？", ["后端", "权限", "白名单", "allowlist"]),
]


def ask(client: httpx.Client, token: str, question: str) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "messages": [{"role": "user", "content": question}],
        "kb_ids": [KB_ID],
        "mode": "agent",
        "stream": True,
        "top_k": 5,
    }
    answer, citations, steps, err = [], [], [], None
    event = None
    with client.stream("POST", "/api/v1/chat/completions", headers=headers, json=payload) as resp:
        if resp.status_code != 200:
            return {"status": resp.status_code, "error": resp.read().decode("utf-8", "ignore")[:300]}
        for line in resp.iter_lines():
            line = line.strip()
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                try:
                    data = json.loads(line[5:].strip())
                except Exception:
                    continue
                if event == "answer_chunk":
                    answer.append(data.get("content", ""))
                elif event == "rag_result":
                    citations = data.get("citations", []) or citations
                elif event == "agent_thought":
                    steps.append(data)
                elif event == "error":
                    err = data
                elif event == "done":
                    break
    return {"status": 200, "answer": "".join(answer), "citations": citations, "steps": steps, "error": err}


REFUSAL_MARKERS = (
    "现有资料不足以完整回答",
    "没有关于",
    "未包含",
    "知识库中未包含",
    "未检索到",
    "没有找到相关",
    "无法完整回答",
)


def _is_refusal(answer: str) -> bool:
    return any(marker in answer for marker in REFUSAL_MARKERS)


def main() -> int:
    with httpx.Client(base_url=BASE, timeout=120, trust_env=False) as client:
        login = client.post("/api/v1/auth/login", json={"student_id": "2023001", "password": "Test@123456"})
        if login.status_code != 200:
            print("login failed", login.status_code, login.text[:200]); return 2
        token = login.json()["access_token"]

        results = []
        passed = 0
        for cid, question, expected in CASES:
            start = time.perf_counter()
            r = ask(client, token, question)
            latency = round((time.perf_counter() - start) * 1000, 1)
            answer = r.get("answer") or ""
            citations = r.get("citations") or []
            tool_errors = [s for s in (r.get("steps") or []) if s.get("step") == "tool_error"]
            hit_any = any(k.lower() in answer.lower() for k in expected)
            hit_all = all(k.lower() in answer.lower() for k in expected)
            refusal = _is_refusal(answer)
            # 只命中关键词不代表答对；非预期拒答必须判失败。
            ok = (
                r.get("status") == 200
                and not r.get("error")
                and hit_all
                and not refusal
                and bool(citations)
                and not tool_errors
            )
            if ok:
                passed += 1
            results.append({
                "id": cid, "question": question, "ok": ok, "latency_ms": latency,
                "keyword_hit": hit_any, "keyword_hit_all": hit_all,
                "refusal_detected": refusal, "citation_count": len(citations),
                "tool_errors": tool_errors, "answer": answer[:500],
            })
            print(
                f"[{cid}] {'OK' if ok else 'FAIL'} hit_all={hit_all} "
                f"refusal={refusal} citations={len(citations)} "
                f"tool_errors={len(tool_errors)} {latency}ms"
            )
            if not ok:
                print("   ", answer[:200])

    summary = {"cases": len(results), "passed": passed, "failed": len(results) - passed, "results": results}
    OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n=== SUMMARY ===")
    print(json.dumps({k: summary[k] for k in ("cases", "passed", "failed")}, ensure_ascii=False))
    print("JSON:", OUT)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
