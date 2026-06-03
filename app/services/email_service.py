"""Email intelligence from public, no-auth sources.

Combines syntactic validation, deliverability signals (MX records), a Gravatar
lookup and a derived-username hint. HaveIBeenPwned breach lookups are performed
only when an API key is configured.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from typing import Any

import dns.asyncresolver
import dns.resolver
import httpx
from email_validator import EmailNotValidError, validate_email

from app.core.concurrency import stream_bounded
from app.core.config import get_settings
from app.core.logging import get_logger
from app.schemas.common import SourceResult, SourceStatus
from app.schemas.email import EmailQuery, EmailResult

logger = get_logger(__name__)

_HIBP_BASE = "https://haveibeenpwned.com/api/v3"


class EmailService:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client
        self._settings = get_settings()

    async def investigate(self, query: EmailQuery) -> EmailResult:
        email = str(query.email).strip().lower()
        local_part, _, domain = email.partition("@")

        results: list[SourceResult] = []
        summary: dict = {"email": email, "domain": domain, "derived_username": local_part}

        # 1. Syntax / normalisation
        results.append(self._syntax_check(email))

        # 2. MX records (deliverability signal)
        mx_result = await self._mx_check(domain)
        results.append(mx_result)
        summary["has_mx"] = mx_result.status == SourceStatus.found

        # 3. Gravatar
        results.append(await self._gravatar_check(email))

        # 4. HaveIBeenPwned (optional, key-gated)
        results.append(await self._hibp_check(email))

        summary["has_gravatar"] = any(
            r.source == "Gravatar" and r.status == SourceStatus.found for r in results
        )

        return EmailResult(target=email, module="email", summary=summary, results=results)

    async def stream(self, query: EmailQuery) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        email = str(query.email).strip().lower()
        local_part, _, domain = email.partition("@")
        factories = [
            lambda: self._syntax_async(email),
            lambda: self._mx_check(domain),
            lambda: self._gravatar_check(email),
            lambda: self._hibp_check(email),
        ]
        yield "meta", {"module": "email", "target": email, "total": len(factories)}
        summary: dict[str, Any] = {
            "email": email,
            "domain": domain,
            "derived_username": local_part,
        }
        async for outcome in stream_bounded(factories):
            if isinstance(outcome, BaseException):
                continue
            if outcome.source == "MX Records":
                summary["has_mx"] = outcome.status == SourceStatus.found
            elif outcome.source == "Gravatar":
                summary["has_gravatar"] = outcome.status == SourceStatus.found
            yield "result", outcome.model_dump(mode="json")
        yield "summary", summary

    async def _syntax_async(self, email: str) -> SourceResult:
        return self._syntax_check(email)

    @staticmethod
    def _syntax_check(email: str) -> SourceResult:
        try:
            info = validate_email(email, check_deliverability=False)
            return SourceResult(
                source="Syntax",
                category="validation",
                status=SourceStatus.found,
                data={"normalized": info.normalized, "domain": info.domain},
            )
        except EmailNotValidError as exc:
            return SourceResult(
                source="Syntax",
                category="validation",
                status=SourceStatus.error,
                error=str(exc),
            )

    async def _mx_check(self, domain: str) -> SourceResult:
        try:
            answers = await dns.asyncresolver.resolve(domain, "MX")
            hosts = sorted(
                (str(r.exchange).rstrip(".") for r in answers),
                key=lambda h: h,
            )
            return SourceResult(
                source="MX Records",
                category="dns",
                status=SourceStatus.found,
                data={"mx": hosts},
            )
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
            return SourceResult(
                source="MX Records",
                category="dns",
                status=SourceStatus.not_found,
                data={"mx": []},
            )
        except Exception as exc:  # noqa: BLE001 — DNS errors are heterogeneous
            return SourceResult(
                source="MX Records",
                category="dns",
                status=SourceStatus.error,
                error=str(exc),
            )

    async def _gravatar_check(self, email: str) -> SourceResult:
        digest = hashlib.md5(email.encode("utf-8")).hexdigest()  # noqa: S324 — Gravatar spec
        avatar_url = f"https://www.gravatar.com/avatar/{digest}?d=404"
        profile_url = f"https://www.gravatar.com/{digest}"
        try:
            resp = await self._client.get(avatar_url)
        except httpx.HTTPError as exc:
            return SourceResult(
                source="Gravatar",
                category="social",
                status=SourceStatus.error,
                error=str(exc),
            )

        if resp.status_code == 404:
            return SourceResult(
                source="Gravatar", category="social", status=SourceStatus.not_found
            )

        data: dict = {"hash": digest}
        try:
            profile = await self._client.get(f"{profile_url}.json")
            if profile.status_code == 200 and "application/json" in profile.headers.get(
                "content-type", ""
            ):
                entries = profile.json().get("entry", [])
                if entries:
                    entry = entries[0]
                    data["display_name"] = entry.get("displayName")
                    data["accounts"] = [
                        a.get("url") for a in entry.get("accounts", []) if a.get("url")
                    ]
        except (httpx.HTTPError, ValueError):
            pass

        return SourceResult(
            source="Gravatar",
            category="social",
            status=SourceStatus.found,
            url=profile_url,
            data=data,
        )

    async def _hibp_check(self, email: str) -> SourceResult:
        if not self._settings.hibp_api_key:
            return SourceResult(
                source="HaveIBeenPwned",
                category="breach",
                status=SourceStatus.skipped,
                error="No HIBP_API_KEY configured.",
            )
        url = f"{_HIBP_BASE}/breachedaccount/{email}?truncateResponse=false"
        try:
            resp = await self._client.get(
                url, headers={"hibp-api-key": self._settings.hibp_api_key}
            )
        except httpx.HTTPError as exc:
            return SourceResult(
                source="HaveIBeenPwned",
                category="breach",
                status=SourceStatus.error,
                error=str(exc),
            )

        if resp.status_code == 404:
            return SourceResult(
                source="HaveIBeenPwned", category="breach", status=SourceStatus.not_found
            )
        if resp.status_code == 429:
            return SourceResult(
                source="HaveIBeenPwned", category="breach", status=SourceStatus.rate_limited
            )
        if resp.status_code != 200:
            return SourceResult(
                source="HaveIBeenPwned",
                category="breach",
                status=SourceStatus.error,
                error=f"Unexpected status {resp.status_code}",
            )

        breaches = resp.json()
        return SourceResult(
            source="HaveIBeenPwned",
            category="breach",
            status=SourceStatus.found,
            data={
                "breach_count": len(breaches),
                "breaches": [b.get("Name") for b in breaches],
            },
        )
