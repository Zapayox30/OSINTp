"""Schemas for cases / dossiers and manual intelligence input."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.graph import Edge, Entity


class CaseCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120, examples=["Operation Nightfall"])
    notes: str | None = Field(default=None, max_length=4000)


class Case(BaseModel):
    id: str
    name: str
    notes: str | None = None
    created_at: datetime
    updated_at: datetime
    entity_count: int = 0
    edge_count: int = 0


class ManualEntity(BaseModel):
    """A fact the analyst already knows, added by hand."""

    type: str = Field(
        ...,
        description="Entity type: username|email|domain|ip|phone|address|person|"
        "organization|url|note|account|asn|breach.",
        examples=["email"],
    )
    value: str = Field(..., min_length=1, max_length=2000, examples=["jane.doe@acme.com"])
    label: str | None = None
    attrs: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class ManualEdge(BaseModel):
    """A relationship the analyst already knows, between two entities."""

    source_type: str
    source_value: str
    target_type: str
    target_value: str
    relation: str = Field(..., min_length=1, max_length=60, examples=["owns"])
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class GraphImport(BaseModel):
    """Bulk upload of prior research."""

    entities: list[ManualEntity] = Field(default_factory=list)
    edges: list[ManualEdge] = Field(default_factory=list)


class CaseGraph(BaseModel):
    case: Case
    entities: list[Entity] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)


class ImportResult(BaseModel):
    case_id: str
    entities_added: int
    edges_added: int


class GeoPoint(BaseModel):
    ip: str
    lat: float | None = None
    lon: float | None = None
    country: str | None = None
    city: str | None = None
    org: str | None = None
    asn: str | None = None


class MapResult(BaseModel):
    case_id: str
    located: int = 0
    points: list[GeoPoint] = Field(default_factory=list)


class Snapshot(BaseModel):
    id: str
    case_id: str
    label: str | None = None
    created_at: datetime
    entity_count: int = 0
    edge_count: int = 0


class DiffResult(BaseModel):
    case_id: str
    base: str
    against: str
    added_entities: list[Entity] = Field(default_factory=list)
    removed_entities: list[Entity] = Field(default_factory=list)
    added_edges: list[Edge] = Field(default_factory=list)
    removed_edges: list[Edge] = Field(default_factory=list)
    changed_entities: list[dict[str, Any]] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
