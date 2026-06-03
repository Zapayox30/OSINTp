"""Username enumeration across public platforms.

For each registered site the service performs a single HTTP probe and maps the
response to a :class:`SourceStatus`. Probes run concurrently with a bounded
worker pool. No authentication is used — only publicly reachable endpoints.
"""

from __future__ import annotations

import re
from time import perf_counter

import httpx

from app.core.concurrency import gather_bounded
from app.core.logging import get_logger
from app.modules.username import Site
from app.modules.username.registry import available_categories, filter_sites
from app.schemas.common import SourceResult, SourceStatus
from app.schemas.username import UsernameQuery, UsernameResult

logger = get_logger(__name__)

# Permissive but URL-safe username pattern (prevents request smuggling).
USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class UsernameService:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    @staticmethod
    def validate_username(username: str) -> str:
        username = username.strip()
        if not USERNAME_RE.match(username):
            raise ValueError(
                "Invalid username: only letters, digits, '.', '_' and '-' are allowed "
                "(1-64 chars, must start with a letter or digit)."
            )
        return username

    async def investigate(self, query: UsernameQuery) -> UsernameResult:
        username = self.validate_username(query.username)
        sites = filter_sites(query.categories)

        results = await gather_bounded(
            [self._make_probe(site, username) for site in sites]
        )

        normalised: list[SourceResult] = []
        for site, outcome in zip(sites, results):
            if isinstance(outcome, BaseException):
                normalised.append(
                    SourceResult(
                        source=site.name,
                        category=site.category,
                        status=SourceStatus.error,
                        url=site.profile_url(username),
                        error=f"{type(outcome).__name__}: {outcome}",
                    )
                )
            else:
                normalised.append(outcome)

        found = [r for r in normalised if r.status == SourceStatus.found]
        if not query.include_not_found:
            shown = [r for r in normalised if r.status != SourceStatus.not_found]
        else:
            shown = normalised

        summary = {
            "sites_checked": len(sites),
            "found_count": len(found),
            "found_on": [r.source for r in found],
            "errors": sum(1 for r in normalised if r.status == SourceStatus.error),
            "rate_limited": sum(
                1 for r in normalised if r.status == SourceStatus.rate_limited
            ),
        }

        return UsernameResult(
            target=username,
            module="username",
            summary=summary,
            results=sorted(shown, key=lambda r: (r.status != SourceStatus.found, r.source)),
        )

    def _make_probe(self, site: Site, username: str):
        async def _factory() -> SourceResult:
            return await self._probe(site, username)

        return _factory

    async def _probe(self, site: Site, username: str) -> SourceResult:
        profile_url = site.profile_url(username)
        probe_url = site.probe_url(username)
        start = perf_counter()
        try:
            resp = await self._client.get(probe_url, headers=site.headers)
        except httpx.TimeoutException:
            return SourceResult(
                source=site.name,
                category=site.category,
                status=SourceStatus.error,
                url=profile_url,
                error="timeout",
                elapsed_ms=round((perf_counter() - start) * 1000, 1),
            )
        except httpx.HTTPError as exc:
            return SourceResult(
                source=site.name,
                category=site.category,
                status=SourceStatus.error,
                url=profile_url,
                error=str(exc) or type(exc).__name__,
                elapsed_ms=round((perf_counter() - start) * 1000, 1),
            )

        status = self._decide(site, resp)
        return SourceResult(
            source=site.name,
            category=site.category,
            status=status,
            url=profile_url if status == SourceStatus.found else None,
            data={"http_status": resp.status_code},
            elapsed_ms=round((perf_counter() - start) * 1000, 1),
        )

    @staticmethod
    def _decide(site: Site, resp: httpx.Response) -> SourceStatus:
        if resp.status_code == 429:
            return SourceStatus.rate_limited

        if site.check == "message":
            body = resp.text
            if site.found_messages:
                return (
                    SourceStatus.found
                    if any(m in body for m in site.found_messages)
                    else SourceStatus.not_found
                )
            if resp.status_code in site.not_found_codes:
                return SourceStatus.not_found
            has_error = any(m in body for m in site.error_messages)
            return SourceStatus.not_found if has_error else SourceStatus.found

        # status strategy
        if resp.status_code in site.not_found_codes:
            return SourceStatus.not_found
        if resp.status_code in site.claimed_codes:
            return SourceStatus.found
        return SourceStatus.error

    @staticmethod
    def categories() -> list[str]:
        return available_categories()
