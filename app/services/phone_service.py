"""Phone-number intelligence (offline, via libphonenumber / phonenumbers).

No network is used: validation, region, carrier, line type and timezone all
come from the bundled libphonenumber metadata.
"""

from __future__ import annotations

import phonenumbers
from phonenumbers import (
    NumberParseException,
    PhoneNumberFormat,
    PhoneNumberType,
    carrier,
    geocoder,
    timezone,
)

from app.core.logging import get_logger
from app.schemas.common import SourceResult, SourceStatus
from app.schemas.phone import PhoneQuery, PhoneResult

logger = get_logger(__name__)

_LINE_TYPES = {
    PhoneNumberType.FIXED_LINE: "fixed_line",
    PhoneNumberType.MOBILE: "mobile",
    PhoneNumberType.FIXED_LINE_OR_MOBILE: "fixed_line_or_mobile",
    PhoneNumberType.TOLL_FREE: "toll_free",
    PhoneNumberType.PREMIUM_RATE: "premium_rate",
    PhoneNumberType.SHARED_COST: "shared_cost",
    PhoneNumberType.VOIP: "voip",
    PhoneNumberType.PERSONAL_NUMBER: "personal_number",
    PhoneNumberType.PAGER: "pager",
    PhoneNumberType.UAN: "uan",
    PhoneNumberType.VOICEMAIL: "voicemail",
    PhoneNumberType.UNKNOWN: "unknown",
}


class PhoneService:
    def __init__(self, client=None) -> None:  # client kept for a uniform service API
        self._client = client

    async def investigate(self, query: PhoneQuery) -> PhoneResult:
        raw = query.phone.strip()
        try:
            num = phonenumbers.parse(raw, query.region)
        except NumberParseException as exc:
            return PhoneResult(
                target=raw,
                module="phone",
                summary={"valid": False, "error": str(exc)},
                results=[
                    SourceResult(
                        source="Validation",
                        category="validation",
                        status=SourceStatus.error,
                        error=str(exc),
                    )
                ],
            )

        valid = phonenumbers.is_valid_number(num)
        line_type = _LINE_TYPES.get(phonenumbers.number_type(num), "unknown")
        e164 = phonenumbers.format_number(num, PhoneNumberFormat.E164)
        region = phonenumbers.region_code_for_number(num)
        car = carrier.name_for_number(num, "en")
        loc = geocoder.description_for_number(num, "en")
        tzs = list(timezone.time_zones_for_number(num))

        results = [
            SourceResult(
                source="Validation",
                category="validation",
                status=SourceStatus.found if valid else SourceStatus.not_found,
                data={
                    "valid": valid,
                    "possible": phonenumbers.is_possible_number(num),
                    "e164": e164,
                    "international": phonenumbers.format_number(
                        num, PhoneNumberFormat.INTERNATIONAL
                    ),
                    "national": phonenumbers.format_number(num, PhoneNumberFormat.NATIONAL),
                    "country_code": num.country_code,
                    "region": region,
                    "line_type": line_type,
                },
            ),
            SourceResult(
                source="Carrier",
                category="carrier",
                status=SourceStatus.found if car else SourceStatus.not_found,
                data={"carrier": car} if car else {},
            ),
            SourceResult(
                source="Location",
                category="geo",
                status=SourceStatus.found if loc else SourceStatus.not_found,
                data={"location": loc, "region": region} if loc else {},
            ),
            SourceResult(
                source="Timezone",
                category="geo",
                status=SourceStatus.found if tzs else SourceStatus.not_found,
                data={"timezones": tzs},
            ),
        ]

        return PhoneResult(
            target=e164 if valid else raw,
            module="phone",
            summary={
                "valid": valid,
                "e164": e164,
                "region": region,
                "line_type": line_type,
                "carrier": car or None,
            },
            results=results,
        )
