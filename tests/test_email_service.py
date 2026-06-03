"""Tests for email syntax validation (no network)."""

from __future__ import annotations

from app.schemas.common import SourceStatus
from app.services.email_service import EmailService


def test_syntax_valid():
    result = EmailService._syntax_check("user@example.com")
    assert result.status == SourceStatus.found
    assert result.data["domain"] == "example.com"


def test_syntax_invalid():
    result = EmailService._syntax_check("definitely-not-an-email")
    assert result.status == SourceStatus.error
    assert result.error
