"""Entity-correlation graph endpoints.

* ``GET  /api/v1/graph`` — Server-Sent Events; streams nodes/edges as the
  recursive auto-pivot discovers them (drives the live graph view).
* ``POST /api/v1/graph`` — builds and returns the whole graph in one response.

SSE event contract: ``start`` → ``meta`` → (``node`` | ``edge`` | ``progress``)*
→ ``summary`` → ``done`` (``error`` may appear before ``done``).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from app.api.deps import CorrelationEngineDep
from app.schemas.graph import GraphQuery, GraphResult

router = APIRouter(tags=["graph"])


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n"


@router.get("/graph", summary="Live SSE stream of the correlation graph")
async def graph_stream(
    engine: CorrelationEngineDep,
    target: str = Query(..., min_length=1, max_length=253, examples=["example.com"]),
    target_type: str | None = Query(default=None, alias="type"),
    max_depth: int = Query(default=2, ge=1, le=3),
    max_nodes: int = Query(default=60, ge=5, le=150),
) -> StreamingResponse:
    query = GraphQuery(
        target=target, type=target_type, max_depth=max_depth, max_nodes=max_nodes
    )

    async def event_source() -> AsyncIterator[str]:
        yield _sse("start", {"target": target.strip()})
        try:
            async for event, payload in engine.stream(query):
                yield _sse(event, payload)
        except ValueError as exc:
            yield _sse("error", {"message": str(exc)})
        except Exception as exc:  # noqa: BLE001 — surface, don't 500 mid-stream
            yield _sse("error", {"message": f"{type(exc).__name__}: {exc}"})
        yield _sse("done", {})

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/graph", response_model=GraphResult, summary="Build the correlation graph")
async def graph_build(engine: CorrelationEngineDep, query: GraphQuery) -> GraphResult:
    try:
        return await engine.build(query)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
