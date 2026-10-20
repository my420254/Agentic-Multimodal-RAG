#!/usr/bin/env python3
"""
把 legacy `backend/local.db` 里的个人资料知识库迁移到 PostgreSQL。

背景：
- 4 份真实上传材料在 backend/storage/uploads/...，但 PostgreSQL 里只有 SRE 文档；
- legacy local.db 保存了这 4 个文件的 209 个 chunk，Chroma 里也已有 209 条向量；
- 因此本脚本只做元数据/chunk 迁移 + BM25 重建，不重新调用 embedding，不删除 local.db。

用法：
    cd /home/yang/Agentic-Multimodal-RAG
    JWT_SECRET=... python3 scripts/migrate_personal_kb.py
"""

from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlmodel import Session, select  # noqa: E402

from app.core.database import engine  # noqa: E402
from app.models import (  # noqa: E402
    ContentType,
    DocumentChunk,
    FileDocument,
    FileStatus,
    KnowledgeBase,
    User,
)
from app.services.bm25 import BM25Index  # noqa: E402

LEGACY_DB = BACKEND_DIR / "local.db"
KB_ID = "6d3e18a1-f70a-4acc-80a6-65eaea9a7a69"
# 真实知识库名称只在本地设置，不写进仓库
KB_NAME = os.environ.get("PERSONAL_KB_NAME", "个人简历与项目材料")
EXPECTED_CHUNKS = 209


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _content_type(value: str | None) -> ContentType:
    try:
        return ContentType(str(value).upper())
    except ValueError:
        return ContentType.TEXT


def load_legacy() -> tuple[sqlite3.Row, list[sqlite3.Row], list[sqlite3.Row]]:
    if not LEGACY_DB.exists():
        raise FileNotFoundError(f"legacy 数据库不存在: {LEGACY_DB}")

    conn = sqlite3.connect(f"file:{LEGACY_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    kb = conn.execute(
        "select * from knowledge_bases where id = ?", (KB_ID,)
    ).fetchone()
    if kb is None:
        raise RuntimeError(f"legacy 中找不到知识库 {KB_ID}")

    files = conn.execute(
        "select * from file_documents where kb_id = ? order by name", (KB_ID,)
    ).fetchall()
    chunks = conn.execute(
        """
        select c.* from document_chunks c
        join file_documents f on f.id = c.file_id
        where f.kb_id = ?
        order by c.file_id, c.original_index
        """,
        (KB_ID,),
    ).fetchall()
    conn.close()
    return kb, files, chunks


def main() -> int:
    kb_row, file_rows, chunk_rows = load_legacy()

    if len(chunk_rows) != EXPECTED_CHUNKS:
        print(
            f"[拒绝] legacy chunk 数量为 {len(chunk_rows)}，预期 {EXPECTED_CHUNKS}；"
            "为避免半迁移，脚本停止。",
            file=sys.stderr,
        )
        return 2

    with Session(engine) as session:
        existing = session.get(KnowledgeBase, KB_ID)
        if existing is not None:
            existing_chunks = session.exec(
                select(DocumentChunk)
                .join(FileDocument, DocumentChunk.file_id == FileDocument.id)
                .where(FileDocument.kb_id == KB_ID)
            ).all()
            if len(existing_chunks) == EXPECTED_CHUNKS:
                print(f"[跳过] PostgreSQL 中已存在 {KB_ID}（{len(existing_chunks)} chunks）")
                return 0
            print(
                f"[修复] PostgreSQL 中已有不完整记录（{len(existing_chunks)} chunks），"
                "将清理该 KB 后重建。"
            )
            for chunk in existing_chunks:
                session.delete(chunk)
            for file_doc in session.exec(
                select(FileDocument).where(FileDocument.kb_id == KB_ID)
            ).all():
                session.delete(file_doc)
            session.delete(existing)
            session.commit()

        created_at = _dt(kb_row["created_at"]) or datetime.now(timezone.utc)
        updated_at = _dt(kb_row["updated_at"]) or created_at
        owner = session.exec(select(User).where(User.student_id == "2023001")).first()
        owner_id = str(owner.id) if owner else None

        kb = KnowledgeBase(
            id=KB_ID,
            name=KB_NAME,
            description="用户提供的 4 份真实材料：PDF/DOCX 简历、实习项目笔记、HiPro-LoRA 论文笔记。",
            owner_id=owner_id,
            # 原库使用 SiliconFlow BGE-M3；系统 embedding 也是同一模型，避免把 API Key 复制进 PG。
            embedding_model="sys_embedding",
            vlm_model="default",
            chunk_count=EXPECTED_CHUNKS,
            is_deleted=False,
            created_at=created_at,
            updated_at=updated_at,
        )
        session.add(kb)

        for row in file_rows:
            legacy_path = row["local_path"]
            # legacy 的 ./storage/... 是相对 backend 的路径，这里落绝对路径，前端/解析器都可直接打开。
            path = Path(legacy_path)
            if not path.is_absolute():
                path = (BACKEND_DIR / path).resolve()
            if not path.exists():
                raise FileNotFoundError(f"上传文件不存在: {path}")

            session.add(
                FileDocument(
                    id=row["id"],
                    kb_id=KB_ID,
                    name=row["name"],
                    local_path=str(path),
                    size=_int(row["size"]),
                    status=FileStatus.READY,
                    progress=100,
                    error_message=None,
                    created_at=_dt(row["created_at"]) or created_at,
                    updated_at=_dt(row["updated_at"]) or updated_at,
                )
            )

        for row in chunk_rows:
            session.add(
                DocumentChunk(
                    id=row["id"],
                    file_id=row["file_id"],
                    content=row["content"] or "",
                    page_number=_int(row["page_number"], 0) or None,
                    content_type=_content_type(row["content_type"]),
                    image_path=row["image_path"] or None,
                    original_index=_int(row["original_index"]),
                    created_at=_dt(row["created_at"]) or created_at,
                    parent_id=row["parent_id"] or None,
                    heading_level=_int(row["heading_level"]) or None,
                    heading_text=row["heading_text"] or None,
                    chunk_type=row["chunk_type"] or "content",
                    token_count=_int(row["token_count"]),
                )
            )

        session.commit()
        print(f"[完成] KB 写入: {KB_ID} / {KB_NAME}")
        print(f"[完成] files={len(file_rows)} chunks={len(chunk_rows)}")

        # 重建 BM25（纯本地计算，不调用模型）
        bm25 = BM25Index()
        chunks = session.exec(
            select(DocumentChunk)
            .join(FileDocument, DocumentChunk.file_id == FileDocument.id)
            .where(FileDocument.kb_id == KB_ID)
        ).all()
        for chunk in chunks:
            bm25.index_chunk(session, chunk.id, chunk.content, KB_ID)
        session.commit()
        print(f"[完成] BM25 索引重建: {len(chunks)} docs")

    print(f"[验证] PostgreSQL 文件: {ROOT}")
    print("[提示] Chroma 向量未改动；查询用系统 BAAI/bge-m3，与原 SiliconFlow BGE-M3 兼容。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
