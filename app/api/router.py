"""Top-level API router aggregating all versioned endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints import domain, email, investigation, ip, stream, username

api_router = APIRouter()

v1 = APIRouter(prefix="/v1")
v1.include_router(username.router)
v1.include_router(email.router)
v1.include_router(domain.router)
v1.include_router(ip.router)
v1.include_router(investigation.router)
v1.include_router(stream.router)

api_router.include_router(v1)
