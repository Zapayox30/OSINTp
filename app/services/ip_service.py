"""IP address intelligence from public sources.

Provides geolocation and network ownership (ip-api.com, no key required),
reverse DNS (PTR) and—when an ``IPINFO_TOKEN`` is set—enriched data from
ipinfo.io. Private/reserved addresses are flagged and external lookups skipped.
"""

from __future__ import annotations

import ipaddress
from collections.abc import AsyncIterator
from typing import Any

import dns.asyncresolver
import httpx

from app.core.concurrency import stream_bounded
from app.core.config import get_settings
from app.core.logging import get_logger
from app.schemas.common import SourceResult, SourceStatus
from app.schemas.ip import IPQuery, IPResult

logger = get_logger(__name__)

_IPAPI_FIELDS = (
    "status,message,continent,country,countryCode,region,regionName,city,zip,"
    "lat,lon,timezone,isp,org,as,asname,reverse,mobile,proxy,hosting,query"
)


class IPService:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client
        self._settings = get_settings()

    @staticmethod
    def parse_ip(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
        return ipaddress.ip_address(value.strip())

    async def investigate(self, query: IPQuery) -> IPResult:
        ip = self.parse_ip(query.ip)
        results: list[SourceResult] = []
        summary: dict = {
            "ip": str(ip),
            "version": ip.version,
            "is_private": ip.is_private,
            "is_global": ip.is_global,
        }

        if not ip.is_global:
            results.append(
                SourceResult(
                    source="Classification",
                    category="meta",
                    status=SourceStatus.found,
                    data={
                        "is_private": ip.is_private,
                        "is_loopback": ip.is_loopback,
                        "is_reserved": ip.is_reserved,
                        "is_multicast": ip.is_multicast,
                    },
                )
            )
            return IPResult(target=str(ip), module="ip", summary=summary, results=results)

        # Reverse DNS
        results.append(await self._reverse_dns(ip))

        # ip-api.com geolocation
        geo = await self._ipapi(str(ip))
        results.append(geo)
        if geo.status == SourceStatus.found:
            summary["country"] = geo.data.get("country")
            summary["city"] = geo.data.get("city")
            summary["org"] = geo.data.get("org") or geo.data.get("isp")
            summary["asn"] = geo.data.get("as")

        # ipinfo.io (optional)
        results.append(await self._ipinfo(str(ip)))

        # Shodan (optional)
        shodan = await self._shodan(str(ip))
        results.append(shodan)
        if shodan.status == SourceStatus.found:
            summary["open_ports"] = shodan.data.get("ports", [])

        return IPResult(target=str(ip), module="ip", summary=summary, results=results)

    async def stream(self, query: IPQuery) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        ip = self.parse_ip(query.ip)
        if not ip.is_global:
            yield "meta", {"module": "ip", "target": str(ip), "total": 1}
            yield "result", SourceResult(
                source="Classification",
                category="meta",
                status=SourceStatus.found,
                data={
                    "is_private": ip.is_private,
                    "is_loopback": ip.is_loopback,
                    "is_reserved": ip.is_reserved,
                    "is_multicast": ip.is_multicast,
                },
            ).model_dump(mode="json")
            yield "summary", {"ip": str(ip), "is_private": ip.is_private, "is_global": False}
            return

        factories = [
            lambda: self._reverse_dns(ip),
            lambda: self._ipapi(str(ip)),
            lambda: self._ipinfo(str(ip)),
            lambda: self._shodan(str(ip)),
        ]
        yield "meta", {"module": "ip", "target": str(ip), "total": len(factories)}
        summary: dict[str, Any] = {
            "ip": str(ip),
            "version": ip.version,
            "is_private": False,
            "is_global": True,
        }
        async for outcome in stream_bounded(factories):
            if isinstance(outcome, BaseException):
                continue
            if outcome.source == "ip-api.com" and outcome.status == SourceStatus.found:
                summary["country"] = outcome.data.get("country")
                summary["city"] = outcome.data.get("city")
                summary["org"] = outcome.data.get("org") or outcome.data.get("isp")
                summary["asn"] = outcome.data.get("as")
            yield "result", outcome.model_dump(mode="json")
        yield "summary", summary

    async def _reverse_dns(self, ip) -> SourceResult:
        try:
            answer = await dns.asyncresolver.resolve_address(str(ip))
            names = [r.to_text().rstrip(".") for r in answer]
            return SourceResult(
                source="Reverse DNS",
                category="dns",
                status=SourceStatus.found,
                data={"ptr": names},
            )
        except Exception as exc:  # noqa: BLE001 — DNS errors are heterogeneous
            return SourceResult(
                source="Reverse DNS",
                category="dns",
                status=SourceStatus.not_found,
                error=str(exc),
            )

    async def _ipapi(self, ip: str) -> SourceResult:
        url = f"http://ip-api.com/json/{ip}?fields={_IPAPI_FIELDS}"
        try:
            resp = await self._client.get(url)
        except httpx.HTTPError as exc:
            return SourceResult(
                source="ip-api.com", category="geo", status=SourceStatus.error, error=str(exc)
            )
        if resp.status_code == 429:
            return SourceResult(
                source="ip-api.com", category="geo", status=SourceStatus.rate_limited
            )
        if resp.status_code != 200:
            return SourceResult(
                source="ip-api.com",
                category="geo",
                status=SourceStatus.error,
                error=f"Unexpected status {resp.status_code}",
            )
        try:
            payload = resp.json()
        except ValueError:
            return SourceResult(
                source="ip-api.com",
                category="geo",
                status=SourceStatus.error,
                error="Malformed response",
            )
        if payload.get("status") != "success":
            return SourceResult(
                source="ip-api.com",
                category="geo",
                status=SourceStatus.not_found,
                error=payload.get("message"),
            )
        payload.pop("status", None)
        return SourceResult(
            source="ip-api.com", category="geo", status=SourceStatus.found, data=payload
        )

    async def _ipinfo(self, ip: str) -> SourceResult:
        if not self._settings.ipinfo_token:
            return SourceResult(
                source="ipinfo.io",
                category="geo",
                status=SourceStatus.skipped,
                error="No IPINFO_TOKEN configured.",
            )
        url = f"https://ipinfo.io/{ip}/json?token={self._settings.ipinfo_token}"
        try:
            resp = await self._client.get(url)
            resp.raise_for_status()
            return SourceResult(
                source="ipinfo.io",
                category="geo",
                status=SourceStatus.found,
                data=resp.json(),
            )
        except httpx.HTTPError as exc:
            return SourceResult(
                source="ipinfo.io", category="geo", status=SourceStatus.error, error=str(exc)
            )

    async def _shodan(self, ip: str) -> SourceResult:
        if not self._settings.shodan_api_key:
            return SourceResult(
                source="Shodan",
                category="hosts",
                status=SourceStatus.skipped,
                error="No SHODAN_API_KEY configured.",
            )
        url = f"https://api.shodan.io/shodan/host/{ip}?key={self._settings.shodan_api_key}"
        try:
            resp = await self._client.get(url)
        except httpx.HTTPError as exc:
            return SourceResult(
                source="Shodan", category="hosts", status=SourceStatus.error, error=str(exc)
            )
        if resp.status_code == 404:
            return SourceResult(source="Shodan", category="hosts", status=SourceStatus.not_found)
        if resp.status_code == 401:
            return SourceResult(
                source="Shodan", category="hosts", status=SourceStatus.error, error="Invalid API key"
            )
        if resp.status_code != 200:
            return SourceResult(
                source="Shodan",
                category="hosts",
                status=SourceStatus.error,
                error=f"Unexpected status {resp.status_code}",
            )
        payload = resp.json()
        services = [
            {"port": item.get("port"), "transport": item.get("transport"), "product": item.get("product")}
            for item in payload.get("data", [])
        ]
        return SourceResult(
            source="Shodan",
            category="hosts",
            status=SourceStatus.found,
            url=f"https://www.shodan.io/host/{ip}",
            data={
                "ports": payload.get("ports", []),
                "hostnames": payload.get("hostnames", []),
                "org": payload.get("org"),
                "os": payload.get("os"),
                "vulns": list(payload.get("vulns", [])),
                "services": services[:20],
            },
        )
