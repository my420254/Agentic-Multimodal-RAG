#!/usr/bin/env python3
"""
简历切块策略消融（300 / 500 / 800 字）。

只对 PDF/DOCX 两封重复简历做临时 collection，不动主知识库。
指标：R01-R08 八条简历事实题的 evidence_all@3 / evidence_any@3 / MRR。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

import chromadb
from chromadb.config import Settings as ChromaSettings

BACKEND_DIR = Path(__file__).resolve().parent.parent
ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import get_settings  # noqa: E402
from app.services.embedding import EmbeddingService  # noqa: E402
from app.services.parser import FileParser  # noqa: E402

settings = get_settings()

UPLOAD_KB_DIR = BACKEND_DIR / "storage/uploads/6d3e18a1-f70a-4acc-80a6-65eaea9a7a69"


def _resume_path(ext: str) -> Path | None:
    """优先用 CHUNKING_PDF_PATH / CHUNKING_DOCX_PATH，否则从上传目录取第一份。"""
    env_path = os.getenv(f"CHUNKING_{ext.upper()}_PATH")
    if env_path:
        return Path(env_path)
    matches = sorted(UPLOAD_KB_DIR.glob(f"*.{ext}"))
    return matches[0] if matches else None


FILES = {
    "pdf": _resume_path("pdf"),
    "docx": _resume_path("docx"),
}
SIZES = [300, 500, 800]
GOLDEN = json.loads((BACKEND_DIR / "benchmark" / "personal_kb_golden.json").read_text(encoding="utf-8"))
RESUME_CASES = [c for c in GOLDEN["cases"] if c["id"].startswith("R")]
OUT = BACKEND_DIR / "benchmark" / "chunking_eval.json"


def _hits(text: str, evidence: List[str]) -> int:
    return sum(1 for e in evidence if e in text)


async def main() -> int:
    if not FILES["pdf"] or not FILES["docx"]:
        print(
            "缺少 PDF/DOCX：请设置 CHUNKING_PDF_PATH / CHUNKING_DOCX_PATH，"
            "或把简历放到 backend/storage/uploads/<kb_id>/ 下。",
            file=sys.stderr,
        )
        return 2

    embedder = EmbeddingService()
    client = chromadb.PersistentClient(
        path=settings.CHROMA_DB_DIR,
        settings=ChromaSettings(anonymized_telemetry=False, allow_reset=True),
    )

    # 查询向量只算一次，三档切块共用
    queries = [c["query"] for c in RESUME_CASES]
    query_vectors = await embedder.embed_documents(queries)

    results: Dict[str, Any] = {}
    for size in SIZES:
        collection_name = f"eval_resume_chunk_{size}"
        try:
            client.delete_collection(collection_name)
        except Exception:
            pass
        collection = client.create_collection(
            name=collection_name,
            metadata={"kind": "chunking_eval", "size": size},
        )

        docs: List[str] = []
        ids: List[str] = []
        metas: List[Dict[str, Any]] = []
        stats: Dict[str, Any] = {}
        for key, path in FILES.items():
            parser = FileParser(kb_id="eval_chunking")
            chunks = parser.parse(
                str(path),
                chunk_mode="custom",
                chunk_size=size,
                chunk_overlap=max(30, size // 10),
            )
            lengths = [len(c.content) for c in chunks]
            stats[key] = {
                "chunks": len(chunks),
                "avg_chars": round(sum(lengths) / len(lengths), 1) if lengths else 0,
                "max_chars": max(lengths) if lengths else 0,
            }
            for idx, chunk in enumerate(chunks):
                docs.append(chunk.content)
                ids.append(f"{key}_{idx}")
                metas.append({"file": key, "idx": idx})

        vectors: List[List[float]] = []
        for start in range(0, len(docs), 32):
            vectors.extend(await embedder.embed_documents(docs[start:start + 32]))
        collection.add(ids=ids, documents=docs, embeddings=vectors, metadatas=metas)
        print(f"[size={size}] indexed {len(docs)} chunks {stats}", flush=True)

        rows = []
        for case, qvec in zip(RESUME_CASES, query_vectors):
            res = collection.query(query_embeddings=[qvec], n_results=3, include=["documents", "metadatas"])
            top_docs = res["documents"][0] if res["documents"] else []
            top_files = [m["file"] for m in (res["metadatas"][0] if res["metadatas"] else [])]
            joined = "\n".join(top_docs)
            hit_count = _hits(joined, case["gold_evidence"])
            evidence_all = bool(case["gold_evidence"]) and hit_count == len(case["gold_evidence"])
            evidence_any = hit_count > 0
            file_hit = any(f in {"pdf", "docx"} for f in top_files)
            rr = 0.0
            for rank, text in enumerate(top_docs, start=1):
                if any(e in text for e in case["gold_evidence"]):
                    rr = 1.0 / rank
                    break
            rows.append(
                {
                    "id": case["id"],
                    "evidence_hits": hit_count,
                    "evidence_count": len(case["gold_evidence"]),
                    "evidence_all": evidence_all,
                    "evidence_any": evidence_any,
                    "resume_file_hit": file_hit,
                    "rr": rr,
                }
            )
            print(
                f"  [{case['id']}] all={evidence_all} any={evidence_any} hits={hit_count}/{len(case['gold_evidence'])} files={top_files}",
                flush=True,
            )

        n = len(rows)
        results[str(size)] = {
            "chunk_stats": stats,
            "cases": rows,
            "evidence_all@3": round(sum(r["evidence_all"] for r in rows) / n, 4),
            "evidence_any@3": round(sum(r["evidence_any"] for r in rows) / n, 4),
            "resume_file_hit@3": round(sum(r["resume_file_hit"] for r in rows) / n, 4),
            "mrr": round(sum(r["rr"] for r in rows) / n, 4),
        }
        client.delete_collection(collection_name)

    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n=== CHUNKING SUMMARY ===")
    for size, row in results.items():
        print(
            f"size={size}: all@3={row['evidence_all@3']:.2%} any@3={row['evidence_any@3']:.2%} "
            f"resume_file@3={row['resume_file_hit@3']:.2%} mrr={row['mrr']:.4f} "
            f"stats={row['chunk_stats']}"
        )
    print(f"JSON: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
