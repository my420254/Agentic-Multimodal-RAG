#!/usr/bin/env python3
"""
把现有 Chroma collection 中的向量回填到 PostgreSQL document_chunks.embedding。
只做数据迁移，不重新调用 embedding API。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
os.chdir(BACKEND)
sys.path.insert(0, str(BACKEND))

import chromadb  # noqa: E402
from sqlmodel import Session, select, func  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.database import engine  # noqa: E402
from app.models import DocumentChunk, FileDocument, KnowledgeBase  # noqa: E402

settings = get_settings()


def main() -> int:
    client = chromadb.PersistentClient(path=settings.CHROMA_DB_DIR)
    with Session(engine) as session:
        kbs = session.exec(select(KnowledgeBase)).all()
        by_collection = {f"kb_{kb.id.replace('-', '_')}": kb.id for kb in kbs}
        total_updated = 0
        total_missing = 0

        for collection in client.list_collections():
            if collection.count() == 0:
                continue
            kb_id = by_collection.get(collection.name)
            if not kb_id:
                print(f"[skip] collection={collection.name} (no matching KB)")
                continue
            data = collection.get(include=["embeddings"])
            ids = data.get("ids") or []
            embeddings = data.get("embeddings")
            if embeddings is None:
                print(f"[skip] collection={collection.name} has no embeddings")
                continue
            updated = 0
            missing = 0
            for i, chunk_id in enumerate(ids):
                chunk = session.get(DocumentChunk, chunk_id)
                if not chunk:
                    missing += 1
                    continue
                chunk.embedding = [float(x) for x in embeddings[i]]
                session.add(chunk)
                updated += 1
                if updated % 50 == 0:
                    session.commit()
            session.commit()
            total_updated += updated
            total_missing += missing
            print(f"[ok] {collection.name} -> kb={kb_id}: updated={updated} missing={missing}")

        print(f"\nTOTAL updated={total_updated} missing={total_missing}")
        print("\ncoverage per KB:")
        for kb in kbs:
            total = session.exec(
                select(func.count())
                .select_from(DocumentChunk)
                .join(FileDocument, DocumentChunk.file_id == FileDocument.id)
                .where(FileDocument.kb_id == kb.id)
            ).one()
            with_vec = session.exec(
                select(func.count())
                .select_from(DocumentChunk)
                .join(FileDocument, DocumentChunk.file_id == FileDocument.id)
                .where(FileDocument.kb_id == kb.id, DocumentChunk.embedding.isnot(None))
            ).one()
            if total:
                print(f"  {kb.id} ({kb.name}): {with_vec}/{total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
