"""Phone intelligence endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import PhoneServiceDep
from app.schemas.phone import PhoneQuery, PhoneResult

router = APIRouter(prefix="/phone", tags=["phone"])


@router.get("", response_model=PhoneResult, summary="Investigate a phone number (quick GET)")
async def investigate_phone_get(
    service: PhoneServiceDep,
    phone: str = Query(..., examples=["+12025550143"]),
    region: str | None = Query(default=None, examples=["US"]),
) -> PhoneResult:
    return await service.investigate(PhoneQuery(phone=phone, region=region))


@router.post("", response_model=PhoneResult, summary="Investigate a phone number")
async def investigate_phone(service: PhoneServiceDep, query: PhoneQuery) -> PhoneResult:
    return await service.investigate(query)
