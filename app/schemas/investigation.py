"""Schemas for the aggregated investigation orchestrator."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import ResultEnvelope

TargetType = Literal["username", "email", "domain", "ip", "phone"]


class InvestigationQuery(BaseModel):
    target: str = Field(..., min_length=1, max_length=253, examples=["torvalds"])
    type: TargetType | None = Field(
        default=None,
        description="Force a target type. Auto-detected from the target when omitted.",
    )
    cross_reference: bool = Field(
        default=False,
        description="For emails, also run a username search on the local part.",
    )


class InvestigationResult(BaseModel):
    target: str
    detected_type: TargetType
    modules: dict[str, ResultEnvelope] = Field(default_factory=dict)
