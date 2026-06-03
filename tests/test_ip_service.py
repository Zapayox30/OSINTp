"""Tests for IP parsing and private-address handling (no network)."""

from __future__ import annotations

import httpx
import pytest

from app.schemas.ip import IPQuery
from app.services.ip_service import IPService


def test_parse_ipv4():
    assert str(IPService.parse_ip("8.8.8.8")) == "8.8.8.8"


def test_parse_ipv6():
    assert IPService.parse_ip("2001:4860:4860::8888").version == 6


def test_parse_invalid():
    with pytest.raises(ValueError):
        IPService.parse_ip("999.1.1.1")


async def test_private_ip_skips_network():
    async with httpx.AsyncClient() as client:
        service = IPService(client)
        result = await service.investigate(IPQuery(ip="192.168.1.1"))
    assert result.summary["is_private"] is True
    assert result.summary["is_global"] is False
    assert any(r.source == "Classification" for r in result.results)
