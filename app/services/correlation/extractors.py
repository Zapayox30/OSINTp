"""Turn module result envelopes into graph entities and edges.

Each extractor is a pure function of ``(parent_entity, envelope)`` so it can be
unit-tested without any network access. The relation confidences encode how
strongly a finding ties two entities together (e.g. an ``A`` record is a near
certainty, while a username derived from an email local-part is a weak guess).

Per-relation breadth caps keep recursive pivoting from exploding on noisy
sources such as certificate-transparency subdomain dumps.
"""

from __future__ import annotations

from app.schemas.common import ResultEnvelope, SourceStatus
from app.schemas.graph import Edge, Entity, EntityType

# Maximum children kept per relation, to bound graph growth.
CAPS = {
    "ips": 8,
    "mx": 5,
    "ns": 5,
    "san": 8,
    "subdomains": 12,
    "accounts": 10,
    "breaches": 10,
}


def _add(
    nodes: list[Entity],
    edges: list[Edge],
    parent: Entity,
    etype: EntityType,
    value: str,
    relation: str,
    conf: float,
    *,
    attrs: dict | None = None,
    leaf: bool = False,
    nid: str | None = None,
    label: str | None = None,
) -> None:
    value = str(value).strip().rstrip(".")
    if not value:
        return
    node_id = nid or f"{etype.value}:{value.lower()}"
    nodes.append(
        Entity(
            id=node_id,
            type=etype,
            value=value,
            label=label or value,
            attrs=attrs or {},
            confidence=round(parent.confidence * conf, 3),
            depth=parent.depth + 1,
            pivotable=not leaf,
            discovered_by=relation,
        )
    )
    edges.append(Edge(source=parent.id, target=node_id, relation=relation, confidence=conf))


def extract(parent: Entity, envelope: ResultEnvelope) -> tuple[list[Entity], list[Edge]]:
    """Dispatch extraction based on the envelope's producing module."""
    dispatch = {
        "username": _from_username,
        "email": _from_email,
        "domain": _from_domain,
        "ip": _from_ip,
    }
    handler = dispatch.get(envelope.module)
    if handler is None:
        return [], []
    nodes: list[Entity] = []
    edges: list[Edge] = []
    handler(parent, envelope, nodes, edges)
    return nodes, edges


def _from_username(parent, env, nodes, edges) -> None:
    for r in env.results:
        if r.status != SourceStatus.found:
            continue
        nid = f"account:{r.source.lower()}:{parent.value.lower()}"
        _add(
            nodes,
            edges,
            parent,
            EntityType.account,
            r.url or r.source,
            "has_account",
            0.9,
            attrs={"platform": r.source, "url": r.url, "category": r.category},
            leaf=True,
            nid=nid,
            label=r.source,
        )


def _from_email(parent, env, nodes, edges) -> None:
    local, _, domain = parent.value.partition("@")
    if local:
        _add(nodes, edges, parent, EntityType.username, local, "derived_username", 0.5)
    if domain:
        _add(nodes, edges, parent, EntityType.domain, domain, "email_domain", 0.7)

    for r in env.results:
        if r.source == "Gravatar" and r.status == SourceStatus.found:
            for url in (r.data.get("accounts") or [])[: CAPS["accounts"]]:
                _add(
                    nodes, edges, parent, EntityType.url, url, "linked_account", 0.7, leaf=True
                )
            name = r.data.get("display_name")
            if name:
                _add(nodes, edges, parent, EntityType.person, name, "identity", 0.6, leaf=True)
        if r.source == "HaveIBeenPwned" and r.status == SourceStatus.found:
            for breach in (r.data.get("breaches") or [])[: CAPS["breaches"]]:
                _add(nodes, edges, parent, EntityType.breach, breach, "breached_in", 0.85, leaf=True)


def _from_domain(parent, env, nodes, edges) -> None:
    for r in env.results:
        if r.source == "DNS" and r.status == SourceStatus.found:
            records = r.data.get("records", {})
            for ip in (records.get("A", []) + records.get("AAAA", []))[: CAPS["ips"]]:
                _add(nodes, edges, parent, EntityType.ip, ip, "resolves_to", 0.95)
            for mx in records.get("MX", [])[: CAPS["mx"]]:
                host = str(mx).split()[-1]
                _add(nodes, edges, parent, EntityType.domain, host, "mail_server", 0.8, leaf=True)
            for ns in records.get("NS", [])[: CAPS["ns"]]:
                _add(nodes, edges, parent, EntityType.domain, ns, "nameserver", 0.7, leaf=True)

        elif r.source == "WHOIS" and r.status == SourceStatus.found:
            emails = r.data.get("emails")
            emails = emails if isinstance(emails, list) else ([emails] if emails else [])
            for email in emails:
                _add(nodes, edges, parent, EntityType.email, email, "registrant_email", 0.8)
            org = r.data.get("org")
            if org:
                _add(
                    nodes, edges, parent, EntityType.organization, org, "registrant_org", 0.7,
                    leaf=True,
                )

        elif r.source == "TLS Certificate" and r.status == SourceStatus.found:
            for san in (r.data.get("subject_alt_names") or [])[: CAPS["san"]]:
                san = san.lstrip("*.")
                if san and san != parent.value:
                    _add(nodes, edges, parent, EntityType.domain, san, "tls_san", 0.6, leaf=True)

        elif r.source == "crt.sh" and r.status == SourceStatus.found:
            for sub in (r.data.get("subdomains") or [])[: CAPS["subdomains"]]:
                if sub and sub != parent.value:
                    _add(nodes, edges, parent, EntityType.domain, sub, "subdomain_of", 0.9, leaf=True)


def _from_ip(parent, env, nodes, edges) -> None:
    for r in env.results:
        if r.source == "Reverse DNS" and r.status == SourceStatus.found:
            for ptr in r.data.get("ptr", []):
                _add(nodes, edges, parent, EntityType.domain, ptr, "ptr", 0.7, leaf=True)
        elif r.source == "ip-api.com" and r.status == SourceStatus.found:
            org = r.data.get("org") or r.data.get("isp")
            if org:
                _add(nodes, edges, parent, EntityType.organization, org, "hosted_by", 0.7, leaf=True)
            asn = r.data.get("as")
            if asn:
                _add(nodes, edges, parent, EntityType.asn, asn, "announced_by", 0.7, leaf=True)
