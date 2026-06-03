"""Schemas for the username enumeration module."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import ResultEnvelope


class UsernameQuery(BaseModel):
    username: str = Field(..., min_length=1, max_length=64, examples=["torvalds"])
    categories: list[str] | None = Field(
        default=None,
        description="Restrict the search to these site categories (e.g. ['dev', 'social']).",
    )
    include_not_found: bool = Field(
        default=False,
        description="Include sites where the username was not found in the response.",
    )


class UsernameResult(ResultEnvelope):
    """Result envelope for a username investigation."""
