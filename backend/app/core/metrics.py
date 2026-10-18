"""Prometheus 指标与请求日志用的路径归一化。"""

from __future__ import annotations

import re
from typing import Optional

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

http_requests_total = Counter(
    "rag_http_requests_total",
    "HTTP requests",
    ["method", "path", "status"],
)
http_request_duration = Histogram(
    "rag_http_request_duration_seconds",
    "HTTP request duration",
    ["method", "path"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60),
)
retrieval_duration = Histogram(
    "rag_retrieval_duration_seconds",
    "Retrieval stage duration",
    ["stage"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
)
llm_ttft = Histogram(
    "rag_llm_ttft_seconds",
    "LLM time to first token",
    ["model"],
    buckets=(0.1, 0.25, 0.5, 1, 1.5, 2, 3, 5, 8, 15, 30),
)
cache_hits_total = Counter("rag_retrieval_cache_hits_total", "Retrieval cache hits")
agent_retry_total = Counter("rag_agent_retries_total", "Agent grading retries")

_UUID = re.compile(r"/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_NUM = re.compile(r"/\d+")


def normalize_path(path: str) -> str:
    path = _UUID.sub("/{id}", path or "/")
    path = _NUM.sub("/{n}", path)
    return path[:200]


def observe_http(method: str, path: str, status: int, duration_s: float) -> None:
    p = normalize_path(path)
    http_requests_total.labels(method=method, path=p, status=str(status)).inc()
    http_request_duration.labels(method=method, path=p).observe(duration_s)


def observe_retrieval(stage: str, duration_s: float) -> None:
    retrieval_duration.labels(stage=stage).observe(max(0.0, duration_s))


def observe_llm_ttft(model: str, duration_s: float) -> None:
    llm_ttft.labels(model=(model or "unknown")[:64]).observe(max(0.0, duration_s))


def metrics_payload() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
