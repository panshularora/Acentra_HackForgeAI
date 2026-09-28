import asyncio
import json
import re
from collections.abc import Iterator
from typing import Any

import boto3
import pytest
from moto import mock_aws

from app.alerts.publisher import AlertPublisher, email_text, sns_subject
from app.config import Settings
from app.detection.detector import AlertChange, AlertEvent
from app.ingest.parser import LogParser
from app.models import Alert, Delivery, Severity
from tests.aws import receive_envelopes, subscribe_queue
from tests.factories import make_alert

RAW_PHI_LINE = (
    '2026-09-28T13:05:03Z ERROR claim-adjudication msg="DB connection timeout" '
    'member_id=M1234567 name="Rosa Diaz" email=rosa@example.com ssn=123-45-6789'
)
PHI_PATTERNS = [r"M\d{7}", "Rosa Diaz", "rosa@example.com", r"\d{3}-\d{2}-\d{4}"]


@pytest.fixture(autouse=True)
def fake_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(key, "testing")


@pytest.fixture
def aws() -> Iterator[None]:
    with mock_aws():
        yield


def settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {"aws_endpoint_url": None, "aws_region": "us-east-1", **overrides}
    return Settings(**values)


def opened(alert: Alert) -> AlertEvent:
    return AlertEvent(AlertChange.OPENED, alert)


def critical_alert_from_real_line() -> Alert:
    event = LogParser().parse(RAW_PHI_LINE)
    assert event is not None
    return make_alert("crit01", severity=Severity.CRITICAL, sample_lines=[event.raw])


def test_ensure_resources_is_idempotent(aws: None) -> None:
    publisher = AlertPublisher(settings())
    publisher.ensure_resources()
    first_arn = publisher.topic_arn
    publisher.ensure_resources()

    assert first_arn is not None and first_arn.endswith(":claimswatch-alerts")
    assert publisher.topic_arn == first_arn


def test_critical_alert_is_readable_from_subscribed_queue_and_masked(aws: None) -> None:
    publisher = AlertPublisher(settings())
    publisher.ensure_resources()
    assert publisher.topic_arn is not None
    queue_url = subscribe_queue(publisher.topic_arn)

    delivery = publisher.deliver(opened(critical_alert_from_real_line()))

    messages = boto3.client("sqs", region_name="us-east-1").receive_message(
        QueueUrl=queue_url, MaxNumberOfMessages=1
    )["Messages"]
    envelope = json.loads(messages[0]["Body"])
    alert = json.loads(envelope["Message"])
    assert delivery.sns.status == "sent"
    assert envelope["MessageId"] == delivery.sns.message_id
    assert envelope["Subject"].startswith("[CRITICAL] ClaimsWatch: ")
    assert envelope["MessageAttributes"]["event"]["Value"] == "opened"
    assert envelope["MessageAttributes"]["severity"]["Value"] == "CRITICAL"
    assert alert["event"] == "opened"
    assert alert["id"] == "crit01"
    assert alert["severity"] == "CRITICAL"
    assert "member_id=<MEMBER_ID>" in alert["sample_lines"][0]
    for pattern in PHI_PATTERNS:
        assert not re.search(pattern, envelope["Message"]), pattern


def test_alert_is_written_to_cloudwatch_logs(aws: None) -> None:
    publisher = AlertPublisher(settings(cw_log_group="/test/alerts", cw_log_stream="s1"))
    publisher.ensure_resources()

    delivery = publisher.deliver(opened(critical_alert_from_real_line()))

    events = boto3.client("logs", region_name="us-east-1").get_log_events(
        logGroupName="/test/alerts", logStreamName="s1"
    )["events"]
    assert delivery.cloudwatch.status == "sent"
    assert len(events) == 1
    logged = json.loads(events[0]["message"])
    assert logged["id"] == "crit01"
    assert "<MEMBER_ID>" in logged["sample_lines"][0]


def test_resources_are_created_lazily_if_startup_missed_them(aws: None) -> None:
    publisher = AlertPublisher(settings())

    delivery = publisher.deliver(opened(make_alert()))

    assert delivery.sns.status == "sent"
    assert delivery.cloudwatch.status == "sent"


def test_unreachable_aws_marks_both_channels_failed_without_raising() -> None:
    publisher = AlertPublisher(settings(aws_endpoint_url="http://127.0.0.1:9"))
    publisher.ensure_resources()

    delivery = publisher.deliver(opened(make_alert()))

    assert publisher.topic_arn is None
    assert delivery.sns.status == "failed" and delivery.sns.error
    assert delivery.cloudwatch.status == "failed" and delivery.cloudwatch.error


