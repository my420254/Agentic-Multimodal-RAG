#!/usr/bin/env python3
"""
用 500 字/50 overlap 重切两封重复简历（PDF/DOCX），重灌 PostgreSQL + Chroma + BM25。

不动 local.db、不动笔记原切块；仅替换 PDF/DOCX 的旧 chunk。
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
RESUME_NAMES = ("辽宁大学_27届_张梦洋.pdf", "辽宁大学_27届_张梦洋.docx")
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

        files = session.exec(
            select(FileDocument).where(
                FileDocument.kb_id == KB_ID,
                FileDocument.name.in_(RESUME_NAMES),
            )
        ).all()
        if len(files) != 2:
            print(f"[错误] 期望 2 个简历文件，实际 {len(files)}", file=sys.stderr)
            return 2

        for file_doc in files:
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

            # 3. 写 PG（先生成稳定 id）
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
                    heading_level=None,
                    heading_text=None,
                    chunk_type="content",
                    token_count=parsed_chunk.token_count or 0,
                )
                new_chunks.append(chunk)
                session.add(chunk)

            file_doc.status = FileStatus.READY
            file_doc.progress = 100
            file_doc.error_message = None
            session.add(file_doc)
            session.commit()

            # 4. 批量 embedding + 写 Chroma
            embeddings = []
            for start in range(0, len(new_chunks), 32):
                batch = new_chunks[start:start + 32]
                embeddings.extend(
                    await embedder.embed_documents([c.content for c in batch])
                )
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

        # 5. 重建整个 KB 的 BM25（笔记 202 + 简历 16 左右）
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
        print(
            f"[完成] KB chunks={len(all_chunks)} (expected notes 202 + HiPro 1 + pdf 7 + docx 9 = 219)"
        )
        print(f"[验证] Chroma count={vector_store.get_count(KB_ID)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
