from app.services.retrieval import RetrievalCache


def test_cache_key_includes_weights_and_threshold():
    cache = RetrievalCache(ttl_seconds=60, enabled=True)
    kb_ids = ["kb_demo"]
    results = [{"id": "chunk_1", "content": "x", "score": 1.0}]
    params = {"score_threshold": 0.0, "vector_weight": 0.7, "bm25_weight": 0.3}
    cache.set("query", kb_ids, "hybrid", 5, results, params)

    assert cache.get("query", kb_ids, "hybrid", 5, params) == results

    changed_weight = {"score_threshold": 0.0, "vector_weight": 0.8, "bm25_weight": 0.2}
    assert cache.get("query", kb_ids, "hybrid", 5, changed_weight) is None

    changed_threshold = {"score_threshold": 0.5, "vector_weight": 0.7, "bm25_weight": 0.3}
    assert cache.get("query", kb_ids, "hybrid", 5, changed_threshold) is None
