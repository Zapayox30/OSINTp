"""Schemas for background jobs."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class JobInfo(BaseModel):
    id: str
    kind: str
    status: str  # queued | running | done | error
    created_at: datetime
    finished_at: datetime | None = None
    error: str | None = None
    result: dict[str, Any] | None = None
