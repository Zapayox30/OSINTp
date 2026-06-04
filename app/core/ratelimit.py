"""Simple in-memory, per-IP fixed-window rate limiting.

Single-process only (no Redis). Disabled when ``RATE_LIMIT_PER_MINUTE`` is 0.
"""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import get_settings


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app) -> None:
        super().__init__(app)
        self._hits: dict[str, tuple[int, int]] = {}

    async def dispatch(self, request: Request, call_next):
        limit = get_settings().rate_limit_per_minute
        if limit <= 0:
            return await call_next(request)

        ip = request.client.host if request.client else "unknown"
        window = int(time.time() // 60)
        start, count = self._hits.get(ip, (window, 0))
        if start != window:
            start, count = window, 0
        count += 1
        self._hits[ip] = (start, count)

        if count > limit:
            return JSONResponse(
                {"detail": "Rate limit exceeded. Try again shortly."},
                status_code=429,
                headers={"Retry-After": "60"},
            )
        return await call_next(request)
