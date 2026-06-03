"""Domain intelligence from public sources.

Collects DNS records, WHOIS registration data, the TLS certificate presented on
port 443, and subdomains observed in Certificate Transparency logs (crt.sh).
Blocking calls (WHOIS, TLS handshake) are offloaded to a thread pool.
"""

from __future__ import annotations

import asyncio
import re
import socket
import ssl
from collections.abc import AsyncIterator
from datetime import datetime
from time import perf_counter
from typing import Any
from urllib.parse import urlparse

import dns.asyncresolver
import dns.resolver
import httpx

from app.core.concurrency import gather_bounded, stream_bounded
from app.core.logging import get_logger
from app.schemas.common import SourceResult, SourceStatus
from app.schemas.domain import DomainQuery, DomainResult

logger = get_logger(__name__)

_DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)([A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,}$"
)
_RECORD_TYPES = ("A", "AAAA", "MX", "NS", "TXT", "SOA", "CNAME")


class DomainService:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    @staticmethod
    def normalize_domain(value: str) -> str:
        value = value.strip().lower()
        if "://" in value:
            value = urlparse(value).netloc or value
        value = value.split("/")[0].split(":")[0]
        if value.startswith("www."):
            value = value[4:]
        if not _DOMAIN_RE.match(value):
            raise ValueError(f"Invalid domain name: {value!r}")
        return value

    async def investigate(self, query: DomainQuery) -> DomainResult:
        domain = self.normalize_domain(query.domain)
        results: list[SourceResult] = []

        # DNS records (resolved concurrently per type)
        dns_results = await gather_bounded(
            [self._make_dns_probe(domain, rtype) for rtype in _RECORD_TYPES]
        )
        records: dict[str, list[str]] = {}
        for rtype, outcome in zip(_RECORD_TYPES, dns_results):
            if isinstance(outcome, BaseException):
                continue
            if outcome.status == SourceStatus.found:
                records[rtype] = outcome.data.get("records", [])
        results.append(
            SourceResult(
                source="DNS",
                category="dns",
                status=SourceStatus.found if records else SourceStatus.not_found,
                data={"records": records},
            )
        )

        # WHOIS + TLS certificate (run concurrently)
        whois_res, tls_res = await asyncio.gather(
            self._whois(domain), self._tls_certificate(domain)
        )
        results.append(whois_res)
        results.append(tls_res)

        # Subdomains via Certificate Transparency
        if query.include_subdomains:
            results.append(await self._crtsh_subdomains(domain))

        summary = {
            "domain": domain,
            "record_types": sorted(records.keys()),
            "ipv4": records.get("A", []),
            "nameservers": records.get("NS", []),
        }
        return DomainResult(target=domain, module="domain", summary=summary, results=results)

    async def stream(self, query: DomainQuery) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        domain = self.normalize_domain(query.domain)
        factories: list = [self._make_dns_probe(domain, rt) for rt in _RECORD_TYPES]
        factories.append(lambda: self._whois(domain))
        factories.append(lambda: self._tls_certificate(domain))
        if query.include_subdomains:
            factories.append(lambda: self._crtsh_subdomains(domain))
        yield "meta", {"module": "domain", "target": domain, "total": len(factories)}

        records: dict[str, list[str]] = {}
        async for outcome in stream_bounded(factories):
            if isinstance(outcome, BaseException):
                continue
            if outcome.source.startswith("DNS:") and outcome.status == SourceStatus.found:
                rtype = outcome.source.split(":", 1)[1]
                records[rtype] = outcome.data.get("records", [])
            yield "result", outcome.model_dump(mode="json")

        yield "summary", {
            "domain": domain,
            "record_types": sorted(records.keys()),
            "ipv4": records.get("A", []),
            "nameservers": records.get("NS", []),
        }

    def _make_dns_probe(self, domain: str, rtype: str):
        async def _factory() -> SourceResult:
            return await self._dns_record(domain, rtype)

        return _factory

    async def _dns_record(self, domain: str, rtype: str) -> SourceResult:
        try:
            answers = await dns.asyncresolver.resolve(domain, rtype)
            values = [r.to_text() for r in answers]
            return SourceResult(
                source=f"DNS:{rtype}",
                category="dns",
                status=SourceStatus.found,
                data={"records": values},
            )
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
            return SourceResult(
                source=f"DNS:{rtype}", category="dns", status=SourceStatus.not_found
            )
        except Exception as exc:  # noqa: BLE001 — DNS errors are heterogeneous
            return SourceResult(
                source=f"DNS:{rtype}",
                category="dns",
                status=SourceStatus.error,
                error=str(exc),
            )

    async def _whois(self, domain: str) -> SourceResult:
        try:
            record = await asyncio.get_running_loop().run_in_executor(
                None, self._whois_blocking, domain
            )
        except Exception as exc:  # noqa: BLE001 — whois backend raises broadly
            return SourceResult(
                source="WHOIS", category="registration", status=SourceStatus.error, error=str(exc)
            )

        if not record or not record.get("domain_name"):
            return SourceResult(
                source="WHOIS", category="registration", status=SourceStatus.not_found
            )
        return SourceResult(
            source="WHOIS",
            category="registration",
            status=SourceStatus.found,
            data=record,
        )

    @staticmethod
    def _whois_blocking(domain: str) -> dict:
        import whois  # imported lazily; backend shells out to the system resolver

        def _norm(value):
            if isinstance(value, list):
                return [_norm(v) for v in value]
            if isinstance(value, datetime):
                return value.isoformat()
            return value

        data = whois.whois(domain)
        fields = (
            "domain_name",
            "registrar",
            "creation_date",
            "expiration_date",
            "updated_date",
            "name_servers",
            "status",
            "emails",
            "org",
            "country",
        )
        return {f: _norm(data.get(f)) for f in fields if data.get(f)}

    async def _tls_certificate(self, domain: str) -> SourceResult:
        try:
            cert = await asyncio.get_running_loop().run_in_executor(
                None, self._tls_blocking, domain
            )
        except (OSError, ssl.SSLError, socket.timeout) as exc:
            return SourceResult(
                source="TLS Certificate",
                category="tls",
                status=SourceStatus.error,
                error=str(exc),
            )
        return SourceResult(
            source="TLS Certificate",
            category="tls",
            status=SourceStatus.found,
            url=f"https://{domain}",
            data=cert,
        )

    @staticmethod
    def _tls_blocking(domain: str, port: int = 443) -> dict:
        ctx = ssl.create_default_context()
        with socket.create_connection((domain, port), timeout=8) as sock:
            with ctx.wrap_socket(sock, server_hostname=domain) as ssock:
                cert = ssock.getpeercert()
        subject = dict(x[0] for x in cert.get("subject", []))
        issuer = dict(x[0] for x in cert.get("issuer", []))
        sans = [v for k, v in cert.get("subjectAltName", []) if k == "DNS"]
        return {
            "subject_cn": subject.get("commonName"),
            "issuer": issuer.get("organizationName") or issuer.get("commonName"),
            "not_before": cert.get("notBefore"),
            "not_after": cert.get("notAfter"),
            "subject_alt_names": sans,
        }

    async def _crtsh_subdomains(self, domain: str) -> SourceResult:
        url = f"https://crt.sh/?q=%25.{domain}&output=json"
        start = perf_counter()
        try:
            resp = await self._client.get(url)
        except httpx.HTTPError as exc:
            return SourceResult(
                source="crt.sh", category="ct-logs", status=SourceStatus.error, error=str(exc)
            )
        if resp.status_code != 200:
            return SourceResult(
                source="crt.sh",
                category="ct-logs",
                status=SourceStatus.error,
                error=f"Unexpected status {resp.status_code}",
            )
        try:
            entries = resp.json()
        except ValueError:
            return SourceResult(
                source="crt.sh",
                category="ct-logs",
                status=SourceStatus.error,
                error="Malformed JSON from crt.sh",
            )

        subdomains: set[str] = set()
        for entry in entries:
            for name in str(entry.get("name_value", "")).splitlines():
                name = name.strip().lower().lstrip("*.")
                if name.endswith(domain):
                    subdomains.add(name)

        ordered = sorted(subdomains)
        return SourceResult(
            source="crt.sh",
            category="ct-logs",
            status=SourceStatus.found if ordered else SourceStatus.not_found,
            url=f"https://crt.sh/?q=%25.{domain}",
            data={"count": len(ordered), "subdomains": ordered},
            elapsed_ms=round((perf_counter() - start) * 1000, 1),
        )
