import uuid
import pytest
from fastapi.testclient import TestClient


def test_list_knowledge_bases(client: TestClient, enterprise_kb_id: str, auth_headers: dict):
    """测试获取知识库列表接口"""
    assert client.get("/api/v1/knowledge-bases").status_code == 401
    response = client.get("/api/v1/knowledge-bases", headers=auth_headers)
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["code"] == 200
    assert isinstance(res_data["data"], list)
    kb_ids = [item["id"] for item in res_data["data"]]
    assert enterprise_kb_id in kb_ids


def test_knowledge_base_lifecycle_crud(client: TestClient, auth_headers: dict):
    """测试知识库完整生命周期 (创建 -> 详情 -> 软删除进入回收站 -> 恢复 -> 永久删除)"""
    unique_suffix = uuid.uuid4().hex[:8]
    create_payload = {
        "name": f"自动化测试专用知识库_{unique_suffix}",
        "description": "用于 pytest 自动化功能验收",
        "embedding_model": "BAAI/bge-m3",
        "vlm_model": "Qwen/Qwen3-VL-8B-Instruct",
    }
    # 1. 创建 (Create)
    create_res = client.post("/api/v1/knowledge-bases", json=create_payload, headers=auth_headers)
    assert create_res.status_code in [200, 201]
    created_data = create_res.json()["data"]
    kb_id = created_data["id"]
    assert created_data["name"] == create_payload["name"]

    # 2. 查询详情 (Detail)
    detail_res = client.get(f"/api/v1/knowledge-bases/{kb_id}", headers=auth_headers)
    assert detail_res.status_code == 200
    assert detail_res.json()["data"]["id"] == kb_id

    # 3. 软删除入回收站 (Soft Delete)
    delete_res = client.delete(f"/api/v1/knowledge-bases/{kb_id}", headers=auth_headers)
    assert delete_res.status_code == 200

    # 4. 检查回收站 (Recycle Bin)
    recycle_res = client.get("/api/v1/knowledge-bases/recycle-bin", headers=auth_headers)
    assert recycle_res.status_code == 200
    recycle_ids = [k["id"] for k in recycle_res.json()["data"]]
    assert kb_id in recycle_ids

    # 5. 从回收站恢复 (Restore)
    restore_res = client.post(f"/api/v1/knowledge-bases/{kb_id}/restore", headers=auth_headers)
    assert restore_res.status_code == 200

    # 6. 永久彻底删除 (Permanent Delete)
    perm_res = client.delete(f"/api/v1/knowledge-bases/{kb_id}/permanent", headers=auth_headers)
    assert perm_res.status_code == 200

    # 7. 再次查询确认已彻底清除
    get_again = client.get(f"/api/v1/knowledge-bases/{kb_id}", headers=auth_headers)
    assert get_again.status_code == 404
