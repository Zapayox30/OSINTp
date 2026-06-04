"""Top-level API router aggregating all versioned endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.v1.endpoints import (
    cases,
    domain,
    email,
    graph,
    investigation,
    ip,
    jobs,
    phone,
    stream,
    username,
)
from app.core.security import require_api_key

api_router = APIRouter()

v1 = APIRouter(prefix="/v1", dependencies=[Depends(require_api_key)])
v1.include_router(username.router)
v1.include_router(email.router)
v1.include_router(domain.router)
v1.include_router(ip.router)
v1.include_router(phone.router)
v1.include_router(investigation.router)
v1.include_router(stream.router)
v1.include_router(graph.router)
v1.include_router(cases.router)
v1.include_router(jobs.router)

api_router.include_router(v1)
