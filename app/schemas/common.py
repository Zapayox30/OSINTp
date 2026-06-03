"""Shared schema primitives used across all OSINT modules."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SourceStatus(str, Enum):
    """Outcome of probing a single external source."""

    found = "found"
    not_found = "not_found"
    error = "error"
    rate_limited = "rate_limited"
    skipped = "skipped"


class SourceResult(BaseModel):
    """Normalised result returned by an individual OSINT source/probe."""

    source: str = Field(..., description="Human-readable source name, e.g. 'GitHub'.")
    category: str = Field(default="other", description="Grouping such as 'social' or 'dev'.")
    status: SourceStatus
    url: str | None = Field(default=None, description="Public URL associated with the hit.")
    data: dict[str, Any] = Field(default_factory=dict, description="Extra structured data.")
    error: str | None = Field(default=None, description="Error detail when status is 'error'.")
    elapsed_ms: float | None = Field(default=None, description="Probe latency in milliseconds.")


class ResultEnvelope(BaseModel):
    """Standard envelope wrapping every module response."""

    target: str = Field(..., description="The investigated identifier.")
    module: str = Field(..., description="Module that produced the result.")
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    summary: dict[str, Any] = Field(default_factory=dict)
    results: list[SourceResult] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str = "ok"
    app: str
    version: str
    environment: str
