# -*- coding: utf-8 -*-
"""
真实企业级 SRE 排障数据入库脚本
目标：将 4 份生产级 SRE / 云原生排障 SOP 存入 PostgreSQL 与向量库
构建真实的知识库资产，替换掉个人简历测试数据。
"""

import sys
import os
import glob
import uuid
import re
from datetime import datetime, timezone

sys.path.insert(0, "/home/yang/Agentic-Multimodal-RAG/backend")
os.chdir("/home/yang/Agentic-Multimodal-RAG/backend")

from sqlmodel import Session, select
from app.core.database import engine, init_db
from app.models import KnowledgeBase, FileDocument, DocumentChunk, FileStatus, ContentType
from app.services.embedding import EmbeddingService
from app.services.vector_store import VectorStoreService
from app.services.bm25 import get_bm25_index

KB_ID = "kb_sre_enterprise"
KB_NAME = "云原生SRE排障与高可用架构知识库"
KB_DESC = "包含生产级 Kubernetes OOMKilled/CrashLoopBackOff、Redis 分布式缓存故障转移、PostgreSQL 慢查询死锁治理与企业级 AI Agent 安全防越狱 SOP。"
DOC_DIR = "/home/yang/Agentic-Multimodal-RAG/data/enterprise_sre_sop"


def split_markdown_into_chunks(text: str, chunk_size: int = 500, overlap: int = 50):
    """按标题与段落语义切分 Markdown 文档"""
    sections = re.split(r'\n(?=#{1,3}\s+)', text)
    chunks = []
    
    for sec in sections:
        sec = sec.strip()
        if not sec:
            continue
        
        # 提取标题
        heading_match = re.match(r'^(#{1,3})\s+(.+)', sec)
        heading_level = len(heading_match.group(1)) if heading_match else None
        heading_text = heading_match.group(2).strip() if heading_match else None
        
        if len(sec) <= chunk_size:
            chunks.append({
                "content": sec,
                "heading_level": heading_level,
                "heading_text": heading_text
            })
        else:
            # 较长段落按自然换行或句号切分
            paragraphs = sec.split('\n\n')
            current_chunk = []
            current_len = 0
            for p in paragraphs:
                p_len = len(p)
                if current_len + p_len > chunk_size and current_chunk:
                    chunk_text = "\n\n".join(current_chunk)
                    chunks.append({
                        "content": chunk_text,
                        "heading_level": heading_level,
                        "heading_text": heading_text
                    })
                    # 简单 overlap: 保留最后一个段落
                    current_chunk = [current_chunk[-1]] if len(current_chunk) > 1 else []
                    current_len = len(current_chunk[0]) if current_chunk else 0
                current_chunk.append(p)
                current_len += p_len
            
            if current_chunk:
                chunks.append({
                    "content": "\n\n".join(current_chunk),
                    "heading_level": heading_level,
                    "heading_text": heading_text
                })

    return chunks


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default=None, help="只入库指定文件名，例如 05_xxx.md")
    args = parser.parse_args()

    print("🚀 [Ingest] 开始真实企业级 SRE 知识库初始化...")
    init_db()
    
    embedding_service = EmbeddingService()
    vector_store = VectorStoreService()
    bm25_service = get_bm25_index()
    
    with Session(engine) as session:
        # 1. 查找或创建知识库
        kb = session.get(KnowledgeBase, KB_ID)
        if not kb:
            kb = KnowledgeBase(
                id=KB_ID,
                name=KB_NAME,
                description=KB_DESC,
                embedding_model="BAAI/bge-m3",
                vlm_model="Qwen/Qwen3-VL-8B-Instruct",
                chunk_count=0,
                is_deleted=False
            )
            session.add(kb)
            session.commit()
            print(f"✅ 知识库创建成功: {KB_NAME} ({KB_ID})")
        else:
            print(f"ℹ️ 知识库已存在: {KB_NAME} ({KB_ID})")

        # 2. 遍历扫描所有 SOP 文档（支持 --only 单文件更新）
        md_files = glob.glob(os.path.join(DOC_DIR, "*.md"))
        if args.only:
            md_files = [p for p in md_files if os.path.basename(p) == args.only]
        if not md_files:
            print(f"❌ 没有找到待入库文档: {args.only or DOC_DIR}")
            return 2
        print(f"📂 发现 {len(md_files)} 份企业级 SOP 文档待入库: {md_files}")
        
        all_doc_chunks = []
        all_vector_docs = []
        all_embeddings = []
        
        for file_path in sorted(md_files):
            file_name = os.path.basename(file_path)
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            file_id = f"doc_{uuid.uuid5(uuid.NAMESPACE_DNS, file_name).hex[:12]}"
            
            # 检查文件是否已存在
            file_doc = session.get(FileDocument, file_id)
            if file_doc:
                print(f"🔄 文件已存在，执行更新: {file_name}")
                # 清理旧 chunk
                old_chunks = session.exec(select(DocumentChunk).where(DocumentChunk.file_id == file_id)).all()
                for oc in old_chunks:
                    session.delete(oc)
                session.commit()
            else:
                file_doc = FileDocument(
                    id=file_id,
                    kb_id=KB_ID,
                    name=file_name,
                    local_path=file_path,
                    size=len(content),
                    status=FileStatus.PARSED,
                    progress=100
                )
                session.add(file_doc)
                session.commit()

            # 切分 Chunks
            raw_chunks = split_markdown_into_chunks(content, chunk_size=500, overlap=50)
            print(f"📄 [{file_name}] 切分为 {len(raw_chunks)} 个切片")

            # 批量生成 Embedding (异步调用)
            chunk_texts = [c["content"] for c in raw_chunks]
            print(f"⚡ [{file_name}] 正在调用 Embedding API ({len(chunk_texts)} chunks)...")
            vectors = await embedding_service.embed_documents(chunk_texts)
            
            for idx, (c_data, vec) in enumerate(zip(raw_chunks, vectors)):
                chunk_id = f"chk_{file_id}_{idx:03d}"
                c_obj = DocumentChunk(
                    id=chunk_id,
                    file_id=file_id,
                    content=c_data["content"],
                    page_number=1,
                    content_type=ContentType.TEXT,
                    original_index=idx,
                    heading_level=c_data["heading_level"],
                    heading_text=c_data["heading_text"],
                    token_count=len(c_data["content"])
                )
                session.add(c_obj)
                
                all_vector_docs.append({
                    "id": chunk_id,
                    "content": c_data["content"],
                    "metadata": {
                        "file_id": file_id,
                        "file_name": file_name,
                        "kb_id": KB_ID,
                        "heading": c_data["heading_text"] or "",
                        "index": idx
                    }
                })
                all_embeddings.append(vec)

                # 4. 实时构建 BM25 倒排索引
                bm25_service.index_chunk(session, chunk_id, c_data["content"], KB_ID)

            file_doc.status = FileStatus.READY
            session.commit()

        # 3. 写入向量库
        print(f"📦 [ChromaDB] 正在将 {len(all_vector_docs)} 条切片向量写入 Collection...")
        vector_store.create_collection(KB_ID)
        vector_store.add_documents(KB_ID, all_vector_docs, all_embeddings)
        print("✅ 向量库写入成功！")

        # 5. 更新知识库总切片数
        total_chunks = session.exec(select(DocumentChunk).join(FileDocument).where(FileDocument.kb_id == KB_ID)).all()
        kb.chunk_count = len(total_chunks)
        session.commit()
        print(f"🎉 真实知识库入库完成！知识库 ID: {KB_ID}, 总切片数: {kb.chunk_count}")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
