"""SQLite storage: call sessions, facility alerts and an audit log.

Sessions hold the caller's number only until the call ends (or an hour passes).
Alerts keep the minimum a clinic needs: group, reported signs, urgency.
"""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    caller TEXT NOT NULL DEFAULT '',
    stage TEXT NOT NULL DEFAULT 'lang',
    lang TEXT,
    consent INTEGER NOT NULL DEFAULT 0,
    node TEXT,
    trail TEXT NOT NULL DEFAULT '[]',
    outcome TEXT,
    retries INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    facility_id TEXT NOT NULL,
    region TEXT NOT NULL,
    lang TEXT NOT NULL,
    level TEXT NOT NULL,
    group_label TEXT NOT NULL,
    reported TEXT NOT NULL,
    caller_ref TEXT NOT NULL,
    caller_number TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new',
    ack_by TEXT,
    ack_at REAL,
    sms_status TEXT
);
CREATE INDEX IF NOT EXISTS alerts_ref ON alerts(caller_ref, created_at);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at REAL NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    alert_id INTEGER
);
"""

SESSION_FIELDS = {"caller", "stage", "lang", "consent", "node", "trail", "outcome", "retries"}


class Store:
    def __init__(self, path):
        self.path = str(path)
        with closing(self._connect()) as conn, conn:
            conn.executescript(SCHEMA)

    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    # ---- sessions ---------------------------------------------------------
    def create_session(self, session_id, caller=""):
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT OR REPLACE INTO sessions (session_id, caller, stage, trail, retries, consent, updated_at)"
                " VALUES (?, ?, 'lang', '[]', 0, 0, ?)",
                (session_id, caller, time.time()),
            )

    def get_session(self, session_id):
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
        return dict(row) if row else None

    def update_session(self, session_id, **fields):
        unknown = set(fields) - SESSION_FIELDS
        if unknown:
            raise ValueError(f"unknown session fields: {sorted(unknown)}")
        columns = ", ".join(f"{name} = ?" for name in fields)
        with closing(self._connect()) as conn, conn:
            conn.execute(
                f"UPDATE sessions SET {columns}, updated_at = ? WHERE session_id = ?",
                (*fields.values(), time.time(), session_id),
            )

    def delete_session(self, session_id):
        with closing(self._connect()) as conn, conn:
            conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))

    def purge_sessions(self, max_age_seconds):
        with closing(self._connect()) as conn, conn:
            conn.execute("DELETE FROM sessions WHERE updated_at < ?", (time.time() - max_age_seconds,))

    def session_count(self):
        with closing(self._connect()) as conn:
            return conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]

    # ---- alerts -----------------------------------------------------------
    def add_alert(self, **fields):
        fields["created_at"] = time.time()
        names = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        with closing(self._connect()) as conn, conn:
            cur = conn.execute(f"INSERT INTO alerts ({names}) VALUES ({marks})", tuple(fields.values()))
            return cur.lastrowid

    def recent_alert_count(self, caller_ref, since):
        with closing(self._connect()) as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM alerts WHERE caller_ref = ? AND created_at >= ?", (caller_ref, since)
            ).fetchone()[0]

    def list_alerts(self, scope="*", include_acked=False, limit=500):
        query, params = "SELECT * FROM alerts WHERE 1 = 1", []
        if scope != "*":
            query += " AND facility_id = ?"
            params.append(scope)
        if not include_acked:
            query += " AND status = 'new'"
        query += " ORDER BY created_at ASC LIMIT ?"
        params.append(limit)
        with closing(self._connect()) as conn:
            return [dict(r) for r in conn.execute(query, params).fetchall()]

    def get_alert(self, alert_id):
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
        return dict(row) if row else None

    def ack_alert(self, alert_id, by):
        with closing(self._connect()) as conn, conn:
            cur = conn.execute(
                "UPDATE alerts SET status = 'acknowledged', ack_by = ?, ack_at = ? WHERE id = ? AND status = 'new'",
                (by, time.time(), alert_id),
            )
            return cur.rowcount > 0

    def set_sms_status(self, alert_id, status):
        with closing(self._connect()) as conn, conn:
            conn.execute("UPDATE alerts SET sms_status = ? WHERE id = ?", (status, alert_id))

    # ---- audit ------------------------------------------------------------
    def log_audit(self, actor, action, alert_id=None):
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT INTO audit (at, actor, action, alert_id) VALUES (?, ?, ?, ?)",
                (time.time(), actor, action, alert_id),
            )

    def audit_log(self, limit=100):
        with closing(self._connect()) as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,))]


def loads(value, default=None):
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default
