"""Aggregated investigation orchestrator.

Auto-detects the target type and dispatches to the relevant module(s),
returning every collected envelope under a single response.
"""

from __future__ import annotations

import ipaddress
import re

from fastapi import APIRouter, HTTPException, status

from app.api.deps import (
    DomainServiceDep,
    EmailServiceDep,
    IPServiceDep,
    UsernameServiceDep,
)
from app.schemas.domain import DomainQuery
from app.schemas.email import EmailQuery
from app.schemas.investigation import InvestigationQuery, InvestigationResult, TargetType
from app.schemas.ip import IPQuery
from app.schemas.username import UsernameQuery

router = APIRouter(prefix="/investigate", tags=["investigation"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def detect_type(target: str) -> TargetType:
    candidate = target.strip()
    try:
        ipaddress.ip_address(candidate)
        return "ip"
    except ValueError:
        pass
    if _EMAIL_RE.match(candidate):
        return "email"
    if "." in candidate and " " not in candidate:
        return "domain"
    return "username"


@router.post("", response_model=InvestigationResult, summary="Auto-detect and investigate a target")
async def investigate(
    query: InvestigationQuery,
    username_service: UsernameServiceDep,
    email_service: EmailServiceDep,
    domain_service: DomainServiceDep,
    ip_service: IPServiceDep,
) -> InvestigationResult:
    target = query.target.strip()
    detected: TargetType = query.type or detect_type(target)
    result = InvestigationResult(target=target, detected_type=detected)

    try:
        if detected == "ip":
            result.modules["ip"] = await ip_service.investigate(IPQuery(ip=target))
        elif detected == "email":
            email_env = await email_service.investigate(EmailQuery(email=target))
            result.modules["email"] = email_env
            if query.cross_reference:
                local_part = target.split("@", 1)[0]
                result.modules["username"] = await username_service.investigate(
                    UsernameQuery(username=local_part)
                )
        elif detected == "domain":
            result.modules["domain"] = await domain_service.investigate(
                DomainQuery(domain=target)
            )
        else:
            result.modules["username"] = await username_service.investigate(
                UsernameQuery(username=target)
            )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    return result