async def test_worker_delivers_in_background_and_reports_back(aws: None) -> None:
    received: list[tuple[str, Delivery]] = []

    async def record(alert_id: str, delivery: Delivery) -> None:
        received.append((alert_id, delivery))

    publisher = AlertPublisher(settings(), on_delivery=record)
    await publisher.start()
    publisher.submit(opened(make_alert("bg1")))
    await asyncio.wait_for(publisher.drain(), timeout=10)
    await publisher.stop()

    assert [alert_id for alert_id, _ in received] == ["bg1"]
    assert received[0][1].sns.status == "sent"
    assert received[0][1].sns.message_id


async def test_outcome_superseded_by_a_newer_transition_is_not_reported(aws: None) -> None:
    received: list[tuple[str, Delivery]] = []

    async def record(alert_id: str, delivery: Delivery) -> None:
        received.append((alert_id, delivery))

    publisher = AlertPublisher(settings(), on_delivery=record)
    publisher.ensure_resources()
    assert publisher.topic_arn is not None
    queue_url = subscribe_queue(publisher.topic_arn)
    publisher.submit(opened(make_alert("a1", severity=Severity.HIGH)))
    publisher.submit(AlertEvent(AlertChange.ESCALATED, make_alert("a1")))
    await publisher.start()
    await asyncio.wait_for(publisher.drain(), timeout=10)
    await publisher.stop()

    envelopes = receive_envelopes(queue_url)
    assert [json.loads(e["Message"])["event"] for e in envelopes] == ["opened", "escalated"]
    assert [alert_id for alert_id, _ in received] == ["a1"]
    assert received[0][1].sns.message_id == envelopes[-1]["MessageId"]


def test_subject_fits_sns_limit_and_marks_resolution() -> None:
    long_alert = make_alert(summary="x" * 300)
    resolved = make_alert(status="resolved")

    assert len(sns_subject(long_alert, "ClaimsWatch")) == 99
    assert sns_subject(resolved, "ClaimsWatch").startswith("[RESOLVED] ")


def test_subject_has_no_line_breaks_control_or_non_ascii_characters() -> None:
    alert = make_alert(summary="DB timeout\nin\tclaims\x07 \u2014 retry\r\n")

    assert sns_subject(alert, "ClaimsWatch") == "[CRITICAL] ClaimsWatch: DB timeout in claims retry"


def test_existing_topic_arn_is_used_without_creating_a_topic(aws: None) -> None:
    sns = boto3.client("sns", region_name="us-east-1")
    arn = sns.create_topic(Name="log-anomaly-alerts")["TopicArn"]
    publisher = AlertPublisher(settings(sns_topic_arn=arn, sns_topic_name="should-not-exist"))
    publisher.ensure_resources()
    queue_url = subscribe_queue(arn)

    delivery = publisher.deliver(opened(make_alert("arn1")))

    topics = [t["TopicArn"] for t in sns.list_topics()["Topics"]]
    assert topics == [arn]
    assert delivery.sns.status == "sent"
    assert json.loads(receive_envelopes(queue_url)[0]["Message"])["id"] == "arn1"


def test_cloudwatch_can_be_turned_off(aws: None) -> None:
    publisher = AlertPublisher(settings(cw_enabled=False, cw_log_group="/off/alerts"))
    publisher.ensure_resources()

    delivery = publisher.deliver(opened(make_alert()))

    groups = boto3.client("logs", region_name="us-east-1").describe_log_groups()["logGroups"]
    assert publisher.log_group is None
    assert delivery.sns.status == "sent"
    assert delivery.cloudwatch.status == "disabled"
    assert groups == []


def test_credentials_from_settings_are_passed_to_boto3() -> None:
    publisher = AlertPublisher(
        settings(aws_access_key_id="AKIDEXAMPLE", aws_secret_access_key="example-secret")
    )

    kwargs = publisher._client_kwargs()

    assert kwargs["aws_access_key_id"] == "AKIDEXAMPLE"
    assert kwargs["aws_secret_access_key"] == "example-secret"


def test_email_text_is_readable_and_masked() -> None:
    event = opened(critical_alert_from_real_line())

    text = email_text(event, "ClaimsWatch")

    assert text.startswith("ClaimsWatch log anomaly: OPENED")
    assert "Severity:       CRITICAL" in text
    assert "Error rate:     31.00% (baseline 2.00%)" in text
    assert "claim-adjudication (212, 94%)" in text
    assert "<MEMBER_ID>" in text
    for pattern in PHI_PATTERNS:
        assert not re.search(pattern, text), pattern
