#!/usr/bin/env python3
"""
把 `data/真实简历` 的 4 份 PDF + 9 张 JPG 真正入库。

- PDF：PyMuPDF 文本 → 500 字切块；
- JPG：Qwen3-VL 逐字 OCR → 600 字切块，保留 image_path 供前端点回图片；
- PostgreSQL 存 chunk，Chroma 存向量，BM25 重建；
- 不删除源文件；重复运行会重建 kb_real_resumes。
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT / "backend"
SOURCE_DIR = ROOT / "data" / "真实简历"
os.chdir(BACKEND_DIR)
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import httpx  # noqa: E402
from sqlmodel import Session, delete, select  # noqa: E402

from app.core.config import get_settings  # noqa: E402
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
from app.services.parser import FileParser, TextSplitter  # noqa: E402
from app.services.vector_store import VectorStoreService  # noqa: E402

settings = get_settings()
engine.echo = False

KB_ID = "kb_real_resumes"
KB_NAME = "真实简历库（4 份 PDF + 9 张图片）"
UPLOAD_DIR = BACKEND_DIR / "storage" / "uploads" / KB_ID
IMAGE_DIR = BACKEND_DIR / "storage" / "images" / KB_ID
CORPUS_PATH = BACKEND_DIR / "benchmark" / "real_resumes_corpus.json"
PDF_CHUNK_SIZE = 500
PDF_CHUNK_OVERLAP = 50
OCR_CHUNK_SIZE = 600
OCR_CHUNK_OVERLAP = 80

OCR_PROMPT = (
    "请逐字提取这张中文简历图片中的全部文字，按原有结构输出：姓名、联系方式、教育背景（学校/专业/时间）、"
    "实习/工作经历（公司/岗位/时间）、项目经历（项目名/职责/技术/数字）、技能、论文/奖项。"
    "不要总结、不要编造；图片里没有的留空。只输出简历文字本身。"
)


def _dt_now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


async def ocr_image(client: httpx.AsyncClient, path: Path, semaphore: asyncio.Semaphore) -> str:
    async with semaphore:
        b64 = base64.b64encode(path.read_bytes()).decode()
        last_err: Exception | None = None
        for attempt in range(1, 4):
            try:
                start = time.time()
                response = await client.post(
                    f"{settings.VLM_BASE_URL}/chat/completions",
                    headers={"Authorization": f"Bearer {settings.VLM_API_KEY}"},
                    json={
                        "model": settings.VLM_MODEL,
                        "messages": [
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": OCR_PROMPT},
                                    {
                                        "type": "image_url",
                                        "image_url": {
                                            "url": f"data:image/jpeg;base64,{b64}"
                                        },
                                    },
                                ],
                            }
                        ],
                        "max_tokens": 2200,
                        "temperature": 0.0,
                    },
                )
                if response.status_code != 200:
                    raise RuntimeError(f"VLM {response.status_code}: {response.text[:300]}")
                text = response.json()["choices"][0]["message"]["content"].strip()
                if not text or "图片解析失败" in text:
                    raise RuntimeError("VLM 返回空文本")
                print(f"  [OCR] {path.name}: {len(text)} chars in {time.time()-start:.1f}s", flush=True)
                return text
            except Exception as exc:
                last_err = exc
                print(f"  [OCR] {path.name} attempt {attempt} failed: {exc}", flush=True)
                await asyncio.sleep(2 * attempt)
        raise RuntimeError(f"OCR 失败: {path.name}: {last_err}")


def _split_ocr(text: str) -> List[str]:
    splitter = TextSplitter(chunk_size=OCR_CHUNK_SIZE, chunk_overlap=OCR_CHUNK_OVERLAP)
    parts = splitter.split(text)
    return [p.strip() for p in parts if p.strip()]


async def main() -> int:
    if not SOURCE_DIR.exists():
        print(f"[错误] 源目录不存在: {SOURCE_DIR}", file=sys.stderr)
        return 2

    pdfs = sorted(SOURCE_DIR.glob("*.pdf"))
    images = sorted(
        p for p in SOURCE_DIR.iterdir()
        if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    )
    if not pdfs or not images:
        print(f"[错误] 需要 PDF 和图片；pdf={len(pdfs)} images={len(images)}", file=sys.stderr)
        return 2

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)

    # 0. 清理旧的 kb_real_resumes（只清这个 KB 的派生数据，不碰源文件）
    with Session(engine) as session:
        old_kb = session.get(KnowledgeBase, KB_ID)
        if old_kb is not None:
            old_files = session.exec(
                select(FileDocument).where(FileDocument.kb_id == KB_ID)
            ).all()
            old_file_ids = [f.id for f in old_files]
            old_chunks = session.exec(
                select(DocumentChunk).where(DocumentChunk.file_id.in_(old_file_ids))
            ).all() if old_file_ids else []
            old_chunk_ids = [c.id for c in old_chunks]
            if old_chunk_ids:
                session.exec(delete(ChunkIndex).where(ChunkIndex.chunk_id.in_(old_chunk_ids)))
            for c in old_chunks:
                session.delete(c)
            for f in old_files:
                session.delete(f)
            session.exec(delete(IndexStats).where(IndexStats.kb_id == KB_ID))
            session.delete(old_kb)
            session.commit()
            VectorStoreService().delete_collection(KB_ID)
            print(f"[清理] 旧 {KB_ID}: files={len(old_files)} chunks={len(old_chunks)}")

    # 1. VLM OCR 9 张图片（并发 3）
    image_texts: Dict[str, str] = {}
    async with httpx.AsyncClient(timeout=180.0, verify=False, trust_env=True) as client:
        semaphore = asyncio.Semaphore(3)
        tasks = {p.name: asyncio.create_task(ocr_image(client, p, semaphore)) for p in images}
        for name, task in tasks.items():
            image_texts[name] = await task

    # 2. 建 KB + 文件记录 + chunks
    vector_store = VectorStoreService()
    embedder = EmbeddingService()
    vector_store.create_collection(KB_ID)

    corpus: List[Dict[str, Any]] = []
    all_chunk_rows: List[DocumentChunk] = []
    file_rows: List[FileDocument] = []

    with Session(engine) as session:
        kb = KnowledgeBase(
            id=KB_ID,
            name=KB_NAME,
            description="用户提供的真实简历：4 份 PDF + 9 张 JPG（含图片 OCR），用于求职诊断与 RAG。",
            embedding_model="sys_embedding",
            vlm_model=settings.VLM_MODEL,
            chunk_count=0,
            is_deleted=False,
            created_at=_dt_now(),
            updated_at=_dt_now(),
        )
        session.add(kb)
        session.commit()

        # 2.1 PDF
        for source in pdfs:
            file_id = generate_uuid()
            dest = UPLOAD_DIR / f"{file_id}_{source.name}"
            shutil.copy2(source, dest)
            parser = FileParser(kb_id=KB_ID)
            parsed = parser.parse(
                str(dest),
                chunk_mode="custom",
                chunk_size=PDF_CHUNK_SIZE,
                chunk_overlap=PDF_CHUNK_OVERLAP,
            )
            text_chunks = [
                c for c in parsed
                if c.content_type != "image" and c.content and c.content.strip()
            ]
            file_doc = FileDocument(
                id=file_id,
                kb_id=KB_ID,
                name=source.name,
                local_path=str(dest),
                size=dest.stat().st_size,
                status=FileStatus.READY,
                progress=100,
                created_at=_dt_now(),
                updated_at=_dt_now(),
            )
            file_rows.append(file_doc)
            session.add(file_doc)
            for idx, parsed_chunk in enumerate(text_chunks):
                chunk = DocumentChunk(
                    id=generate_uuid(),
                    file_id=file_id,
                    content=parsed_chunk.content,
                    page_number=parsed_chunk.page_number,
                    content_type=ContentType.TEXT,
                    image_path=None,
                    original_index=idx,
                    chunk_type="pdf_text",
                    token_count=parsed_chunk.token_count or 0,
                )
                all_chunk_rows.append(chunk)
                session.add(chunk)
                corpus.append(
                    {
                        "file": source.name,
                        "kind": "pdf",
                        "chunk_index": idx,
                        "text": parsed_chunk.content,
                    }
                )
            print(f"[PDF] {source.name}: chunks={len(text_chunks)}", flush=True)

        # 2.2 JPG（OCR 文本切块）
        for source in images:
            file_id = generate_uuid()
            dest = UPLOAD_DIR / f"{file_id}_{source.name}"
            shutil.copy2(source, dest)
            image_dest = IMAGE_DIR / f"{file_id}{source.suffix.lower()}"
            shutil.copy2(source, image_dest)
            relative_image = f"{KB_ID}/{image_dest.name}"

            ocr_text = image_texts[source.name]
            parts = _split_ocr(ocr_text)
            file_doc = FileDocument(
                id=file_id,
                kb_id=KB_ID,
                name=source.name,
                local_path=str(dest),
                size=dest.stat().st_size,
                status=FileStatus.READY,
                progress=100,
                created_at=_dt_now(),
                updated_at=_dt_now(),
            )
            file_rows.append(file_doc)
            session.add(file_doc)
            for idx, part in enumerate(parts):
                chunk = DocumentChunk(
                    id=generate_uuid(),
                    file_id=file_id,
                    content=part,
                    page_number=1,
                    content_type=ContentType.IMAGE,
                    image_path=relative_image,
                    original_index=idx,
                    chunk_type="image_ocr",
                    token_count=0,
                )
                all_chunk_rows.append(chunk)
                session.add(chunk)
                corpus.append(
                    {
                        "file": source.name,
                        "kind": "image_ocr",
                        "chunk_index": idx,
                        "text": part,
                        "image_path": relative_image,
                    }
                )
            print(f"[IMG] {source.name}: ocr_chars={len(ocr_text)} chunks={len(parts)}", flush=True)

        session.commit()

        # 3. embedding + Chroma
        embeddings = []
        for start in range(0, len(all_chunk_rows), 32):
            batch = all_chunk_rows[start:start + 32]
            embeddings.extend(await embedder.embed_documents([c.content for c in batch]))
            print(f"[EMB] {min(start+32, len(all_chunk_rows))}/{len(all_chunk_rows)}", flush=True)

        vector_store.add_documents(
            kb_id=KB_ID,
            documents=[
                {
                    "id": c.id,
                    "content": c.content,
                    "metadata": {
                        "file_id": c.file_id,
                        "kb_id": KB_ID,
                        "chunk_index": c.original_index,
                    },
                }
                for c in all_chunk_rows
            ],
            embeddings=embeddings,
        )

        # 4. BM25
        bm25 = BM25Index()
        for chunk in all_chunk_rows:
            bm25.index_chunk(session, chunk.id, chunk.content, KB_ID)
        session.commit()

        kb.chunk_count = len(all_chunk_rows)
        kb.updated_at = _dt_now()
        session.add(kb)
        session.commit()

        CORPUS_PATH.write_text(
            json.dumps(
                {
                    "kb_id": KB_ID,
                    "kb_name": KB_NAME,
                    "sources": {
                        "pdfs": [p.name for p in pdfs],
                        "images": [p.name for p in images],
                    },
                    "files": len(file_rows),
                    "chunks": len(all_chunk_rows),
                    "chunks_detail": corpus,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        print(
            f"\n[完成] KB={KB_ID} files={len(file_rows)} chunks={len(all_chunk_rows)} "
            f"chroma={vector_store.get_count(KB_ID)} bm25_docs={session.get(IndexStats, KB_ID).total_docs}"
        )
        print(f"[corpus] {CORPUS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
