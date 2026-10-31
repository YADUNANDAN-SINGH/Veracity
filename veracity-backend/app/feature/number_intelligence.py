# The core feature of the this file is to get basic infromation about the number like geo location and other public data awalable for the number.

import math

import phonenumbers as pn
from phonenumbers import geocoder, carrier, timezone

from app.feature import reports_db

''' 
<------ For Testing ------->

NB = input("please Enter your number: ")

parsed_nb = pn.parse(NB, "IN")

if pn.is_valid_number(parsed_nb):
    print("Valid number")
else:
    print("Invalid number")

print("Here is it's e164 format: ", pn.format_number(parsed_nb, pn.PhoneNumberFormat.E164))

'''

''' 
def get_number_details(raw: str, default_region: str = "IN"):
    n = pn.parse(raw, default_region)
    
    return {
        "valid": pn.is_valid_number(n),
        "number_type": pn.number_type(n),
        "country": geocoder.country_name_for_number(n, "en"),
        "original_carrier": carrier.name_for_number(n, "en"),
        "is_international": n.country_code != 91,
        "e164_format": pn.format_number(n, pn.PhoneNumberFormat.E164),
        "national_digits": str(n.national_number)
    }
'''

# <------- Real Implementation --------->

class InvalidNumberError(ValueError):
    """Raised when the input can't be read as a phone number at all."""


def get_number_details(raw: str, default_region: str = "IN"):
    default_region = default_region.upper()

    try:
        n = pn.parse(raw, default_region)
    except pn.NumberParseException as e:
        raise InvalidNumberError("That doesn't look like a phone number.") from e

    return {
        "valid": pn.is_valid_number(n),
        # e.g. "MOBILE", "FIXED_LINE", "VOIP" (pn.number_type() alone is just an int)
        "number_type": pn.PhoneNumberType.to_string(pn.number_type(n)),
        "country": geocoder.country_name_for_number(n, "en") or None,
        # Finer than country: for Indian mobiles this is usually the telecom circle / state
        "location": geocoder.description_for_number(n, "en") or None,
        # Carrier the number was first issued to; ported numbers may have moved since
        "original_carrier": carrier.name_for_number(n, "en") or None,
        "is_international": n.country_code != pn.country_code_for_region(default_region),
        "e164_format": pn.format_number(n, pn.PhoneNumberFormat.E164),
        "national_digits": str(n.national_number),
        # phonenumbers returns ["Etc/Unknown"] when it can't tell
        "timezones": [tz for tz in timezone.time_zones_for_number(n) if tz != "Etc/Unknown"],
    }


# <------- Rule score (Project Document §1.4) --------->

# Library types that map straight to a series; everything else is "other"
_SERIES_BY_TYPE = {
    "MOBILE": "mobile",
    "FIXED_LINE_OR_MOBILE": "mobile",
    "FIXED_LINE": "fixed_line",
    "TOLL_FREE": "toll_free",
}


def number_series(details: dict) -> str:
    """The India-specific series, e.g. "1600_regulated" (phonenumbers calls 1600… MOBILE)."""
    digits = details["national_digits"]
    if not details["valid"]:
        return "invalid"
    if details["is_international"]:
        return "international"
    if len(digits) == 10 and digits.startswith("1600"):
        return "1600_regulated"
    if digits.startswith("140"):
        return "140_telemarketing"
    return _SERIES_BY_TYPE.get(details["number_type"], "other")


def rule_score(series: str, reports: int, reports_7d: int) -> tuple[int, list[str]]:
    """Transparent 0–100 score, with one reason per signal that added points."""
    points: list[tuple[int, str]] = []
    if series == "invalid":
        points.append((40, "Not a valid number"))
    if series == "international":
        points.append((25, "International number"))
    if reports:
        times = "once" if reports == 1 else f"{reports} times"
        points.append((min(30, round(10 * math.log2(1 + reports))), f"Reported {times} by the community"))
    if reports_7d:
        points.append((10, "Reported in the last 7 days"))
    if series == "140_telemarketing":
        points.append((5, "140 telemarketing series"))
    if series == "1600_regulated":
        points.append((-20, "1600 series, used only by regulated banks and agencies"))

    score = max(0, min(100, sum(p for p, _ in points)))
    reasons = [f"{reason} ({'+' if p > 0 else '−'}{abs(p)})" for p, reason in points]
    return score, reasons


def analyse_number(raw: str, default_region: str = "IN") -> dict:
    """get_number_details plus the series, community reports and rule score."""
    details = get_number_details(raw, default_region)
    series = number_series(details)
    reports, reports_7d = reports_db.community_counts(details["e164_format"])
    score, reasons = rule_score(series, reports, reports_7d)
    return {
        **details,
        "series": series,
        "community_reports": reports,
        "reports_7d": reports_7d,
        "rule_score": score,
        "rule_reasons": reasons,
    }
