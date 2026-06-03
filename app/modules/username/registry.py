"""Site registry for username enumeration.

Sites are described declaratively in ``sites.json`` and validated into typed
:class:`Site` models. Two detection strategies are supported:

* ``status``  — the username exists when the probe returns one of
  ``claimed_codes`` and is absent for ``not_found_codes``.
* ``message`` — the response body is inspected for marker strings. Either
  ``found_messages`` (presence ⇒ exists) or ``error_messages``
  (presence ⇒ absent) drive the decision.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

_SITES_FILE = Path(__file__).with_name("sites.json")


class Site(BaseModel):
    """Declarative description of a checkable site."""

    name: str
    category: str = "other"
    url: str = Field(..., description="Public profile URL template containing '{}'.")
    url_probe: str | None = Field(
        default=None,
        description="Optional alternative URL to request (e.g. a JSON API endpoint).",
    )
    check: Literal["status", "message"] = "status"
    claimed_codes: list[int] = Field(default_factory=lambda: [200])
    not_found_codes: list[int] = Field(default_factory=lambda: [404])
    found_messages: list[str] = Field(default_factory=list)
    error_messages: list[str] = Field(default_factory=list)
    headers: dict[str, str] = Field(default_factory=dict)

    def profile_url(self, username: str) -> str:
        return self.url.format(username)

    def probe_url(self, username: str) -> str:
        return (self.url_probe or self.url).format(username)


@lru_cache
def load_sites() -> tuple[Site, ...]:
    """Load and validate the site registry (cached)."""
    raw = json.loads(_SITES_FILE.read_text(encoding="utf-8"))
    return tuple(Site.model_validate(entry) for entry in raw)


def filter_sites(categories: list[str] | None) -> tuple[Site, ...]:
    """Return registry sites, optionally restricted to *categories*."""
    sites = load_sites()
    if not categories:
        return sites
    wanted = {c.lower() for c in categories}
    return tuple(s for s in sites if s.category.lower() in wanted)


def available_categories() -> list[str]:
    """Return the sorted set of categories present in the registry."""
    return sorted({s.category for s in load_sites()})
