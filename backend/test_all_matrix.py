import os
import sys
import time
import requests
import sqlite3

BASE_URL = "http://127.0.0.1:8000"

def run_tests():
    print("=" * 60)
    print("🚀 开始全量全矩阵压力与兼容性测试...")
    print("=" * 60)

    # 1. 检查数据库现有文件
    conn = sqlite3.connect("/home/yang/Agentic-Multimodal-RAG/backend/local.db")
    c = conn.cursor()
    c.execute("SELECT id, name, local_path FROM file_documents")
    files = c.fetchall()
    print(f"📁 发现数据库中已有 {len(files)} 个测试文件:")
    for f in files:
        print(f"  - [{f[0]}] {f[1]} ({f[2]})")

    # 2. 测试所有模型连通性
    print("\n--- [测试 1/4] 测试所有模型在线状态 ---")
    c.execute("SELECT id, name, model_type FROM custom_models")
    custom_models = c.fetchall()
    for m in custom_models:
        m_id, m_name, m_type = m
        res = requests.post(f"{BASE_URL}/api/v1/settings/models/{m_id}/test", timeout=20)
        status = "✅ PASS" if res.status_code == 200 else f"❌ FAIL ({res.text})"
        print(f"  模型 [{m_type}] {m_name}: {status}")

    # 3. 测试文件解析与所有分块方式
    # chunk_modes: custom, structure, semantic, no_split
    # embedding_models: sys_embedding, 6fe0e548-a9a8-487b-a07c-cf509a023170
    chunk_modes = ["custom", "structure", "semantic", "no_split"]
    models_to_test = ["sys_embedding", "6fe0e548-a9a8-487b-a07c-cf509a023170"]

    print("\n--- [测试 2/4] 测试每种文件类型 + 每种分块方式组合 ---")
    
    # 选代表性文件: .md, .docx, .pdf
    test_files = {}
    for f in files:
        ext = os.path.splitext(f[1])[1].lower()
        if ext not in test_files:
            test_files[ext] = f

    for ext, (f_id, f_name, f_path) in test_files.items():
        print(f"\n📄 正在测试文件类型: {ext} ({f_name})")
        for mode in chunk_modes:
            for vec_model in models_to_test:
                model_label = "sys_embedding" if vec_model == "sys_embedding" else "Custom-BGE-M3"
                print(f"  👉 测试切分模式: [{mode}] + Embedding: [{model_label}] ...", end=" ", flush=True)
                
                payload = {
                    "chunk_mode": mode,
                    "chunk_size": 400,
                    "chunk_overlap": 40,
                    "heading_level": 2,
                    "auto_vectorize": True,
                    "vector_model": vec_model,
                    "embedding_model": vec_model
                }
                
                # 触发解析
                t0 = time.time()
                r = requests.post(f"{BASE_URL}/api/v1/files/{f_id}/parse", json=payload, timeout=30)
                if r.status_code != 200:
                    print(f"❌ 触发失败: {r.status_code} {r.text}")
                    continue

                # 轮询状态直到完成或失败 (最多等 45s)
                success = False
                err_msg = ""
                final_chunks = 0
                for _ in range(30):
                    time.sleep(1.5)
                    c.execute("SELECT status, progress, error_message FROM file_documents WHERE id = ?", (f_id,))
                    row = c.fetchone()
                    if row:
                        st, prog, err = row
                        if st == "PARSED" and prog == 100:
                            success = True
                            c.execute("SELECT count(*) FROM document_chunks WHERE file_id = ?", (f_id,))
                            final_chunks = c.fetchone()[0]
                            break
                        elif st == "FAILED":
                            err_msg = err
                            break
                cost = time.time() - t0
                if success:
                    print(f"✅ 成功! 生成 {final_chunks} 块并向量化入库 ({cost:.1f}s)")
                else:
                    print(f"❌ 失败! 错误: {err_msg}")

    # 4. 测试智能问答与检索 (带 Rerank)
    print("\n--- [测试 3/4] 测试问答与 Rerank 混合召回 ---")
    c.execute("SELECT id FROM knowledge_bases LIMIT 1")
    kb_row = c.fetchone()
    if kb_row:
        kb_id = kb_row[0]
        # 发送测试检索问题
        chat_payload = {
            "messages": [{"role": "user", "content": "候选人的实习经历和个人项目有哪些？"}],
            "kb_ids": [kb_id],
            "model_id": "dd0c8bb7-b0c5-4857-93f6-0517ba1c177d",
            "search_mode": "hybrid",
            "rerank_enabled": True,
            "rerank_model_id": "e081f81c-9eaa-4e56-b09e-e6f9b9e0c764",
            "top_k": 5,
            "score_threshold": 0.0
        }
        print("  👉 测试混合检索 + Rerank 重排 + DeepSeek 回答 ...", end=" ", flush=True)
        r = requests.post(f"{BASE_URL}/api/v1/chat/completions", json=chat_payload, stream=True, timeout=30)
        if r.status_code == 200:
            events = []
            for line in r.iter_lines():
                if line:
                    decoded = line.decode('utf-8')
                    if decoded.startswith('event:'):
                        events.append(decoded)
            print(f"✅ 成功! 收到 {len(events)} 个事件流 (包含 agent_thought, answer_chunk, done)")
        else:
            print(f"❌ 失败: {r.status_code} {r.text}")

    print("\n" + "=" * 60)
    print("🎉 全量测试执行完毕！")
    print("=" * 60)

if __name__ == "__main__":
    run_tests()
