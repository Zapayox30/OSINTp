"""Shared async HTTP client managed by the application lifespan.

A single :class:`httpx.AsyncClient` with connection pooling is reused across
all requests. Services obtain it through :func:`get_client`.
"""

from __future__ import annotations

import httpx

from app.core.config import get_settings


class HTTPClientManager:
    """Owns the lifecycle of the shared :class:`httpx.AsyncClient`."""

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        if self._client is not None:
            return
        settings = get_settings()
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.http_timeout),
            limits=httpx.Limits(max_connections=settings.http_max_connections),
            headers={"User-Agent": settings.user_agent},
            follow_redirects=True,
        )

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError(
                "HTTP client is not initialised. Did the application lifespan start?"
            )
        return self._client


# Module-level singleton wired up in the FastAPI lifespan.
http_client = HTTPClientManager()


def get_client() -> httpx.AsyncClient:
    """FastAPI dependency / helper returning the shared async client."""
    return http_client.client
