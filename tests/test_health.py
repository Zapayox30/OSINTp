"""Smoke tests for meta endpoints and the OpenAPI schema."""

from __future__ import annotations


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["app"] == "OSINTp"


def test_root_serves_console(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "OSINTp" in resp.text


def test_openapi_exposes_modules(client):
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    paths = resp.json()["paths"]
    for expected in (
        "/api/v1/username",
        "/api/v1/email",
        "/api/v1/domain",
        "/api/v1/ip",
        "/api/v1/investigate",
        "/api/v1/stream",
        "/api/v1/graph",
        "/api/v1/cases",
    ):
        assert expected in paths
