"""SQLite-backed store for cases, manual entities and saved graph edges.

Uses the standard-library :mod:`sqlite3` (no extra dependencies). A fresh
connection is opened per operation so the store is safe to call from worker
threads (e.g. via :func:`asyncio.to_thread`). Upserts *merge* rather than
overwrite, so re-discovering an entity keeps the strongest confidence and never
downgrades analyst-entered ("manual") intel.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from app.core.config import get_settings
from app.schemas.cases import Case
from app.schemas.graph import Edge, Entity, EntityType

PIVOTABLE_VALUE_TYPES = {"username", "email", "domain", "ip"}


def entity_id(etype: str, value: str) -> str:
    return f"{etype}:{value.strip().lower()}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CaseStore:
    def __init__(self, path: str) -> None:
        self._path = path

    # ------------------------------------------------------------- lifecycle

    def _connect(self) -> sqlite3.Connection:
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS cases (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    notes TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS entities (
                    case_id TEXT NOT NULL,
                    ent_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    value TEXT NOT NULL,
                    label TEXT,
                    attrs TEXT NOT NULL DEFAULT '{}',
                    confidence REAL NOT NULL DEFAULT 1.0,
                    depth INTEGER NOT NULL DEFAULT 0,
                    pivotable INTEGER NOT NULL DEFAULT 0,
                    discovered_by TEXT,
                    origin TEXT NOT NULL DEFAULT 'auto',
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (case_id, ent_id),
                    FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS edges (
                    case_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    target TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 1.0,
                    origin TEXT NOT NULL DEFAULT 'auto',
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (case_id, source, target, relation),
                    FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE
                );
                """
            )

    # ----------------------------------------------------------------- cases

    def create_case(self, name: str, notes: str | None = None) -> Case:
        cid = uuid.uuid4().hex[:12]
        ts = _now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO cases (id, name, notes, created_at, updated_at) VALUES (?,?,?,?,?)",
                (cid, name, notes, ts, ts),
            )
        return Case(id=cid, name=name, notes=notes, created_at=ts, updated_at=ts)

    def list_cases(self) -> list[Case]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM cases ORDER BY updated_at DESC").fetchall()
            return [self._case_from_row(conn, r) for r in rows]

    def get_case(self, case_id: str) -> Case | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
            return self._case_from_row(conn, row) if row else None

    def delete_case(self, case_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM cases WHERE id=?", (case_id,))
            return cur.rowcount > 0

    def touch(self, case_id: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE cases SET updated_at=? WHERE id=?", (_now(), case_id))

    def _case_from_row(self, conn: sqlite3.Connection, row: sqlite3.Row) -> Case:
        n_ent = conn.execute(
            "SELECT COUNT(*) FROM entities WHERE case_id=?", (row["id"],)
        ).fetchone()[0]
        n_edge = conn.execute(
            "SELECT COUNT(*) FROM edges WHERE case_id=?", (row["id"],)
        ).fetchone()[0]
        return Case(
            id=row["id"],
            name=row["name"],
            notes=row["notes"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            entity_count=n_ent,
            edge_count=n_edge,
        )

    # -------------------------------------------------------------- entities

    def upsert_entity(self, case_id: str, entity: Entity) -> Entity:
        with self._connect() as conn:
            merged = self._upsert_entity(conn, case_id, entity)
        return merged

    def _upsert_entity(self, conn: sqlite3.Connection, case_id: str, entity: Entity) -> Entity:
        existing = conn.execute(
            "SELECT * FROM entities WHERE case_id=? AND ent_id=?", (case_id, entity.id)
        ).fetchone()

        if existing is None:
            conn.execute(
                """INSERT INTO entities
                   (case_id, ent_id, type, value, label, attrs, confidence, depth,
                    pivotable, discovered_by, origin, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    case_id, entity.id, entity.type.value, entity.value, entity.label,
                    json.dumps(entity.attrs), entity.confidence, entity.depth,
                    int(entity.pivotable), entity.discovered_by, entity.origin, _now(),
                ),
            )
            return entity

        # Merge: never lose manual provenance or the strongest confidence.
        origin = "manual" if "manual" in (existing["origin"], entity.origin) else entity.origin
        confidence = max(existing["confidence"], entity.confidence)
        attrs = {**json.loads(existing["attrs"]), **entity.attrs}
        label = entity.label or existing["label"]
        depth = min(existing["depth"], entity.depth)
        pivotable = bool(existing["pivotable"]) or entity.pivotable
        conn.execute(
            """UPDATE entities SET label=?, attrs=?, confidence=?, depth=?,
               pivotable=?, origin=? WHERE case_id=? AND ent_id=?""",
            (label, json.dumps(attrs), confidence, depth, int(pivotable), origin,
             case_id, entity.id),
        )
        return Entity(
            id=entity.id, type=entity.type, value=existing["value"], label=label,
            attrs=attrs, confidence=confidence, depth=depth, pivotable=pivotable,
            discovered_by=existing["discovered_by"] or entity.discovered_by, origin=origin,
        )

    def upsert_edge(self, case_id: str, edge: Edge) -> None:
        with self._connect() as conn:
            self._upsert_edge(conn, case_id, edge)

    def _upsert_edge(self, conn: sqlite3.Connection, case_id: str, edge: Edge) -> None:
        existing = conn.execute(
            "SELECT confidence, origin FROM edges WHERE case_id=? AND source=? AND target=? AND relation=?",
            (case_id, edge.source, edge.target, edge.relation),
        ).fetchone()
        if existing is None:
            conn.execute(
                """INSERT INTO edges (case_id, source, target, relation, confidence, origin, created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (case_id, edge.source, edge.target, edge.relation, edge.confidence,
                 edge.origin, _now()),
            )
            return
        origin = "manual" if "manual" in (existing["origin"], edge.origin) else edge.origin
        confidence = max(existing["confidence"], edge.confidence)
        conn.execute(
            "UPDATE edges SET confidence=?, origin=? WHERE case_id=? AND source=? AND target=? AND relation=?",
            (confidence, origin, case_id, edge.source, edge.target, edge.relation),
        )

    def bulk(self, case_id: str, entities: list[Entity], edges: list[Edge]) -> tuple[int, int]:
        with self._connect() as conn:
            for e in entities:
                self._upsert_entity(conn, case_id, e)
            for ed in edges:
                self._upsert_edge(conn, case_id, ed)
            conn.execute("UPDATE cases SET updated_at=? WHERE id=?", (_now(), case_id))
        return len(entities), len(edges)

    # ----------------------------------------------------------------- reads

    def get_graph(self, case_id: str) -> tuple[list[Entity], list[Edge]]:
        with self._connect() as conn:
            ent_rows = conn.execute(
                "SELECT * FROM entities WHERE case_id=? ORDER BY depth, confidence DESC",
                (case_id,),
            ).fetchall()
            edge_rows = conn.execute(
                "SELECT * FROM edges WHERE case_id=?", (case_id,)
            ).fetchall()
        return [self._entity_from_row(r) for r in ent_rows], [
            Edge(
                source=r["source"], target=r["target"], relation=r["relation"],
                confidence=r["confidence"], origin=r["origin"],
            )
            for r in edge_rows
        ]

    def get_pivotable(self, case_id: str) -> list[Entity]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM entities WHERE case_id=? AND pivotable=1 AND type IN (?,?,?,?)",
                (case_id, *PIVOTABLE_VALUE_TYPES),
            ).fetchall()
        return [self._entity_from_row(r) for r in rows]

    @staticmethod
    def _entity_from_row(row: sqlite3.Row) -> Entity:
        return Entity(
            id=row["ent_id"],
            type=EntityType(row["type"]),
            value=row["value"],
            label=row["label"],
            attrs=json.loads(row["attrs"]),
            confidence=row["confidence"],
            depth=row["depth"],
            pivotable=bool(row["pivotable"]),
            discovered_by=row["discovered_by"],
            origin=row["origin"],
        )


@lru_cache
def get_store() -> CaseStore:
    store = CaseStore(get_settings().database_path)
    store.init_db()
    return store
