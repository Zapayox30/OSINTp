"""Compute the difference between two case graphs (snapshots / current state)."""

from __future__ import annotations

from typing import Any

from app.schemas.graph import Edge, Entity


def _edge_key(e: Edge) -> tuple[str, str, str]:
    return (e.source, e.target, e.relation)


def diff_graphs(
    old_entities: list[Entity],
    old_edges: list[Edge],
    new_entities: list[Entity],
    new_edges: list[Edge],
) -> dict[str, Any]:
    """Return added/removed/changed entities and added/removed edges."""
    old_map = {e.id: e for e in old_entities}
    new_map = {e.id: e for e in new_entities}

    added_entities = [new_map[i] for i in new_map if i not in old_map]
    removed_entities = [old_map[i] for i in old_map if i not in new_map]

    changed_entities: list[dict[str, Any]] = []
    for i in old_map.keys() & new_map.keys():
        a, b = old_map[i], new_map[i]
        if a.confidence != b.confidence or a.origin != b.origin:
            changed_entities.append(
                {
                    "id": i,
                    "type": b.type.value,
                    "value": b.value,
                    "confidence_old": a.confidence,
                    "confidence_new": b.confidence,
                    "origin_old": a.origin,
                    "origin_new": b.origin,
                }
            )

    old_e = {_edge_key(e): e for e in old_edges}
    new_e = {_edge_key(e): e for e in new_edges}
    added_edges = [new_e[k] for k in new_e if k not in old_e]
    removed_edges = [old_e[k] for k in old_e if k not in new_e]

    return {
        "added_entities": added_entities,
        "removed_entities": removed_entities,
        "added_edges": added_edges,
        "removed_edges": removed_edges,
        "changed_entities": changed_entities,
        "summary": {
            "added_entities": len(added_entities),
            "removed_entities": len(removed_entities),
            "added_edges": len(added_edges),
            "removed_edges": len(removed_edges),
            "changed_entities": len(changed_entities),
        },
    }
