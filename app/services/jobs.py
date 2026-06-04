"""In-process background job manager.

A dependency-free task queue for long-running work (e.g. deep graph builds):
jobs run as :mod:`asyncio` tasks on the app's event loop, with status and
results held in memory. Suitable for a single process; swap for Celery/ARQ +
Redis if you need durability or multiple workers.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from functools import lru_cache

from app.core.logging import get_logger
from app.schemas.jobs import JobInfo

logger = get_logger(__name__)


class Job:
    def __init__(self, kind: str) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.status = "queued"
        self.created_at = datetime.now(timezone.utc)
        self.finished_at: datetime | None = None
        self.result: dict | None = None
        self.error: str | None = None

    def info(self) -> JobInfo:
        return JobInfo(
            id=self.id,
            kind=self.kind,
            status=self.status,
            created_at=self.created_at,
            finished_at=self.finished_at,
            error=self.error,
            result=self.result,
        )


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    def submit(self, kind: str, factory: Callable[[], Awaitable[dict]]) -> Job:
        job = Job(kind)
        self._jobs[job.id] = job
        asyncio.create_task(self._run(job, factory))
        return job

    async def _run(self, job: Job, factory: Callable[[], Awaitable[dict]]) -> None:
        job.status = "running"
        try:
            job.result = await factory()
            job.status = "done"
        except Exception as exc:  # noqa: BLE001 — record any failure on the job
            job.error = f"{type(exc).__name__}: {exc}"
            job.status = "error"
            logger.warning("job %s failed: %s", job.id, job.error)
        finally:
            job.finished_at = datetime.now(timezone.utc)

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)


@lru_cache
def get_job_manager() -> JobManager:
    return JobManager()
