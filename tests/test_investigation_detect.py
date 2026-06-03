"""Tests for target-type auto-detection and domain normalisation."""

from __future__ import annotations

import pytest

from app.api.v1.endpoints.investigation import detect_type
from app.services.domain_service import DomainService


@pytest.mark.parametrize(
    "target,expected",
    [
        ("8.8.8.8", "ip"),
        ("2001:4860:4860::8888", "ip"),
        ("alice@example.com", "email"),
        ("example.com", "domain"),
        ("sub.example.co.uk", "domain"),
        ("torvalds", "username"),
    ],
)
def test_detect_type(target, expected):
    assert detect_type(target) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("https://www.Example.com/path", "example.com"),
        ("EXAMPLE.COM", "example.com"),
        ("example.com:443", "example.com"),
    ],
)
def test_normalize_domain(raw, expected):
    assert DomainService.normalize_domain(raw) == expected


def test_normalize_domain_invalid():
    with pytest.raises(ValueError):
        DomainService.normalize_domain("not a domain!!")
