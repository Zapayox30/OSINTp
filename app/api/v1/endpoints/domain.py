"""Domain intelligence endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import DomainServiceDep
from app.schemas.domain import DomainQuery, DomainResult

router = APIRouter(prefix="/domain", tags=["domain"])


@router.get("", response_model=DomainResult, summary="Investigate a domain (quick GET)")
async def investigate_domain_get(
    service: DomainServiceDep,
    domain: str = Query(..., examples=["example.com"]),
    include_subdomains: bool = Query(default=True),
) -> DomainResult:
    query = DomainQuery(domain=domain, include_subdomains=include_subdomains)
    return await _run(service, query)


@router.post("", response_model=DomainResult, summary="Investigate a domain")
async def investigate_domain(service: DomainServiceDep, query: DomainQuery) -> DomainResult:
    return await _run(service, query)


async def _run(service: DomainServiceDep, query: DomainQuery) -> DomainResult:
    try:
        return await service.investigate(query)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
