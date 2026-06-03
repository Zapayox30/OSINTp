"""Schemas for the email intelligence module."""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import ResultEnvelope


class EmailQuery(BaseModel):
    email: EmailStr = Field(..., examples=["torvalds@linux-foundation.org"])


class EmailResult(ResultEnvelope):
    """Result envelope for an email investigation."""
