# POST /api/number/check: the lookup behind Step 2 (Check number) on the frontend.

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.feature.number_intelligence import InvalidNumberError, get_number_details

router = APIRouter(prefix="/api/number", tags=["number"])


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


@router.post("/check", response_model=NumberCheckResponse)
def check_number(body: NumberCheckRequest):
    try:
        return get_number_details(body.number, body.region)
    except InvalidNumberError as e:
        raise HTTPException(status_code=422, detail=str(e))
