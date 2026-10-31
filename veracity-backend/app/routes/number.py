# POST /api/number/check: the lookup behind Step 2 (Check number) on the frontend.
# POST /api/number/report: Step 4's "Add to community reports".

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.feature import reports_db
from app.feature.number_intelligence import InvalidNumberError, analyse_number, get_number_details

router = APIRouter(prefix="/api/number", tags=["number"])

# Same ids as SCAM_TYPES in veracity-frontend/veracity/src/api/report.js
ScamType = Literal[
    "digital_arrest", "bank_kyc", "family_emergency", "parcel_courier",
    "investment", "lottery_prize", "tech_support", "other",
]


class NumberCheckRequest(BaseModel):
    number: str = Field(..., min_length=1, max_length=32, examples=["+91 98765 43210"])
    # Used only when the number has no +country code
    region: str = Field("IN", min_length=2, max_length=2, examples=["IN"])


class NumberCheckResponse(BaseModel):
    valid: bool
    number_type: str
    country: str | None
    location: str | None
    original_carrier: str | None
    is_international: bool
    e164_format: str
    national_digits: str
    timezones: list[str]
    # e.g. "mobile", "international", "1600_regulated"
    series: str
    community_reports: int
    reports_7d: int
    # 0–100, with one reason per signal that added points
    rule_score: int
    rule_reasons: list[str]


class CommunityReportRequest(BaseModel):
    number: str = Field(..., min_length=1, max_length=32, examples=["+91 98765 43210"])
    category: ScamType
    note: str | None = Field(None, max_length=500)
    region: str = Field("IN", min_length=2, max_length=2)


class CommunityReportResponse(BaseModel):
    id: int
    e164: str
    category: ScamType
    reported_at: str
    # Totals for the number after this report, for "reported N times"
    community_reports: int
    reports_7d: int


@router.post("/check", response_model=NumberCheckResponse)
def check_number(body: NumberCheckRequest):
    try:
        return analyse_number(body.number, body.region)
    except InvalidNumberError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/report", response_model=CommunityReportResponse, status_code=201)
def report_number(body: CommunityReportRequest):
    try:
        # Invalid but parseable numbers are kept too: spoofed numbers often are
        e164 = get_number_details(body.number, body.region)["e164_format"]
    except InvalidNumberError as e:
        raise HTTPException(status_code=422, detail=str(e))
    note = body.note.strip() if body.note else None
    saved = reports_db.add_community_report(e164, body.category, note)
    reports, reports_7d = reports_db.community_counts(e164)
    return {**saved, "community_reports": reports, "reports_7d": reports_7d}
