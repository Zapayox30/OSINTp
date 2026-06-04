"""Tests for production hardening: auth, rate limiting, cache, jobs."""

from __future__ import annotations

import time

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import Response

from app.core import cache, security
from app.core.config import get_settings
from app.core.ratelimit import RateLimitMiddleware


def _request(headers: dict | None = None, query: bytes = b"") -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request(
        {"type": "http", "method": "GET", "path": "/", "headers": raw, "query_string": query}
    )


async def test_auth_disabled_by_default():
    assert get_settings().api_key is None
    await security.require_api_key(_request())  # must not raise


async def test_auth_enforced_when_configured(monkeypatch):
    monkeypatch.setattr(get_settings(), "api_key", "s3cret")
    with pytest.raises(HTTPException):
        await security.require_api_key(_request())
    # header or query param both accepted
    await security.require_api_key(_request({"x-api-key": "s3cret"}))
    await security.require_api_key(_request(query=b"api_key=s3cret"))


async def test_rate_limit_blocks_after_threshold(monkeypatch):
    monkeypatch.setattr(get_settings(), "rate_limit_per_minute", 2)
    mw = RateLimitMiddleware(app=None)

    async def call_next(_req):
        return Response("ok")

    assert (await mw.dispatch(_request(), call_next)).status_code == 200
    assert (await mw.dispatch(_request(), call_next)).status_code == 200
    assert (await mw.dispatch(_request(), call_next)).status_code == 429


async def test_ttl_cache_memoises(monkeypatch):
    monkeypatch.setattr(get_settings(), "cache_ttl_seconds", 60)
    cache._CACHE.clear()
    calls = {"n": 0}

    class Dummy:
        @cache.ttl_cached()
        async def fetch(self, x):
            calls["n"] += 1
            return x * 2

    d = Dummy()
    assert await d.fetch(3) == 6
    assert await d.fetch(3) == 6
    assert calls["n"] == 1  # second call served from cache
    assert await d.fetch(4) == 8
    assert calls["n"] == 2


def test_jobs_submit_and_complete(client):
    resp = client.post("/api/v1/jobs", json={"target": "10.0.0.3", "max_depth": 1})
    assert resp.status_code == 202
    job_id = resp.json()["id"]

    info = {}
    for _ in range(100):
        info = client.get(f"/api/v1/jobs/{job_id}").json()
        if info["status"] in ("done", "error"):
            break
        time.sleep(0.05)
    assert info["status"] == "done", info
    assert info["result"]["seed_type"] == "ip"


def test_jobs_404(client):
    assert client.get("/api/v1/jobs/nope").status_code == 404
