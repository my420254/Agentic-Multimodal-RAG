#!/usr/bin/env python3
"""登录 -> 建临时 KB -> 上传 -> 解析/向量化 -> 提问 -> 校验引用 -> 清理。"""

from __future__ import annotations

import json
import sys
import time
import uuid

import httpx

BASE = "http://127.0.0.1:8000"
STUDENT = "2023001"
PASSWORD = "Test@123456"
TOKEN = f"QCM-{uuid.uuid4().hex[:8].upper()}"


def sse_ask(client: httpx.Client, headers: dict, kb_id: str) -> tuple[list, str, str | None]:
    payload = {
        "messages": [{"role": "user", "content": "量子咖啡机 QCM 项目的技术栈是什么？"}],
        "kb_ids": [kb_id],
        "mode": "chat",
        "stream": True,
        "search_mode": "vector",
        "top_k": 3,
    }
    cites, answer, err = [], [], None
    event = None
    with client.stream("POST", "/api/v1/chat/completions", headers=headers, json=payload) as resp:
        print("chat status:", resp.status_code)
        if resp.status_code != 200:
            return [], "", resp.read().decode("utf-8", "ignore")[:300]
        for line in resp.iter_lines():
            line = line.strip()
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                try:
                    data = json.loads(line[5:].strip())
                except Exception:
                    continue
                if event == "rag_result":
                    cites = data.get("citations", []) or cites
                elif event == "answer_chunk":
                    answer.append(data.get("content", ""))
                elif event == "error":
                    err = data
                elif event == "done":
                    break
    return cites, "".join(answer), err


def main() -> int:
    headers = {}
    with httpx.Client(base_url=BASE, timeout=120, trust_env=False) as client:
        login = client.post("/api/v1/auth/login", json={"student_id": STUDENT, "password": PASSWORD})
        if login.status_code != 200:
            print("login failed", login.status_code, login.text[:200]); return 2
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        kb_name = f"E2E临时KB_{uuid.uuid4().hex[:8]}"
        kb_resp = client.post("/api/v1/knowledge-bases", headers=headers, json={
            "name": kb_name,
            "description": "E2E upload/ask/citation test",
            "embedding_model": "sys_embedding",
            "vlm_model": "default",
        })
        if kb_resp.status_code not in (200, 201):
            print("create kb failed", kb_resp.status_code, kb_resp.text[:300]); return 2
        kb_id = kb_resp.json()["data"]["id"]
        print("kb:", kb_id, kb_name)

        content = f"""# 量子咖啡机 {TOKEN}

项目代号：{TOKEN}
技术栈：FastAPI + Redis + PostgreSQL
项目描述：这是一个用于验证上传、解析、向量化、检索与引用链路的临时文档。
"""
        upload = client.post(
            f"/api/v1/knowledge-bases/{kb_id}/upload",
            headers=headers,
            files={"file": ("e2e_qcm.md", content.encode("utf-8"), "text/markdown")},
        )
        if upload.status_code not in (200, 202):
            print("upload failed", upload.status_code, upload.text[:300])
            client.delete(f"/api/v1/knowledge-bases/{kb_id}/permanent", headers=headers)
            return 2
        file_id = upload.json()["data"]["file_id"]
        print("file:", file_id)

        parse = client.post(
            f"/api/v1/files/{file_id}/parse",
            headers=headers,
            json={"chunk_mode": "custom", "chunk_size": 300, "chunk_overlap": 30, "auto_vectorize": True},
        )
        print("parse:", parse.status_code, parse.text[:200])
        status = None
        for i in range(60):
            detail = client.get(f"/api/v1/files/{file_id}", headers=headers).json()["data"]
            status = detail["status"]
            print(f"  poll {i}: {status} chunks={detail.get('chunk_count')}")
            if status in ("ready", "parsed") and (detail.get("chunk_count") or 0) > 0:
                break
            if status == "failed":
                break
            time.sleep(2)
        if status == "failed" or (detail.get("chunk_count") or 0) == 0:
            print("parse not ready:", status)
            client.delete(f"/api/v1/knowledge-bases/{kb_id}/permanent", headers=headers)
            return 2

        cites, answer, err = sse_ask(client, headers, kb_id)
        print("citations:", [(c.get("fileName"), c.get("score")) for c in cites])
        print("answer:", answer[:300])
        print("error:", err)

        ok = (
            not err
            and bool(cites)
            and any(c.get("fileName") == "e2e_qcm.md" for c in cites)
            and ("FastAPI" in answer or "Redis" in answer)
        )
        print("RESULT:", "PASS" if ok else "FAIL")
        client.delete(f"/api/v1/knowledge-bases/{kb_id}/permanent", headers=headers)
        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
