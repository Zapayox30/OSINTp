"""Server-Sent Events (SSE) streaming endpoint.

Powers the live command-center console: results are pushed to the browser as
each source resolves, rather than waiting for the whole investigation. Auto-
detects the target type (or honours an explicit ``type``) and dispatches to the
matching service's ``stream()`` generator.

Event stream contract (``text/event-stream``):

* ``start``   — ``{target, detected_type}``
* ``meta``    — ``{module, target, total}``
* ``result``  — a serialised ``SourceResult``
* ``summary`` — module summary dict
* ``error``   — ``{message}`` (validation or unexpected failure)
* ``done``    — ``{}`` (always last; client should close the stream)
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.api.deps import (
    DomainServiceDep,
    EmailServiceDep,
    IPServiceDep,
    UsernameServiceDep,
)
from app.core.detect import detect_type
from app.schemas.domain import DomainQuery
from app.schemas.email import EmailQuery
from app.schemas.ip import IPQuery
from app.schemas.username import UsernameQuery

router = APIRouter(tags=["stream"])


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n"


@router.get("/stream", summary="Live SSE stream of an investigation")
async def stream(
    username_service: UsernameServiceDep,
    email_service: EmailServiceDep,
    domain_service: DomainServiceDep,
    ip_service: IPServiceDep,
    target: str = Query(..., min_length=1, max_length=253, examples=["torvalds"]),
    target_type: str | None = Query(
        default=None,
        alias="type",
        description="Force a type: username|email|domain|ip. Auto-detected when omitted.",
    ),
    include_not_found: bool = Query(default=False),
) -> StreamingResponse:
    target = target.strip()
    detected = target_type or detect_type(target)

    async def event_source() -> AsyncIterator[str]:
        yield _sse("start", {"target": target, "detected_type": detected})
        try:
            if detected == "ip":
                generator = ip_service.stream(IPQuery(ip=target))
            elif detected == "email":
                generator = email_service.stream(EmailQuery(email=target))
            elif detected == "domain":
                generator = domain_service.stream(DomainQuery(domain=target))
            else:
                generator = username_service.stream(
                    UsernameQuery(username=target, include_not_found=include_not_found)
                )
            async for event, payload in generator:
                yield _sse(event, payload)
        except ValueError as exc:
            yield _sse("error", {"message": str(exc)})
        except Exception as exc:  # noqa: BLE001 — surface failures to the client, don't 500
            yield _sse("error", {"message": f"{type(exc).__name__}: {exc}"})
        yield _sse("done", {})

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable proxy buffering (nginx)
        },
    )
