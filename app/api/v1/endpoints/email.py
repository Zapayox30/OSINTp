"""Email intelligence endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import EmailServiceDep
from app.schemas.email import EmailQuery, EmailResult

router = APIRouter(prefix="/email", tags=["email"])


@router.get("", response_model=EmailResult, summary="Investigate an email (quick GET)")
async def investigate_email_get(
    service: EmailServiceDep,
    email: str = Query(..., examples=["torvalds@linux-foundation.org"]),
) -> EmailResult:
    return await service.investigate(EmailQuery(email=email))


@router.post("", response_model=EmailResult, summary="Investigate an email")
async def investigate_email(service: EmailServiceDep, query: EmailQuery) -> EmailResult:
    return await service.investigate(query)
