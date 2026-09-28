"""Persistence for alerts (SQLite) and recent stats (in memory).

Alerts must survive a restart so the on-call engineer can see what happened
overnight; the standard-library ``sqlite3`` module is enough for that and adds
no infrastructure. Stats points are cheap to regenerate and only needed for
the chart, so they live in a bounded in-memory ring.

Detection and delivery update different columns. :meth:`AlertStore.save_detection`
never touches ``acknowledged``, and only touches ``delivery`` when asked to
because a new delivery was just queued, so a routine detector update cannot
undo an operator's acknowledgement or an SNS message id recorded moments ago.

Schema changes are additive: a column added later (``explanation``, the
detector's reasoning as JSON) is created with ``ALTER TABLE`` on databases
that predate it, and rows without it load with an empty explanation.
"""

import json
import sqlite3
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app.models import (
    Alert,
    Delivery,
    Explanation,
    Severity,
    StatsPoint,
    TopContributors,
    from_iso,
    to_iso,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts (
    id               TEXT PRIMARY KEY,
    status           TEXT NOT NULL,
    severity         TEXT NOT NULL,
    score            REAL NOT NULL,
    error_rate       REAL NOT NULL,
    baseline_median  REAL NOT NULL,
    opened_at        TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    resolved_at      TEXT,
    summary          TEXT NOT NULL,
    top_contributors TEXT NOT NULL,
    sample_lines     TEXT NOT NULL,
    acknowledged     INTEGER NOT NULL DEFAULT 0,
    delivery         TEXT NOT NULL,
    explanation      TEXT
);
CREATE INDEX IF NOT EXISTS alerts_opened_at ON alerts (opened_at DESC);
"""

_DETECTION_COLUMNS = (
    "status",
    "severity",
    "score",
    "error_rate",
    "baseline_median",
    "opened_at",
    "updated_at",
    "resolved_at",
    "summary",
    "top_contributors",
    "sample_lines",
    "explanation",
)

# Columns added after the first release: name -> SQL type (always nullable).
_ADDED_COLUMNS = {"explanation": "TEXT"}


class AlertStore:
    """SQLite-backed alert history."""

    def __init__(self, path: Path | str) -> None:
        if isinstance(path, Path):
            path.parent.mkdir(parents=True, exist_ok=True)
        # Only the event-loop thread uses the connection; the flag just allows
        # it to be created in one thread and used in another.
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(_SCHEMA)
        self._migrate()

    def save_detection(self, alert: Alert, *, reset_delivery: bool = False) -> Alert:
        """Insert a new alert or update its detection fields; return the stored version.

        With ``reset_delivery`` the alert's delivery state replaces the stored one,
        so a newly queued delivery shows as pending instead of the last "sent".
        """
        row = _to_row(alert)
        columns = ", ".join(row)
        placeholders = ", ".join(f":{name}" for name in row)
        updated = (*_DETECTION_COLUMNS, "delivery") if reset_delivery else _DETECTION_COLUMNS
        updates = ", ".join(f"{name} = excluded.{name}" for name in updated)
        with self._db:
            self._db.execute(
                f"INSERT INTO alerts ({columns}) VALUES ({placeholders}) "
                f"ON CONFLICT(id) DO UPDATE SET {updates}",
                row,
            )
        stored = self.get(alert.id)
        assert stored is not None
        return stored

    def set_delivery(self, alert_id: str, delivery: Delivery) -> Alert | None:
        """Record AWS delivery state; return the updated alert, or None if unknown."""
        return self._update(alert_id, "delivery = ?", json.dumps(delivery.to_dict()))

    def acknowledge(self, alert_id: str) -> Alert | None:
        """Mark an alert as acknowledged; return it, or None if unknown."""
        return self._update(alert_id, "acknowledged = ?", 1)

    def get(self, alert_id: str) -> Alert | None:
        """Fetch one alert by id."""
        row = self._db.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
        return _from_row(row) if row else None

    def list_recent(self, limit: int = 50) -> list[Alert]:
        """Most recently opened alerts first."""
        rows = self._db.execute(
            "SELECT * FROM alerts ORDER BY opened_at DESC, rowid DESC LIMIT ?", (limit,)
        ).fetchall()
        return [_from_row(row) for row in rows]

    def close(self) -> None:
        """Close the database connection."""
        self._db.close()

    def _migrate(self) -> None:
        """Add columns that databases created by older versions are missing."""
        existing = {row["name"] for row in self._db.execute("PRAGMA table_info(alerts)")}
        with self._db:
            for name, sql_type in _ADDED_COLUMNS.items():
                if name not in existing:
                    self._db.execute(f"ALTER TABLE alerts ADD COLUMN {name} {sql_type}")

    def _update(self, alert_id: str, assignment: str, value: object) -> Alert | None:
        with self._db:
            cursor = self._db.execute(
                f"UPDATE alerts SET {assignment} WHERE id = ?", (value, alert_id)
            )
        return self.get(alert_id) if cursor.rowcount else None


class StatsHistory:
    """Bounded, time-ordered ring of recent stats points."""

    def __init__(self, max_points: int) -> None:
        self._points: deque[StatsPoint] = deque(maxlen=max_points)

    def append(self, point: StatsPoint) -> None:
        """Add the newest point, dropping the oldest when full."""
        self._points.append(point)

    def since(self, minutes: int) -> list[StatsPoint]:
        """Points from the last ``minutes`` minutes, measured back from the newest point."""
        if not self._points:
            return []
        cutoff: datetime = self._points[-1].ts - timedelta(minutes=minutes)
        return [p for p in self._points if p.ts > cutoff]


def _to_row(alert: Alert) -> dict[str, Any]:
    return {
        "id": alert.id,
        "status": alert.status,
        "severity": alert.severity.value,
        "score": alert.score,
        "error_rate": alert.error_rate,
        "baseline_median": alert.baseline_median,
        "opened_at": to_iso(alert.opened_at),
        "updated_at": to_iso(alert.updated_at),
        "resolved_at": to_iso(alert.resolved_at) if alert.resolved_at else None,
        "summary": alert.summary,
        "top_contributors": json.dumps(alert.top_contributors.to_dict()),
        "sample_lines": json.dumps(alert.sample_lines),
        "acknowledged": int(alert.acknowledged),
        "delivery": json.dumps(alert.delivery.to_dict()),
        "explanation": json.dumps(alert.explanation.to_dict()),
    }


def _from_row(row: sqlite3.Row) -> Alert:
    return Alert(
        id=row["id"],
        status=row["status"],
        severity=Severity(row["severity"]),
        score=row["score"],
        error_rate=row["error_rate"],
        baseline_median=row["baseline_median"],
        opened_at=from_iso(row["opened_at"]),
        updated_at=from_iso(row["updated_at"]),
        resolved_at=from_iso(row["resolved_at"]) if row["resolved_at"] else None,
        summary=row["summary"],
        top_contributors=TopContributors.from_dict(json.loads(row["top_contributors"])),
        sample_lines=json.loads(row["sample_lines"]),
        acknowledged=bool(row["acknowledged"]),
        delivery=Delivery.from_dict(json.loads(row["delivery"])),
        explanation=Explanation.from_dict(json.loads(row["explanation"] or "{}")),
    )
