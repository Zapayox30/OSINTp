"""IP intelligence endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import IPServiceDep
from app.schemas.ip import IPQuery, IPResult

router = APIRouter(prefix="/ip", tags=["ip"])


@router.get("", response_model=IPResult, summary="Investigate an IP (quick GET)")
async def investigate_ip_get(
    service: IPServiceDep,
    ip: str = Query(..., examples=["8.8.8.8"]),
) -> IPResult:
    return await _run(service, IPQuery(ip=ip))


@router.post("", response_model=IPResult, summary="Investigate an IP")
async def investigate_ip(service: IPServiceDep, query: IPQuery) -> IPResult:
    return await _run(service, query)


async def _run(service: IPServiceDep, query: IPQuery) -> IPResult:
    try:
        return await service.investigate(query)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
