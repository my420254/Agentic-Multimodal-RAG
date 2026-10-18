import json
import pytest
from fastapi.testclient import TestClient


def test_chat_rewrite_api(client: TestClient):
    """测试问题改写接口"""
    payload = {"query": "那个 137 报错是什么原因？"}
    response = client.post("/api/v1/chat/rewrite", json=payload)
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["code"] == 200
    assert "rewritten_query" in res_data["data"]
    assert len(res_data["data"]["rewritten_query"]) > 0


def test_chat_completions_kb_not_found(client: TestClient):
    """测试请求不存在的知识库时严格返回 404"""
    payload = {
        "messages": [{"role": "user", "content": "测试问题"}],
        "kb_ids": ["non_existent_kb_12345"],
        "stream": True,
    }
    response = client.post("/api/v1/chat/completions", json=payload)
    assert response.status_code == 404


def test_chat_completions_streaming_sse(client: TestClient, enterprise_kb_id: str):
    """测试真实生产 SRE 故障问答的 SSE 流式输出完整性"""
    payload = {
        "messages": [
            {"role": "user", "content": "线上 Redis 发生缓存击穿该如何防范？"}
        ],
        "kb_ids": [enterprise_kb_id],
        "stream": True,
    }
    with client.stream("POST", "/api/v1/chat/completions", json=payload) as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        
        events = []
        for line in response.iter_lines():
            if line.startswith("event: "):
                events.append(line.replace("event: ", "").strip())

        # 验证关键 SSE 事件到达
        assert "agent_thought" in events
        assert "answer_chunk" in events or "error" in events
        assert "done" in events or "error" in events

