#!/usr/bin/env python3
"""
按 PostgreSQL 当前 chunks 全量重建个人知识库的 Chroma collection。

背景：
- 重灌简历时脚本从仓库根目录运行，CHROMA_DB_DIR=./storage/... 落到了根目录，
  主向量库仍是旧的 209 条，和 PG 的 219 个 chunk 不一致；
- 本脚本强制 chdir 到 backend，确保使用 backend/storage/chroma_db；
- 清空并重建 kb_6d3e... collection，重新 embedding 全部 219 个 chunk。
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT / "backend"
# 关键：先切到 backend，保证 ./storage/chroma_db 指向主库
os.chdir(BACKEND_DIR)
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlmodel import Session, select  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.database import engine  # noqa: E402
from app.models import DocumentChunk, FileDocument  # noqa: E402
from app.services.embedding import EmbeddingService  # noqa: E402
from app.services.vector_store import VectorStoreService  # noqa: E402

settings = get_settings()
engine.echo = False
KB_ID = "6d3e18a1-f70a-4acc-80a6-65eaea9a7a69"


async def main() -> int:
    vector_store = VectorStoreService()
    embedder = EmbeddingService()

    with Session(engine) as session:
        rows = session.exec(
            select(DocumentChunk, FileDocument.name)
            .join(FileDocument, DocumentChunk.file_id == FileDocument.id)
            .where(FileDocument.kb_id == KB_ID)
            .order_by(FileDocument.name, DocumentChunk.original_index)
        ).all()
        if not rows:
            print("[错误] PG 中该 KB 没有 chunks", file=sys.stderr)
            return 2
        print(f"[1/3] PG chunks={len(rows)}; Chroma 当前={vector_store.get_count(KB_ID)}")
        print(f"[1/3] CHROMA_DB_DIR={settings.CHROMA_DB_DIR} cwd={os.getcwd()}")

        vector_store.delete_collection(KB_ID)
        vector_store.create_collection(KB_ID)
        print("[2/3] collection 已重建，开始 embedding")

        ids = [chunk.id for chunk, _ in rows]
        docs = [chunk.content for chunk, _ in rows]
        metadatas = [
            {
                "file_id": chunk.file_id,
                "file_name": file_name,
                "kb_id": KB_ID,
                "chunk_index": chunk.original_index,
            }
            for chunk, file_name in rows
        ]

        embeddings = []
        for start in range(0, len(docs), 32):
            batch = docs[start:start + 32]
            vectors = await embedder.embed_documents(batch)
            embeddings.extend(vectors)
            print(f"  embedded {min(start + len(batch), len(docs))}/{len(docs)}", flush=True)

        vector_store.add_documents(
            kb_id=KB_ID,
            documents=[
                {"id": cid, "content": doc, "metadata": meta}
                for cid, doc, meta in zip(ids, docs, metadatas)
            ],
            embeddings=embeddings,
        )

        count = vector_store.get_count(KB_ID)
        print(f"[3/3] Chroma count={count} (expect {len(rows)})")
        return 0 if count == len(rows) else 3


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
