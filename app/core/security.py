"""Optional API-key authentication.

Disabled by default: when ``API_KEY`` is unset the API is open. When set, every
request under ``/api/v1`` must present the key via the ``X-API-Key`` header or
an ``api_key`` query parameter (the latter so SSE/``EventSource`` clients, which
cannot set headers, still work).
"""

from __future__ import annotations

from fastapi import HTTPException, Request, status

from app.core.config import get_settings


async def require_api_key(request: Request) -> None:
    settings = get_settings()
    if not settings.api_key:
        return  # auth disabled
    provided = request.headers.get("x-api-key") or request.query_params.get("api_key")
    if provided != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key.",
            headers={"WWW-Authenticate": "API-Key"},
        )
