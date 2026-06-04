"""Tiny in-memory TTL cache for outbound lookups.

Bounded by time only (single-process). Disabled when ``CACHE_TTL_SECONDS`` is 0.
Use the :func:`ttl_cached` decorator on async methods whose result depends only
on their arguments (e.g. a DNS record type for a domain, or an IP geolocation).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from functools import wraps

from app.core.config import get_settings


class TTLCache:
    def __init__(self) -> None:
        self._store: dict[tuple, tuple[float, object]] = {}

    def get(self, key: tuple, ttl: float):
        item = self._store.get(key)
        if item is None:
            return None
        ts, value = item
        if time.monotonic() - ts > ttl:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: tuple, value: object) -> None:
        self._store[key] = (time.monotonic(), value)

    def clear(self) -> None:
        self._store.clear()


_CACHE = TTLCache()


def stable_source(result) -> bool:
    """Cache only deterministic source outcomes (found / not_found)."""
    from app.schemas.common import SourceStatus

    return getattr(result, "status", None) in (SourceStatus.found, SourceStatus.not_found)


def ttl_cached(predicate: Callable[[object], bool] | None = None):
    """Memoise an async method for ``CACHE_TTL_SECONDS`` (keyed on its args)."""

    def decorator(fn):
        @wraps(fn)
        async def wrapper(self, *args, **kwargs):
            ttl = get_settings().cache_ttl_seconds
            if ttl <= 0:
                return await fn(self, *args, **kwargs)
            key = (fn.__qualname__, args, tuple(sorted(kwargs.items())))
            cached = _CACHE.get(key, ttl)
            if cached is not None:
                return cached
            value = await fn(self, *args, **kwargs)
            if predicate is None or predicate(value):
                _CACHE.set(key, value)
            return value

        return wrapper

    return decorator
