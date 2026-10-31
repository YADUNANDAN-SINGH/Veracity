# GET /api/report/{id}: a finished call report (Step 4), as saved when the
# call ended. ?download=1 sends it as a file to attach on 1930 /
# cybercrime.gov.in / Chakshu.

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from app.feature import reports_db

router = APIRouter(prefix="/api/report", tags=["report"])


@router.get("/{report_id}")
def get_report(report_id: str, download: bool = False):
    report = reports_db.get_report(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="No report with that id.")
    headers = {"Content-Disposition": f'attachment; filename="veracity-report-{report_id[:8]}.json"'} if download else None
    return JSONResponse(report, headers=headers)
