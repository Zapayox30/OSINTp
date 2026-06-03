"""Schemas for the domain intelligence module."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import ResultEnvelope


class DomainQuery(BaseModel):
    domain: str = Field(..., min_length=3, max_length=253, examples=["example.com"])
    include_subdomains: bool = Field(
        default=True,
        description="Enumerate subdomains via certificate transparency logs (crt.sh).",
    )


class DomainResult(ResultEnvelope):
    """Result envelope for a domain investigation."""
