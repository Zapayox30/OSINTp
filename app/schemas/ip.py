"""Schemas for the IP intelligence module."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import ResultEnvelope


class IPQuery(BaseModel):
    ip: str = Field(..., examples=["8.8.8.8"])


class IPResult(ResultEnvelope):
    """Result envelope for an IP investigation."""
