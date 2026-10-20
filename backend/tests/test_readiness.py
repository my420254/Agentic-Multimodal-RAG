"""健康/就绪检查与 CORS 配置测试。"""


def test_health_is_liveness_only(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_reports_components(client):
    response = client.get("/ready")
    assert response.status_code in (200, 503)
    body = response.json()
    assert set(body["checks"]) == {"postgres", "redis", "llm"}
    assert body["status"] in {"ok", "degraded", "unavailable"}


def test_cors_rejects_unknown_origin(client):
    response = client.options(
        "/health",
        headers={
            "Origin": "http://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-origin" not in response.headers


def test_cors_allows_local_frontend(client):
    response = client.options(
        "/health",
        headers={
            "Origin": "http://127.0.0.1:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.headers.get("access-control-allow-origin") == "http://127.0.0.1:3000"
