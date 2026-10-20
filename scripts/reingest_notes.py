#!/usr/bin/env python3
"""把个人材料库里 75k 字符的论文笔记重新切成 500/50 chunk。

背景：legacy 迁移把 HiPro-LoRA.md 整个文件当成 1 个 chunk，BGE-M3 无法有效
编码，论文事实题检索必然差。本脚本只重切这一份文件，不动 PDF/DOCX 和
实习笔记；完成后重建整个 KB 的 BM25 与 pgvector 向量。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlmodel import Session, delete, select  # noqa: E402

from app.core.database import engine  # noqa: E402
from app.models import (  # noqa: E402
    ChunkIndex,
    ContentType,
    DocumentChunk,
    FileDocument,
    FileStatus,
    IndexStats,
    KnowledgeBase,
    generate_uuid,
)
from app.services.bm25 import BM25Index  # noqa: E402
from app.services.embedding import EmbeddingService  # noqa: E402
from app.services.parser import FileParser  # noqa: E402
from app.services.vector_store import VectorStoreService  # noqa: E402

KB_ID = "6d3e18a1-f70a-4acc-80a6-65eaea9a7a69"
TARGET_NAME = "HiPro-LoRA.md"
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50


def _content_type(raw: str) -> ContentType:
    try:
        return ContentType(str(raw).upper())
    except ValueError:
        return ContentType.TEXT


async def main() -> int:
    engine.echo = False
    embedder = EmbeddingService()
    vector_store = VectorStoreService()

    with Session(engine) as session:
        kb = session.get(KnowledgeBase, KB_ID)
        if kb is None:
            print(f"[错误] KB 不存在: {KB_ID}", file=sys.stderr)
            return 2

        file_doc = session.exec(
            select(FileDocument).where(
                FileDocument.kb_id == KB_ID,
                FileDocument.name == TARGET_NAME,
            )
        ).first()
        if file_doc is None:
            print(f"[错误] 文件不存在: {TARGET_NAME}", file=sys.stderr)
            return 2

        old_chunks = session.exec(
            select(DocumentChunk).where(DocumentChunk.file_id == file_doc.id)
        ).all()
        old_ids = [c.id for c in old_chunks]
        print(f"[{file_doc.name}] old chunks={len(old_chunks)}")

        # 1. 清理旧 BM25 / PG chunks / Chroma vectors
        if old_ids:
            session.exec(delete(ChunkIndex).where(ChunkIndex.chunk_id.in_(old_ids)))
        for chunk in old_chunks:
            session.delete(chunk)
        session.commit()
        vector_store.delete_by_file_id(KB_ID, file_doc.id)

        # 2. 重新切分
        parser = FileParser(kb_id=KB_ID)
        parsed = parser.parse(
            file_doc.local_path,
            chunk_mode="custom",
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
        )
        parsed = [c for c in parsed if c.content and c.content.strip()]
        print(
            f"[{file_doc.name}] new chunks={len(parsed)} "
            f"avg={sum(len(c.content) for c in parsed) / max(1, len(parsed)):.0f}"
        )

        # 3. 写 PG
        new_chunks = []
        for idx, parsed_chunk in enumerate(parsed):
            chunk = DocumentChunk(
                id=generate_uuid(),
                file_id=file_doc.id,
                content=parsed_chunk.content,
                page_number=parsed_chunk.page_number,
                content_type=_content_type(parsed_chunk.content_type),
                image_path=parsed_chunk.image_path,
                original_index=idx,
                parent_id=None,
                heading_level=getattr(parsed_chunk, "heading_level", None),
                heading_text=getattr(parsed_chunk, "heading_text", None),
                chunk_type=getattr(parsed_chunk, "chunk_type", "content") or "content",
                token_count=parsed_chunk.token_count or 0,
            )
            new_chunks.append(chunk)
            session.add(chunk)

        file_doc.status = FileStatus.READY
        file_doc.progress = 100
        file_doc.error_message = None
        session.add(file_doc)
        session.commit()

        # 4. 批量 embedding + 写 Chroma / pgvector
        embeddings = []
        for start in range(0, len(new_chunks), 32):
            batch = new_chunks[start : start + 32]
            embeddings.extend(await embedder.embed_documents([c.content for c in batch]))
        vector_store.add_documents(
            kb_id=KB_ID,
            documents=[
                {
                    "id": c.id,
                    "content": c.content,
                    "metadata": {
                        "file_id": file_doc.id,
                        "file_name": file_doc.name,
                        "kb_id": KB_ID,
                        "chunk_index": c.original_index,
                    },
                }
                for c in new_chunks
            ],
            embeddings=embeddings,
        )
        print(f"[{file_doc.name}] PG + Chroma 写入完成: {len(new_chunks)} chunks")

        # 5. 重建整个 KB 的 BM25
        session.exec(delete(ChunkIndex).where(ChunkIndex.kb_id == KB_ID))
        session.exec(delete(IndexStats).where(IndexStats.kb_id == KB_ID))
        session.commit()

        all_chunks = session.exec(
            select(DocumentChunk)
            .join(FileDocument, DocumentChunk.file_id == FileDocument.id)
            .where(FileDocument.kb_id == KB_ID)
        ).all()
        bm25 = BM25Index()
        for chunk in all_chunks:
            bm25.index_chunk(session, chunk.id, chunk.content, KB_ID)
        session.commit()

        kb.chunk_count = len(all_chunks)
        session.add(kb)
        session.commit()
        print(f"[完成] KB chunks={len(all_chunks)}")
        print(f"[验证] Chroma count={vector_store.get_count(KB_ID)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
