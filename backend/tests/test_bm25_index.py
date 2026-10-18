import pytest
from sqlmodel import Session
from app.core.database import engine
from app.services.bm25 import tokenize, BM25Index, get_bm25_index


def test_tokenize_mixed_chinese_english():
    """测试中英文混合切词与停用词过滤"""
    text = "Kubernetes 中的 Pod 发生 OOMKilled (Exit Code 137) 该如何排查？"
    tokens = tokenize(text)
    assert isinstance(tokens, list)
    assert len(tokens) > 0
    assert any("kubernetes" in t.lower() or "pod" in t.lower() for t in tokens)
    assert any("oomkilled" in t.lower() or "137" in t for t in tokens)
    assert "的" not in tokens
    assert "中" not in tokens


def test_bm25_search_real_sop(enterprise_kb_id):
    """测试基于真实 SRE 知识库的 BM25 稀疏倒排索引检索"""
    bm25 = get_bm25_index()
    with Session(engine) as session:
        # 查询 K8s Exit Code 137
        results = bm25.search(
            session=session,
            query="Exit Code 137 OOMKilled",
            kb_id=enterprise_kb_id,
            top_k=3,
        )
        assert len(results) > 0
        assert results[0]["bm25_score"] > 0
        assert isinstance(results[0]["chunk_id"], str)

        # 查询 PostgreSQL 死锁 pg_terminate_backend
        pg_results = bm25.search(
            session=session,
            query="PostgreSQL 慢查询 pg_terminate_backend 死锁",
            kb_id=enterprise_kb_id,
            top_k=3,
        )
        assert len(pg_results) > 0
        assert pg_results[0]["bm25_score"] > 0
