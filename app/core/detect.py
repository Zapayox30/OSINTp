"""Target-type detection shared across the API and the correlation engine."""

from __future__ import annotations

import ipaddress
import re

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def detect_type(target: str) -> str:
    """Best-effort classification of a raw target into a module type.

    Returns one of ``"ip"``, ``"email"``, ``"domain"`` or ``"username"``.
    """
    candidate = target.strip()
    try:
        ipaddress.ip_address(candidate)
        return "ip"
    except ValueError:
        pass
    if _EMAIL_RE.match(candidate):
        return "email"
    if "." in candidate and " " not in candidate:
        return "domain"
    return "username"
