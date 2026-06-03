"""Tests for the correlation engine: pure extraction + private-IP graph."""

from __future__ import annotations

import httpx
import pytest

from app.schemas.common import ResultEnvelope, SourceResult, SourceStatus
from app.schemas.graph import Entity, EntityType, GraphQuery
from app.services.correlation import CorrelationEngine
from app.services.correlation.extractors import extract


def _seed(type_, value):
    return Entity(id=f"{type_.value}:{value}", type=type_, value=value, confidence=1.0, depth=0)


def test_extract_domain_cross_pivots_to_ip_and_email():
    parent = _seed(EntityType.domain, "acme.com")
    env = ResultEnvelope(
        target="acme.com",
        module="domain",
        results=[
            SourceResult(
                source="DNS",
                status=SourceStatus.found,
                data={"records": {"A": ["1.2.3.4"], "NS": ["ns1.acme.com."]}},
            ),
            SourceResult(
                source="WHOIS",
                status=SourceStatus.found,
                data={"emails": ["admin@acme.com"], "org": "ACME Inc"},
            ),
            SourceResult(
                source="crt.sh",
                status=SourceStatus.found,
                data={"subdomains": ["api.acme.com"], "count": 1},
            ),
        ],
    )
    nodes, edges = extract(parent, env)
    by_value = {n.value: n for n in nodes}

    # IP and WHOIS email are pivotable (drive cross-module correlation)...
    assert by_value["1.2.3.4"].type == EntityType.ip
    assert by_value["1.2.3.4"].pivotable is True
    assert by_value["admin@acme.com"].type == EntityType.email
    assert by_value["admin@acme.com"].pivotable is True
    # ...while nameservers, org and CT subdomains are leaves (no auto-pivot).
    assert by_value["ns1.acme.com"].pivotable is False
    assert by_value["api.acme.com"].pivotable is False
    assert by_value["ACME Inc"].pivotable is False
    assert {e.relation for e in edges} >= {"resolves_to", "registrant_email", "subdomain_of"}


def test_extract_email_derives_username_and_domain():
    parent = _seed(EntityType.email, "jane.doe@acme.com")
    env = ResultEnvelope(
        target="jane.doe@acme.com",
        module="email",
        results=[SourceResult(source="MX Records", status=SourceStatus.found, data={"mx": ["mx.acme.com"]})],
    )
    nodes, _ = extract(parent, env)
    by_type = {n.type: n for n in nodes}
    assert by_type[EntityType.username].value == "jane.doe"
    assert by_type[EntityType.username].pivotable is True
    assert by_type[EntityType.domain].value == "acme.com"
    assert by_type[EntityType.domain].pivotable is True


def test_extract_username_accounts_are_leaves():
    parent = _seed(EntityType.username, "torvalds")
    env = ResultEnvelope(
        target="torvalds",
        module="username",
        results=[
            SourceResult(source="GitHub", status=SourceStatus.found, url="https://github.com/torvalds"),
            SourceResult(source="Twitch", status=SourceStatus.not_found),
        ],
    )
    nodes, edges = extract(parent, env)
    assert len(nodes) == 1  # only the 'found' GitHub account
    assert nodes[0].type == EntityType.account
    assert nodes[0].pivotable is False
    assert edges[0].relation == "has_account"


def test_extract_unknown_module_is_empty():
    parent = _seed(EntityType.ip, "8.8.8.8")
    env = ResultEnvelope(target="8.8.8.8", module="mystery", results=[])
    assert extract(parent, env) == ([], [])


async def test_engine_private_ip_returns_seed_only():
    async with httpx.AsyncClient() as client:
        engine = CorrelationEngine(client)
        graph = await engine.build(GraphQuery(target="10.0.0.5", max_depth=2))
    assert graph.seed_type == "ip"
    assert len(graph.nodes) == 1
    assert graph.nodes[0].value == "10.0.0.5"
    assert graph.edges == []


async def test_engine_rejects_invalid_seed():
    async with httpx.AsyncClient() as client:
        engine = CorrelationEngine(client)
        with pytest.raises(ValueError):
            await engine.build(GraphQuery(target="bad!seed", type="username"))


def test_graph_sse_endpoint_private_ip(client):
    resp = client.get("/api/v1/graph", params={"target": "10.0.0.5"})
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    body = resp.text
    assert "event: meta" in body
    assert '"seed_type": "ip"' in body
    assert "event: node" in body
    assert "event: summary" in body
    assert "event: done" in body
