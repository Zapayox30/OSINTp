"""FastAPI dependencies wiring services to the shared HTTP client."""

from __future__ import annotations

from typing import Annotated

import httpx
from fastapi import Depends

from app.core.http_client import get_client
from app.services.correlation import CorrelationEngine
from app.services.domain_service import DomainService
from app.services.email_service import EmailService
from app.services.ip_service import IPService
from app.services.username_service import UsernameService

ClientDep = Annotated[httpx.AsyncClient, Depends(get_client)]


def get_username_service(client: ClientDep) -> UsernameService:
    return UsernameService(client)


def get_email_service(client: ClientDep) -> EmailService:
    return EmailService(client)


def get_domain_service(client: ClientDep) -> DomainService:
    return DomainService(client)


def get_ip_service(client: ClientDep) -> IPService:
    return IPService(client)


def get_correlation_engine(client: ClientDep) -> CorrelationEngine:
    return CorrelationEngine(client)


UsernameServiceDep = Annotated[UsernameService, Depends(get_username_service)]
EmailServiceDep = Annotated[EmailService, Depends(get_email_service)]
DomainServiceDep = Annotated[DomainService, Depends(get_domain_service)]
IPServiceDep = Annotated[IPService, Depends(get_ip_service)]
CorrelationEngineDep = Annotated[CorrelationEngine, Depends(get_correlation_engine)]
