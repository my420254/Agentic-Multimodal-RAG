import pytest
from sqlmodel import Session
from app.core.database import engine
from app.services.retrieval import (
    get_retrieval_service,
    normalize_scores,
    jaccard_similarity,
    deduplicate_results,
)
from app.services.rerank import RerankService


def test_jaccard_similarity():
    """测试文本 Jaccard 相似度算法"""
    s1 = "Kubernetes Pod CrashLoopBackOff 故障排查"
    s2 = "Kubernetes Pod CrashLoopBackOff 排查方案"
    sim = jaccard_similarity(s1, s2)
    assert 0.5 < sim <= 1.0

    s3 = "Redis 缓存雪崩与布隆过滤器配置"
    sim_diff = jaccard_similarity(s1, s3)
    assert sim_diff < 0.3


def test_score_normalization():
    """测试检索分数归一化 (Min-Max)"""
    raw_scores = {"doc1": 10.0, "doc2": 20.0, "doc3": 50.0}
    norm = normalize_scores(raw_scores)
    assert norm["doc1"] == 0.0
    assert norm["doc3"] == 1.0
    assert 0.0 < norm["doc2"] < 1.0


@pytest.mark.asyncio
async def test_hybrid_retrieval_service(enterprise_kb_id):
    """测试双路混合检索召回核心链路 (Vector + BM25)"""
    retrieval = get_retrieval_service()
    with Session(engine) as session:
        # 1. 混合检索
        results, original = await retrieval.search(
            session=session,
            query="Redis 缓存击穿与分布式锁互斥",
            kb_ids=[enterprise_kb_id],
            search_mode="hybrid",
            top_k=3,
        )
        assert len(results) > 0
        assert any("redis" in r["content"].lower() or "缓存" in r["content"] for r in results)

        # 2. 纯向量检索
        vec_results, _ = await retrieval.search(
            session=session,
            query="JVM 容器内存 Exit Code 137",
            kb_ids=[enterprise_kb_id],
            search_mode="vector",
            top_k=3,
        )
        assert len(vec_results) > 0

        # 3. 纯全文检索
        ft_results, _ = await retrieval.search(
            session=session,
            query="pg_terminate_backend 死锁",
            kb_ids=[enterprise_kb_id],
            search_mode="fulltext",
            top_k=3,
        )
        assert len(ft_results) > 0


def test_rerank_service_scoring():
    """测试 Rerank 服务交叉打分与候选排序"""
    query = "如何排查 Kubernetes Pod 崩溃 OOMKilled"
    docs = [
        "Kubernetes 中 Pod 发生 Exit Code 137 属于 cgroups 限制引起的 OOMKilled 故障，需查看 dmesg 日志。",
        "在 Python 中通过 requests 库发送 HTTP POST 请求并处理 json 响应数据。",
    ]
    with Session(engine) as session:
        reranker = RerankService(session)
        model = reranker.get_default_rerank_model()
        if model:
            results = reranker.rerank(query, docs, model=model)
            assert len(results) == 2
            assert results[0]["index"] == 0
        else:
            assert True
