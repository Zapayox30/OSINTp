"""Schemas for the entity-correlation graph."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class EntityType(str, Enum):
    username = "username"
    email = "email"
    domain = "domain"
    ip = "ip"
    url = "url"
    account = "account"
    person = "person"
    organization = "organization"
    asn = "asn"
    breach = "breach"


# Entity types the engine knows how to investigate further (pivot from).
PIVOTABLE_TYPES = {EntityType.username, EntityType.email, EntityType.domain, EntityType.ip}


class Entity(BaseModel):
    """A node in the correlation graph."""

    id: str = Field(..., description="Stable identifier, e.g. 'domain:example.com'.")
    type: EntityType
    value: str
    label: str | None = None
    attrs: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    depth: int = 0
    pivotable: bool = True
    discovered_by: str | None = Field(default=None, description="Relation that surfaced it.")


class Edge(BaseModel):
    """A directed, typed relationship between two entities."""

    source: str
    target: str
    relation: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class GraphQuery(BaseModel):
    target: str = Field(..., min_length=1, max_length=253, examples=["example.com"])
    type: str | None = Field(default=None, description="Force the seed type. Auto-detected otherwise.")
    max_depth: int = Field(default=2, ge=1, le=3, description="How far to pivot from the seed.")
    max_nodes: int = Field(default=60, ge=5, le=150, description="Hard cap on graph size.")


class GraphResult(BaseModel):
    target: str
    seed_type: str
    nodes: list[Entity] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)
    stats: dict[str, Any] = Field(default_factory=dict)
