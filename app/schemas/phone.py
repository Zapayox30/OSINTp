"""Schemas for the phone intelligence module."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import ResultEnvelope


class PhoneQuery(BaseModel):
    phone: str = Field(..., min_length=4, max_length=32, examples=["+12025550143"])
    region: str | None = Field(
        default=None,
        description="ISO region hint (e.g. 'US') for numbers given without a country code.",
    )


class PhoneResult(ResultEnvelope):
    """Result envelope for a phone investigation."""
