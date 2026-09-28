"""Send one test alert through the configured SNS topic and print the outcome.

Uses the application's own settings (environment or .env) and publisher, so a
pass here means the running service will be able to publish too::

    make sns-check
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.alerts.publisher import AlertPublisher
from app.config import get_settings
from app.detection.detector import AlertChange, AlertEvent
from app.models import Alert, Contributor, Severity, TopContributors


def test_alert() -> Alert:
    """A clearly labelled synthetic alert."""
    now = datetime.now(UTC)
    return Alert(
        id="sns-check",
        status="open",
        severity=Severity.WARNING,
        score=4.2,
        error_rate=0.12,
        baseline_median=0.02,
        opened_at=now,
        updated_at=now,
        summary="TEST ALERT: SNS delivery check",
        top_contributors=TopContributors(services=[Contributor("sns-check", 1, 1.0)]),
        sample_lines=[],
    )


def main() -> int:
    """Entry point: exit 0 when SNS accepted the message."""
    publisher = AlertPublisher(get_settings())
    publisher.ensure_resources()
    delivery = publisher.deliver(AlertEvent(AlertChange.OPENED, test_alert()))
    print(f"topic:      {publisher.topic_arn}")
    sns = delivery.sns
    print(f"sns:        {sns.status} {sns.message_id or sns.error or ''}")
    print(f"cloudwatch: {delivery.cloudwatch.status} {delivery.cloudwatch.error or ''}")
    return 0 if delivery.sns.status == "sent" else 1


if __name__ == "__main__":
    raise SystemExit(main())
