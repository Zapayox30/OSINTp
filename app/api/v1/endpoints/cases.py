"""Case / dossier endpoints: manual intel, bulk import, enrich, export.

Lets an analyst persist what they already know (entities + relationships),
upload prior research in bulk, then run the correlation engine so auto-pivot
findings *merge* into the same dossier (manual provenance is never lost).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import HTMLResponse, PlainTextResponse, StreamingResponse

from app.api.deps import CaseStoreDep, CorrelationEngineDep, IPServiceDep
from app.schemas.cases import (
    Case,
    CaseCreate,
    CaseGraph,
    DiffResult,
    GraphImport,
    ImportResult,
    ManualEdge,
    ManualEntity,
    MapResult,
    Snapshot,
)
from app.schemas.graph import Edge, Entity, EntityType, GraphQuery
from app.services.cases import entity_id
from app.services.cases.diffing import diff_graphs
from app.services.cases.store import PIVOTABLE_VALUE_TYPES
from app.services.report import build_html, build_markdown, collect_geo

router = APIRouter(prefix="/cases", tags=["cases"])

_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n"


def _to_entity_type(value: str) -> EntityType:
    try:
        return EntityType(value.strip().lower())
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown entity type: {value!r}"
        ) from exc


def _manual_entity(m: ManualEntity) -> Entity:
    etype = _to_entity_type(m.type)
    val = m.value.strip()
    return Entity(
        id=entity_id(etype.value, val),
        type=etype,
        value=val,
        label=m.label or val,
        attrs=m.attrs,
        confidence=m.confidence,
        depth=0,
        pivotable=etype.value in PIVOTABLE_VALUE_TYPES,
        discovered_by="manual",
        origin="manual",
    )


def _manual_edge(m: ManualEdge) -> tuple[Entity, Entity, Edge]:
    src = _manual_entity(ManualEntity(type=m.source_type, value=m.source_value))
    tgt = _manual_entity(ManualEntity(type=m.target_type, value=m.target_value))
    edge = Edge(
        source=src.id, target=tgt.id, relation=m.relation,
        confidence=m.confidence, origin="manual",
    )
    return src, tgt, edge


async def _require_case(store: CaseStoreDep, case_id: str) -> Case:
    case = await asyncio.to_thread(store.get_case, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Case not found: {case_id}")
    return case


# ---------------------------------------------------------------- case CRUD

@router.post("", response_model=Case, status_code=status.HTTP_201_CREATED)
async def create_case(store: CaseStoreDep, body: CaseCreate) -> Case:
    return await asyncio.to_thread(store.create_case, body.name, body.notes)


@router.get("", response_model=list[Case])
async def list_cases(store: CaseStoreDep) -> list[Case]:
    return await asyncio.to_thread(store.list_cases)


@router.get("/{case_id}", response_model=CaseGraph)
async def get_case(store: CaseStoreDep, case_id: str) -> CaseGraph:
    case = await _require_case(store, case_id)
    entities, edges = await asyncio.to_thread(store.get_graph, case_id)
    return CaseGraph(case=case, entities=entities, edges=edges)


@router.delete("/{case_id}")
async def delete_case(store: CaseStoreDep, case_id: str) -> dict[str, bool]:
    deleted = await asyncio.to_thread(store.delete_case, case_id)
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Case not found: {case_id}")
    return {"deleted": True}


@router.get("/{case_id}/export", response_model=CaseGraph)
async def export_case(store: CaseStoreDep, case_id: str) -> CaseGraph:
    return await get_case(store, case_id)


# ------------------------------------------------------------ reports & map

def _ips_in(entities: list[Entity]) -> list[str]:
    return [e.value for e in entities if e.type is EntityType.ip]


@router.get("/{case_id}/map", response_model=MapResult, summary="Geolocate the case's IPs")
async def case_map(store: CaseStoreDep, ip_service: IPServiceDep, case_id: str) -> MapResult:
    await _require_case(store, case_id)
    entities, _ = await asyncio.to_thread(store.get_graph, case_id)
    points = await collect_geo(ip_service, _ips_in(entities))
    located = sum(1 for p in points if p.lat is not None)
    return MapResult(case_id=case_id, located=located, points=points)


@router.get("/{case_id}/report.md", summary="Markdown dossier")
async def report_markdown(
    store: CaseStoreDep, ip_service: IPServiceDep, case_id: str
) -> PlainTextResponse:
    case = await _require_case(store, case_id)
    entities, edges = await asyncio.to_thread(store.get_graph, case_id)
    geo = await collect_geo(ip_service, _ips_in(entities))
    return PlainTextResponse(
        build_markdown(case, entities, edges, geo),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="dossier_{case_id}.md"'},
    )


@router.get(
    "/{case_id}/report.html",
    response_class=HTMLResponse,
    summary="Printable HTML dossier (Save as PDF)",
)
async def report_html(
    store: CaseStoreDep, ip_service: IPServiceDep, case_id: str
) -> HTMLResponse:
    case = await _require_case(store, case_id)
    entities, edges = await asyncio.to_thread(store.get_graph, case_id)
    geo = await collect_geo(ip_service, _ips_in(entities))
    return HTMLResponse(build_html(case, entities, edges, geo))


# ------------------------------------------------------- snapshots & diffing

@router.post("/{case_id}/snapshots", response_model=Snapshot, status_code=status.HTTP_201_CREATED)
async def create_snapshot(
    store: CaseStoreDep, case_id: str, label: str | None = Query(default=None)
) -> Snapshot:
    await _require_case(store, case_id)
    return await asyncio.to_thread(store.create_snapshot, case_id, label)


@router.get("/{case_id}/snapshots", response_model=list[Snapshot])
async def list_snapshots(store: CaseStoreDep, case_id: str) -> list[Snapshot]:
    await _require_case(store, case_id)
    return await asyncio.to_thread(store.list_snapshots, case_id)


@router.get("/{case_id}/diff", response_model=DiffResult)
async def diff_case(
    store: CaseStoreDep,
    case_id: str,
    base: str | None = Query(default=None, description="Snapshot id, or 'latest' (default)."),
    against: str = Query(default="current", description="'current' (default) or a snapshot id."),
) -> DiffResult:
    await _require_case(store, case_id)

    if base in (None, "latest"):
        snap = await asyncio.to_thread(store.latest_snapshot, case_id)
        if snap is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, "No snapshots yet — create one first."
            )
        base_id = snap.id
        old = await asyncio.to_thread(store.get_snapshot_graph, snap.id)
    else:
        old = await asyncio.to_thread(store.get_snapshot_graph, base)
        base_id = base
        if old is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Snapshot not found: {base}")

    if against == "current":
        new = await asyncio.to_thread(store.get_graph, case_id)
    else:
        new = await asyncio.to_thread(store.get_snapshot_graph, against)
        if new is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Snapshot not found: {against}")

    result = diff_graphs(old[0], old[1], new[0], new[1])
    return DiffResult(case_id=case_id, base=base_id, against=against, **result)


# --------------------------------------------------------------- manual intel

@router.post("/{case_id}/entities", response_model=list[Entity])
async def add_entities(
    store: CaseStoreDep, case_id: str, body: ManualEntity | list[ManualEntity]
) -> list[Entity]:
    await _require_case(store, case_id)
    items = body if isinstance(body, list) else [body]
    saved: list[Entity] = []
    for item in items:
        saved.append(await asyncio.to_thread(store.upsert_entity, case_id, _manual_entity(item)))
    await asyncio.to_thread(store.touch, case_id)
    return saved


@router.post("/{case_id}/edges", response_model=Edge)
async def add_edge(store: CaseStoreDep, case_id: str, body: ManualEdge) -> Edge:
    await _require_case(store, case_id)
    src, tgt, edge = _manual_edge(body)
    await asyncio.to_thread(store.upsert_entity, case_id, src)
    await asyncio.to_thread(store.upsert_entity, case_id, tgt)
    await asyncio.to_thread(store.upsert_edge, case_id, edge)
    await asyncio.to_thread(store.touch, case_id)
    return edge


@router.post("/{case_id}/import", response_model=ImportResult)
async def import_graph(store: CaseStoreDep, case_id: str, body: GraphImport) -> ImportResult:
    await _require_case(store, case_id)
    entities = [_manual_entity(e) for e in body.entities]
    edges: list[Edge] = []
    for m in body.edges:
        src, tgt, edge = _manual_edge(m)
        entities.extend([src, tgt])
        edges.append(edge)
    await asyncio.to_thread(store.bulk, case_id, entities, edges)
    return ImportResult(
        case_id=case_id, entities_added=len(body.entities), edges_added=len(body.edges)
    )


# ----------------------------------------------------------- enrich (SSE)

@router.get("/{case_id}/enrich", summary="Auto-pivot and merge findings into the case")
async def enrich_case(
    engine: CorrelationEngineDep,
    store: CaseStoreDep,
    case_id: str,
    target: str | None = Query(default=None, description="Seed. Omit to enrich all pivotable intel."),
    target_type: str | None = Query(default=None, alias="type"),
    max_depth: int = Query(default=2, ge=1, le=3),
    max_nodes: int = Query(default=60, ge=5, le=150),
) -> StreamingResponse:
    await _require_case(store, case_id)
    if target:
        seeds: list[tuple[str, str | None]] = [(target.strip(), target_type)]
    else:
        pivotable = await asyncio.to_thread(store.get_pivotable, case_id)
        seeds = [(e.value, e.type.value) for e in pivotable]

    async def event_source() -> AsyncIterator[str]:
        yield _sse("start", {"case_id": case_id, "target": target, "seeds": len(seeds)})
        if not seeds:
            yield _sse("error", {"message": "No pivotable intel yet — add a username/email/domain/ip."})
            yield _sse("done", {})
            return
        seen_nodes: set[str] = set()
        seen_edges: set[tuple[str, str, str]] = set()
        for value, kind in seeds:
            query = GraphQuery(target=value, type=kind, max_depth=max_depth, max_nodes=max_nodes)
            try:
                async for event, payload in engine.stream(query):
                    if event == "node":
                        await asyncio.to_thread(store.upsert_entity, case_id, Entity.model_validate(payload))
                        if payload["id"] in seen_nodes:
                            continue
                        seen_nodes.add(payload["id"])
                        yield _sse("node", payload)
                    elif event == "edge":
                        await asyncio.to_thread(store.upsert_edge, case_id, Edge.model_validate(payload))
                        key = (payload["source"], payload["target"], payload["relation"])
                        if key in seen_edges:
                            continue
                        seen_edges.add(key)
                        yield _sse("edge", payload)
                    else:
                        yield _sse(event, payload)
            except ValueError as exc:
                yield _sse("error", {"message": str(exc)})
            except Exception as exc:  # noqa: BLE001
                yield _sse("error", {"message": f"{type(exc).__name__}: {exc}"})
        await asyncio.to_thread(store.touch, case_id)
        yield _sse("done", {"nodes": len(seen_nodes), "edges": len(seen_edges)})

    return StreamingResponse(event_source(), media_type="text/event-stream", headers=_SSE_HEADERS)
