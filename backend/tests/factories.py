"""Builders for test data."""

from datetime import UTC, datetime

from app.models import LogEvent

T0 = datetime(2026, 9, 28, 13, 0, 0, tzinfo=UTC)


def make_event(
    level: str = "INFO",
    service: str = "eligibility-check",
    message: str = "eligibility verified",
    source_ip: str | None = None,
    http_status: int | None = None,
) -> LogEvent:
    """Build a LogEvent with sensible defaults for tests."""
    raw = f"2026-09-28T13:00:00Z {level} {service} msg=\"{message}\""
    return LogEvent(
        ts=T0,
        level=level,
        service=service,
        message=message,
        raw=raw,
        source_ip=source_ip,
        http_status=http_status,
    )
