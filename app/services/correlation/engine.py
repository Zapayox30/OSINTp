"""Recursive auto-pivoting correlation engine.

Starting from a seed target, the engine investigates the entity with the
matching module, extracts new entities/edges from the result, and enqueues the
*pivotable* ones for the next breadth-first level — bounded by ``max_depth`` and
``max_nodes``. Results stream out as they are discovered so a UI can draw the
graph live.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.core.concurrency import stream_bounded
from app.core.detect import detect_type
from app.core.logging import get_logger
from app.schemas.domain import DomainQuery
from app.schemas.email import EmailQuery
from app.schemas.graph import Edge, Entity, EntityType, GraphQuery, GraphResult
from app.schemas.ip import IPQuery
from app.schemas.phone import PhoneQuery
from app.schemas.username import UsernameQuery
from app.services.correlation.extractors import extract
from app.services.domain_service import DomainService
from app.services.email_service import EmailService
from app.services.ip_service import IPService
from app.services.phone_service import PhoneService
from app.services.username_service import UsernameService

logger = get_logger(__name__)

_TYPE_MAP = {
    "username": EntityType.username,
    "email": EntityType.email,
    "domain": EntityType.domain,
    "ip": EntityType.ip,
    "phone": EntityType.phone,
}


class CorrelationEngine:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._username = UsernameService(client)
        self._email = EmailService(client)
        self._domain = DomainService(client)
        self._ip = IPService(client)
        self._phone = PhoneService()

    # ------------------------------------------------------------------ public

    async def stream(
        self, query: GraphQuery
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """Yield ``(event, payload)`` pairs: meta, node, edge, progress, summary."""
        seed = self._build_seed(query)  # may raise ValueError
        max_depth = query.max_depth
        max_nodes = query.max_nodes

        nodes: dict[str, Entity] = {seed.id: seed}
        edges_seen: set[tuple[str, str, str]] = set()

        yield "meta", {
            "target": seed.value,
            "seed_type": seed.type.value,
            "max_depth": max_depth,
            "max_nodes": max_nodes,
        }
        yield "node", seed.model_dump(mode="json")

        frontier = [seed]
        depth = 0
        while frontier and depth < max_depth and len(nodes) < max_nodes:
            factories = [self._make_expand(e) for e in frontier if e.pivotable]
            next_frontier: list[Entity] = []

            async for outcome in stream_bounded(factories):
                if isinstance(outcome, BaseException):
                    continue
                new_nodes, new_edges = outcome

                for ent in new_nodes:
                    existing = nodes.get(ent.id)
                    if existing is None:
                        if len(nodes) >= max_nodes:
                            continue
                        nodes[ent.id] = ent
                        yield "node", ent.model_dump(mode="json")
                        if ent.pivotable and ent.type in _PIVOT_TYPES and ent.depth < max_depth:
                            next_frontier.append(ent)
                    elif ent.confidence > existing.confidence:
                        existing.confidence = ent.confidence

                for ed in new_edges:
                    key = (ed.source, ed.target, ed.relation)
                    if key in edges_seen:
                        continue
                    if ed.source not in nodes or ed.target not in nodes:
                        continue
                    edges_seen.add(key)
                    yield "edge", ed.model_dump(mode="json")

                yield "progress", {
                    "nodes": len(nodes),
                    "edges": len(edges_seen),
                    "depth": depth + 1,
                }

            frontier = next_frontier
            depth += 1

        yield "summary", self._stats(nodes, edges_seen, depth)

    async def build(self, query: GraphQuery) -> GraphResult:
        """Collect the full graph (non-streaming) for plain API consumers."""
        nodes: list[Entity] = []
        edges: list[Edge] = []
        stats: dict[str, Any] = {}
        seed_value = query.target
        seed_type = query.type or detect_type(query.target)
        async for event, payload in self.stream(query):
            if event == "node":
                nodes.append(Entity.model_validate(payload))
            elif event == "edge":
                edges.append(Edge.model_validate(payload))
            elif event == "meta":
                seed_value = payload["target"]
                seed_type = payload["seed_type"]
            elif event == "summary":
                stats = payload
        return GraphResult(
            target=seed_value, seed_type=seed_type, nodes=nodes, edges=edges, stats=stats
        )

    # ----------------------------------------------------------------- internal

    def _build_seed(self, query: GraphQuery) -> Entity:
        raw = query.target.strip()
        kind = (query.type or detect_type(raw)).lower()
        etype = _TYPE_MAP.get(kind)
        if etype is None:
            raise ValueError(f"Unsupported seed type: {kind!r}")
        value = self._normalize(etype, raw)  # may raise ValueError
        return Entity(
            id=f"{etype.value}:{value.lower()}",
            type=etype,
            value=value,
            label=value,
            confidence=1.0,
            depth=0,
            pivotable=True,
            discovered_by="seed",
        )

    def _normalize(self, etype: EntityType, value: str) -> str:
        if etype is EntityType.username:
            return self._username.validate_username(value)
        if etype is EntityType.domain:
            return self._domain.normalize_domain(value)
        if etype is EntityType.ip:
            return str(self._ip.parse_ip(value))
        if etype is EntityType.email:
            email = value.strip().lower()
            if "@" not in email:
                raise ValueError(f"Invalid email: {value!r}")
            return email
        return value

    def _make_expand(self, entity: Entity):
        async def _factory() -> tuple[list[Entity], list[Edge]]:
            envelope = await self._investigate(entity)
            if envelope is None:
                return [], []
            return extract(entity, envelope)

        return _factory

    async def _investigate(self, entity: Entity):
        try:
            if entity.type is EntityType.username:
                return await self._username.investigate(UsernameQuery(username=entity.value))
            if entity.type is EntityType.email:
                return await self._email.investigate(EmailQuery(email=entity.value))
            if entity.type is EntityType.domain:
                return await self._domain.investigate(
                    DomainQuery(domain=entity.value, include_subdomains=True)
                )
            if entity.type is EntityType.ip:
                return await self._ip.investigate(IPQuery(ip=entity.value))
            if entity.type is EntityType.phone:
                return await self._phone.investigate(PhoneQuery(phone=entity.value))
        except Exception as exc:  # noqa: BLE001 — a bad pivot must not abort the graph
            logger.debug("pivot failed for %s: %s", entity.id, exc)
            return None
        return None

    @staticmethod
    def _stats(nodes: dict[str, Entity], edges: set, depth_reached: int) -> dict[str, Any]:
        by_type: dict[str, int] = {}
        for ent in nodes.values():
            by_type[ent.type.value] = by_type.get(ent.type.value, 0) + 1
        top = sorted(
            (e for e in nodes.values() if e.depth > 0),
            key=lambda e: e.confidence,
            reverse=True,
        )[:8]
        return {
            "nodes_total": len(nodes),
            "edges_total": len(edges),
            "depth_reached": depth_reached,
            "by_type": by_type,
            "top_entities": [
                {"value": e.value, "type": e.type.value, "confidence": e.confidence}
                for e in top
            ],
        }


# Local copy to avoid importing the set from schemas at call time on the hot path.
_PIVOT_TYPES = {EntityType.username, EntityType.email, EntityType.domain, EntityType.ip}
