# SQLite storage for the payment gate, in the same file as the reports (VERA_DB):
#   payments        one row per Protected Send: PayPal ids, amount, status, why it's held
#   payment_events  the audit trail: every PayPal call, every webhook, every decision
#   webhook_events  ids of webhooks already handled (PayPal retries deliveries)

import json
import sqlite3
from contextlib import closing

from app.feature.reports_db import _connect as _connect_reports
from app.feature.reports_db import utc_now

_SCHEMA = """
CREATE TABLE IF NOT EXISTS payments (
    payment_id        TEXT PRIMARY KEY,
    session_id        TEXT,
    order_id          TEXT UNIQUE,
    authorization_id  TEXT UNIQUE,
    capture_id        TEXT,
    payout_batch_id   TEXT,
    amount            TEXT NOT NULL,
    currency          TEXT NOT NULL,
    recipient_name    TEXT NOT NULL,
    recipient_email   TEXT,
    contact_name      TEXT,
    contact_number    TEXT,
    note              TEXT,
    status            TEXT NOT NULL,
    hold_reason       TEXT,
    risk_json         TEXT,
    verification      TEXT,
    release_at        TEXT,
    expires_at        TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS payments_session ON payments (session_id);

CREATE TABLE IF NOT EXISTS payment_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    payment_id  TEXT NOT NULL,
    at          TEXT NOT NULL,
    source      TEXT NOT NULL,
    kind        TEXT NOT NULL,
    detail      TEXT
);
CREATE INDEX IF NOT EXISTS payment_events_payment ON payment_events (payment_id, id);

CREATE TABLE IF NOT EXISTS webhook_events (
    event_id     TEXT PRIMARY KEY,
    event_type   TEXT NOT NULL,
    received_at  TEXT NOT NULL
);
"""

_FIELDS = {
    "session_id", "order_id", "authorization_id", "capture_id", "payout_batch_id", "status", "hold_reason",
    "risk_json", "verification", "release_at", "expires_at",
}


def _connect() -> sqlite3.Connection:
    conn = _connect_reports()
    conn.executescript(_SCHEMA)
    return conn


def create_payment(row: dict) -> dict:
    now = utc_now()
    row = {**row, "created_at": now, "updated_at": now}
    columns = ", ".join(row)
    with closing(_connect()) as conn, conn:
        conn.execute(f"INSERT INTO payments ({columns}) VALUES ({', '.join('?' * len(row))})", tuple(row.values()))
    return get_payment(row["payment_id"])


def get_payment(payment_id: str) -> dict | None:
    return _one("SELECT * FROM payments WHERE payment_id = ?", payment_id)


def find_by_order(order_id: str) -> dict | None:
    return _one("SELECT * FROM payments WHERE order_id = ?", order_id)


def find_by_authorization(authorization_id: str) -> dict | None:
    return _one("SELECT * FROM payments WHERE authorization_id = ?", authorization_id)


def find_by_payout(batch_id: str) -> dict | None:
    return _one("SELECT * FROM payments WHERE payout_batch_id = ?", batch_id)


def list_payments(session_id: str | None = None) -> list[dict]:
    with closing(_connect()) as conn:
        if session_id:
            rows = conn.execute("SELECT * FROM payments WHERE session_id = ? ORDER BY created_at", (session_id,))
        else:
            rows = conn.execute("SELECT * FROM payments ORDER BY created_at DESC LIMIT 50")
        return [dict(r) for r in rows.fetchall()]


def update_payment(payment_id: str, **fields) -> dict:
    unknown = set(fields) - _FIELDS
    if unknown:
        raise ValueError(f"Unknown payment fields: {sorted(unknown)}")
    fields["updated_at"] = utc_now()
    sets = ", ".join(f"{k} = ?" for k in fields)
    with closing(_connect()) as conn, conn:
        conn.execute(f"UPDATE payments SET {sets} WHERE payment_id = ?", (*fields.values(), payment_id))
    return get_payment(payment_id)


def add_event(payment_id: str, source: str, kind: str, detail: dict | None = None) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(
            "INSERT INTO payment_events (payment_id, at, source, kind, detail) VALUES (?, ?, ?, ?, ?)",
            (payment_id, utc_now(), source, kind, json.dumps(detail) if detail else None),
        )


def list_events(payment_id: str) -> list[dict]:
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT at, source, kind, detail FROM payment_events WHERE payment_id = ? ORDER BY id", (payment_id,)
        ).fetchall()
    return [{**dict(r), "detail": json.loads(r["detail"]) if r["detail"] else None} for r in rows]


def mark_webhook_seen(event_id: str, event_type: str) -> bool:
    """True the first time an event id is seen; False for PayPal's retries."""
    with closing(_connect()) as conn, conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO webhook_events (event_id, event_type, received_at) VALUES (?, ?, ?)",
            (event_id, event_type, utc_now()),
        )
    return cur.rowcount == 1


def _one(sql: str, *params) -> dict | None:
    with closing(_connect()) as conn:
        row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None
