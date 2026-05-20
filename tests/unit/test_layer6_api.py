from __future__ import annotations

from fastapi.testclient import TestClient

from jarvis.app.main import app


def test_layer6_openapi_contains_core_routes() -> None:
    schema = app.openapi()

    assert schema["info"]["title"] == "Newscope API"
    assert "/api/v1/news/feed" in schema["paths"]
    assert "/api/v1/search" in schema["paths"]
    assert "/api/v1/chat" in schema["paths"]
    assert "/api/v1/admin/overview" in schema["paths"]


def test_layer6_health_endpoint() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
