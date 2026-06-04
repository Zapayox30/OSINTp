"""Tests for the phone module (offline via phonenumbers) and detection."""

from __future__ import annotations

from app.core.detect import detect_type
from app.schemas.common import SourceStatus
from app.schemas.phone import PhoneQuery
from app.services.phone_service import PhoneService


async def test_valid_us_number():
    result = await PhoneService().investigate(PhoneQuery(phone="+12025550143"))
    assert result.summary["valid"] is True
    assert result.summary["region"] == "US"
    validation = next(r for r in result.results if r.source == "Validation")
    assert validation.status == SourceStatus.found
    assert validation.data["e164"] == "+12025550143"


async def test_unparseable_number_errors():
    # A long-but-nonsense string parses to an error envelope (no country code).
    result = await PhoneService().investigate(PhoneQuery(phone="abcdefg"))
    assert result.results[0].status == SourceStatus.error


async def test_phone_detection():
    assert detect_type("+12025550143") == "phone"
    assert detect_type("+44 20 7946 0958") == "phone"
    assert detect_type("torvalds") == "username"
