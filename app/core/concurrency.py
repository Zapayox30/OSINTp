"""Concurrency helpers for fanning out OSINT probes."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Sequence
from typing import TypeVar

from app.core.config import get_settings

T = TypeVar("T")


async def gather_bounded(
    tasks: Iterable[Callable[[], Awaitable[T]]],
    limit: int | None = None,
) -> Sequence[T]:
    """Run *tasks* concurrently with a bounded number of workers.

    Each item must be a zero-argument coroutine factory so coroutines are only
    created once a worker slot is free. Exceptions raised by an individual task
    are returned in place of its result (``return_exceptions`` semantics).
    """
    if limit is None:
        limit = get_settings().max_concurrency
    semaphore = asyncio.Semaphore(max(1, limit))

    async def _run(factory: Callable[[], Awaitable[T]]) -> T:
        async with semaphore:
            return await factory()

    return await asyncio.gather(
        *(_run(factory) for factory in tasks),
        return_exceptions=True,
    )


async def stream_bounded(
    factories: Iterable[Callable[[], Awaitable[T]]],
    limit: int | None = None,
) -> AsyncIterator[T]:
    """Yield results from *factories* as each one completes.

    Unlike :func:`gather_bounded`, results stream back in completion order — which
    is what a live console wants. Still bounded by *limit* concurrent workers.
    Any tasks left pending are cancelled if the consumer stops early (e.g. the
    client disconnects mid-stream).
    """
    if limit is None:
        limit = get_settings().max_concurrency
    semaphore = asyncio.Semaphore(max(1, limit))

    async def _run(factory: Callable[[], Awaitable[T]]) -> T:
        async with semaphore:
            return await factory()

    tasks = [asyncio.create_task(_run(factory)) for factory in factories]
    try:
        for completed in asyncio.as_completed(tasks):
            yield await completed
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
