# SQLite storage (Python standard library, nothing to install or run):
#   community_reports  numbers people reported after a call (POST /api/number/report);
#                      their counts feed the number's rule score
#   call_reports       every finished JSON report, so GET /api/report/{id} can return it
#
# The file is app/data/veracity.db; VERA_DB points it elsewhere (the tests use a temp file).

import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

_DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "veracity.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS community_reports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    e164        TEXT NOT NULL,
    category    TEXT NOT NULL,
    note        TEXT,
    reported_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS community_reports_e164 ON community_reports (e164, reported_at);

CREATE TABLE IF NOT EXISTS call_reports (
    report_id    TEXT PRIMARY KEY,
    generated_at TEXT NOT NULL,
    caller_e164  TEXT,
    report_json  TEXT NOT NULL
);
"""


def utc_now() -> str:
    """UTC timestamp like "2026-10-31T12:10:00Z" (sorts as text, so SQL can compare it)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _connect() -> sqlite3.Connection:
    # Read the path on every call so tests can set VERA_DB after import
    path = Path(os.environ.get("VERA_DB", _DEFAULT_DB))
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def add_community_report(e164: str, category: str, note: str | None) -> dict:
    reported_at = utc_now()
    with closing(_connect()) as conn, conn:
        cur = conn.execute(
            "INSERT INTO community_reports (e164, category, note, reported_at) VALUES (?, ?, ?, ?)",
            (e164, category, note or None, reported_at),
        )
    return {"id": cur.lastrowid, "e164": e164, "category": category, "note": note or None, "reported_at": reported_at}


def community_counts(e164: str) -> tuple[int, int]:
    """(all reports, reports in the last 7 days) for one number."""
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(reported_at >= ?), 0) FROM community_reports WHERE e164 = ?",
            (week_ago, e164),
        ).fetchone()
    return row[0], row[1]


def save_report(report: dict) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(
            "INSERT OR REPLACE INTO call_reports (report_id, generated_at, caller_e164, report_json) VALUES (?, ?, ?, ?)",
            (
                report["report_id"],
                report["generated_at"],
                (report.get("number") or {}).get("e164"),
                json.dumps(report),
            ),
        )


def get_report(report_id: str) -> dict | None:
    with closing(_connect()) as conn:
        row = conn.execute("SELECT report_json FROM call_reports WHERE report_id = ?", (report_id,)).fetchone()
    return json.loads(row["report_json"]) if row else None
