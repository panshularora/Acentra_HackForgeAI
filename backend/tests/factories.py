"""Builders for test data."""

from datetime import UTC, datetime

from app.models import Alert, Contributor, LogEvent, Severity, TopContributors

T0 = datetime(2026, 9, 28, 13, 0, 0, tzinfo=UTC)


def make_event(
    level: str = "INFO",
    service: str = "eligibility-check",
    message: str = "eligibility verified",
    source_ip: str | None = None,
    http_status: int | None = None,
    raw: str | None = None,
    template_id: str | None = None,
    params: tuple[tuple[str, str], ...] = (),
    ts: datetime | None = None,
) -> LogEvent:
    """Build a LogEvent with sensible defaults for tests."""
    moment = ts or T0
    stamp = moment.strftime("%Y-%m-%dT%H:%M:%SZ")
    raw = raw or f'{stamp} {level} {service} msg="{message}"'
    return LogEvent(
        ts=moment,
        level=level,
        service=service,
        message=message,
        raw=raw,
        source_ip=source_ip,
        http_status=http_status,
        template_id=template_id,
        params=params,
    )


def make_alert(alert_id: str = "a1", **overrides: object) -> Alert:
    """Build an open CRITICAL alert; any field can be overridden."""
    fields: dict[str, object] = {
        "id": alert_id,
        "status": "open",
        "severity": Severity.CRITICAL,
        "score": 9.4,
        "error_rate": 0.31,
        "baseline_median": 0.02,
        "opened_at": T0,
        "updated_at": T0,
        "summary": "94% of errors come from claim-adjudication: DB connection timeout",
        "top_contributors": TopContributors(
            services=[Contributor("claim-adjudication", 212, 0.94)],
            messages=[Contributor("DB connection timeout", 200, 0.89)],
        ),
        "sample_lines": ["2026-09-28T13:00:00Z ERROR claim-adjudication member_id=<MEMBER_ID>"],
    }
    fields.update(overrides)
    return Alert(**fields)  # type: ignore[arg-type]
