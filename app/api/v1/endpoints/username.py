"""Username enumeration endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import UsernameServiceDep
from app.schemas.username import UsernameQuery, UsernameResult

router = APIRouter(prefix="/username", tags=["username"])


@router.get("/categories", summary="List available site categories")
async def list_categories(service: UsernameServiceDep) -> dict[str, list[str]]:
    return {"categories": service.categories()}


@router.get("", response_model=UsernameResult, summary="Search a username (quick GET)")
async def search_username_get(
    service: UsernameServiceDep,
    username: str = Query(..., min_length=1, max_length=64, examples=["torvalds"]),
    categories: list[str] | None = Query(default=None),
    include_not_found: bool = Query(default=False),
) -> UsernameResult:
    query = UsernameQuery(
        username=username,
        categories=categories,
        include_not_found=include_not_found,
    )
    return await _run(service, query)


@router.post("", response_model=UsernameResult, summary="Search a username")
async def search_username(service: UsernameServiceDep, query: UsernameQuery) -> UsernameResult:
    return await _run(service, query)


async def _run(service: UsernameServiceDep, query: UsernameQuery) -> UsernameResult:
    try:
        return await service.investigate(query)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
