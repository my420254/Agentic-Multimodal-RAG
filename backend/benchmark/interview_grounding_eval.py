#!/usr/bin/env python3
"""10 条真实简历 × 岗位 JD 的模拟面试 grounding E2E。

检查：
1. 登录真实账号；
2. 选定一份简历文件；
3. 调用 /career/interview/chat；
4. 响应 grounding_available=true；
5. grounding_citations 全部来自选定文件，不能混入其他候选人的简历；
6. 没有 GraphRAG 字段。
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import httpx

BASE = os.getenv("E2E_BASE_URL", "http://127.0.0.1:8000")
STUDENT = os.getenv("E2E_STUDENT_ID", "2023001")
PASSWORD = os.getenv("E2E_PASSWORD", "Test@123456")
KB_ID = "kb_real_resumes"
OUT = Path(__file__).resolve().parent / "interview_grounding_eval.json"

CASES = [
    ("G01", "辽宁大学_27届_张梦洋(4).pdf", "AI Agent / 后端研发工程师", "我在实习里做过 RAG 检索和后端服务，您可以挑一个项目点追问。"),
    ("G02", "辽宁大学_27届_张梦洋(4).pdf", "大模型应用 / RAG 工程师", "我做过混合检索和重排，想请您追问检索链路的取舍。"),
    ("G03", "宋浩简历(2).pdf", "RAG / 文档智能工程师", "我做过文档解析和检索，您可以追问项目细节。"),
    ("G04", "宋浩简历(2).pdf", "数据平台 / 后端开发", "我做过数据链路和后端开发，请从简历里的项目继续问。"),
    ("G05", "盛国梁 校招简历(2).pdf", "高并发后端工程师", "我做过大文件传输和秒杀场景，您可以追问并发与容错。"),
    ("G06", "盛国梁 校招简历(2).pdf", "云原生 / SRE 工程师", "我做过服务部署和故障排查，请从项目经历继续问。"),
    ("G07", "个人简历(2).pdf", "Java 后端工程师", "我做过 Java 后端和数据库相关项目，您可以追问实现细节。"),
    ("G08", "个人简历(2).pdf", "数据库 / 后端开发", "我做过数据库设计和后端接口，请从简历项目继续追问。"),
    ("G09", "辽宁大学_27届_张梦洋(4).pdf", "LLM 应用开发工程师", "我做过 Agent 状态机和 RAG，您可以追问工程落地。"),
    ("G10", "宋浩简历(2).pdf", "多模态 / 文档解析工程师", "我做过文档处理和多模态解析，请从项目出发追问。"),
]


def main() -> int:
    with httpx.Client(base_url=BASE, timeout=90, trust_env=False) as client:
        login = client.post("/api/v1/auth/login", json={"student_id": STUDENT, "password": PASSWORD})
        if login.status_code != 200:
            print(f"login failed: {login.status_code} {login.text[:300]}")
            return 2
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        files = client.get(f"/api/v1/knowledge-bases/{KB_ID}/files", headers=headers)
        if files.status_code != 200:
            print(f"list files failed: {files.status_code} {files.text[:300]}")
            return 2
        by_name = {f["name"]: f["id"] for f in files.json().get("data", [])}

        results = []
        failures = 0
        for case_id, filename, role, answer in CASES:
            fid = by_name.get(filename)
            started = time.perf_counter()
            if not fid:
                failures += 1
                results.append({"id": case_id, "file": filename, "ok": False, "error": "file not found"})
                print(f"[{case_id}] FAIL file not found: {filename}")
                continue
            resp = client.post(
                "/api/v1/career/interview/chat",
                headers=headers,
                json={
                    "messages": [{"role": "user", "content": answer}],
                    "mode": "mock_interview",
                    "target_role": role,
                    "resume_file_id": fid,
                },
            )
            latency = round((time.perf_counter() - started) * 1000, 1)
            if resp.status_code != 200:
                failures += 1
                results.append({"id": case_id, "file": filename, "ok": False, "latency_ms": latency, "error": resp.text[:300]})
                print(f"[{case_id}] FAIL HTTP {resp.status_code}")
                continue
            data = resp.json()
            citations = data.get("grounding_citations") or []
            names = {c.get("file_name") for c in citations}
            graph_fields = [k for k in data if "graphrag" in k.lower()]
            ok = (
                data.get("grounding_available") is True
                and bool(citations)
                and names == {filename}
                and not graph_fields
                and len(data.get("reply_text") or "") >= 20
            )
            if not ok:
                failures += 1
            row = {
                "id": case_id,
                "file": filename,
                "role": role,
                "ok": ok,
                "latency_ms": latency,
                "grounding_available": data.get("grounding_available"),
                "citation_count": len(citations),
                "citation_files": sorted(n for n in names if n),
                "graph_fields": graph_fields,
                "question": data.get("reply_text"),
                "citations": [
                    {"file_name": c.get("file_name"), "location": c.get("location"), "score": c.get("score")}
                    for c in citations
                ],
            }
            results.append(row)
            print(f"[{case_id}] {'OK' if ok else 'FAIL'} {filename} citations={len(citations)} latency={latency}ms")
            print(f"       {str(data.get('reply_text'))[:160]}")

    summary = {
        "cases": len(results),
        "passed": len(results) - failures,
        "failed": failures,
        "results": results,
    }
    OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n=== SUMMARY ===")
    print(json.dumps({k: summary[k] for k in ("cases", "passed", "failed")}, ensure_ascii=False))
    print(f"JSON: {OUT}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
