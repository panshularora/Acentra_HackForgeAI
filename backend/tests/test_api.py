import time
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

from app.config import Settings
from app.main import create_app
from app.services import Services
from tests.factories import T0

# Buckets are an hour long so the background clock never fires during a test;
# tests close buckets explicitly instead.
TEST_SETTINGS = {
    "bucket_seconds": 3600,
    "window_seconds": 3 * 3600,
    "baseline_min_buckets": 3,
    "min_errors": 3,
    "min_total": 10,
    "tail_poll_seconds": 0.02,
    "aws_enabled": False,
    "stats_history_minutes": 24 * 60,
}


@pytest.fixture
def log_path(tmp_path: Path) -> Path:
    path = tmp_path / "app.log"
    path.write_text("")
    return path


@pytest.fixture
def client(tmp_path: Path, log_path: Path) -> Iterator[TestClient]:
    settings = Settings(log_path=log_path, db_path=tmp_path / "test.db", **TEST_SETTINGS)
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def services_of(client: TestClient) -> Services:
    services: Services = client.app.state.services  # type: ignore[attr-defined]
    return services


def write_lines(client: TestClient, log_path: Path, total: int, errors: int) -> None:
    """Append lines and wait until the pipeline has parsed them."""
    services = services_of(client)
    expected = services.parser.parsed + total
    with log_path.open("a") as handle:
        for n in range(total):
            level, message = ("ERROR", "DB connection timeout") if n < errors else ("INFO", "ok")
            handle.write(
                f'2026-09-28T13:00:00Z {level} claim-adjudication msg="{message}" '
                f"member_id=M{1000000 + n} ip=10.0.0.{n % 250} status=503\n"
            )
    deadline = time.monotonic() + 5
    while services.parser.parsed < expected:
        assert time.monotonic() < deadline, "pipeline did not ingest lines in time"
        time.sleep(0.01)


def close_buckets(client: TestClient, count: int, start: int = 0) -> None:
    pipeline = services_of(client).pipeline
    for n in range(start, start + count):
        client.portal.call(pipeline.close_bucket, T0 + timedelta(hours=n + 1))  # type: ignore[union-attr]


def run_incident(client: TestClient, log_path: Path) -> None:
    for n in range(6):
        write_lines(client, log_path, total=100, errors=2)
        close_buckets(client, 1, start=n)
    write_lines(client, log_path, total=100, errors=60)
    close_buckets(client, 1, start=6)


def test_health_reports_pipeline_state(client: TestClient, log_path: Path) -> None:
    write_lines(client, log_path, total=5, errors=0)

    body = client.get("/api/health").json()

    assert body["status"] == "ok"
    assert body["app"] == "ClaimsWatch"
    assert body["log_path"] == str(log_path)
    assert body["tailer_offset"] == log_path.stat().st_size
    assert body["aws"] == {"sns_topic_arn": None, "cloudwatch_log_group": None, "endpoint": None}
    assert body["pipeline"]["parsed_lines"] == 5


def test_stats_endpoint_returns_closed_buckets(client: TestClient, log_path: Path) -> None:
    write_lines(client, log_path, total=50, errors=1)
    close_buckets(client, 2)

    points = client.get("/api/stats", params={"minutes": 24 * 60}).json()["points"]

    assert len(points) == 2
    assert points[0]["ts"] < points[1]["ts"]
    assert points[0]["total"] == 50
    assert set(points[0]) == {
        "ts",
        "total",
        "errors",
        "error_rate",
        "baseline_median",
        "band_upper",
        "score",
        "severity",
    }


def test_stats_rejects_out_of_range_minutes(client: TestClient) -> None:
    assert client.get("/api/stats", params={"minutes": 0}).status_code == 422


def test_incident_appears_in_alert_list(client: TestClient, log_path: Path) -> None:
    run_incident(client, log_path)

    alerts = client.get("/api/alerts").json()["alerts"]

    assert len(alerts) == 1
    alert = alerts[0]
    assert alert["status"] == "open"
    assert alert["severity"] == "CRITICAL"
    assert alert["summary"] == "100% of errors come from claim-adjudication: DB connection timeout"
    assert alert["delivery"]["sns"]["status"] == "disabled"
    assert all("<MEMBER_ID>" in line for line in alert["sample_lines"])


def test_acknowledge_alert(client: TestClient, log_path: Path) -> None:
    run_incident(client, log_path)
    alert_id = client.get("/api/alerts").json()["alerts"][0]["id"]

    response = client.post(f"/api/alerts/{alert_id}/ack")

    assert response.status_code == 200
    assert response.json()["acknowledged"] is True
    assert client.get("/api/alerts").json()["alerts"][0]["acknowledged"] is True


def test_acknowledge_unknown_alert_is_404(client: TestClient) -> None:
    assert client.post("/api/alerts/nope/ack").status_code == 404


def test_websocket_receives_stats_and_alert_messages(client: TestClient, log_path: Path) -> None:
    with client.websocket_connect("/ws") as ws:
        run_incident(client, log_path)
        messages = [ws.receive_json() for _ in range(8)]

    types = [m["type"] for m in messages]
    assert types.count("stats") == 7
    assert types[-1] == "alert"
    assert messages[-1]["data"]["severity"] == "CRITICAL"
    assert messages[-2]["data"]["severity"] == "CRITICAL"


def test_websocket_ack_is_broadcast(client: TestClient, log_path: Path) -> None:
    run_incident(client, log_path)
    alert_id = client.get("/api/alerts").json()["alerts"][0]["id"]

    with client.websocket_connect("/ws") as ws:
        client.post(f"/api/alerts/{alert_id}/ack")
        message = ws.receive_json()

    assert message == {"type": "alert", "data": client.get("/api/alerts").json()["alerts"][0]}


def test_disconnected_client_is_removed(client: TestClient) -> None:
    with client.websocket_connect("/ws"):
        assert services_of(client).clients.client_count == 1
    deadline = time.monotonic() + 2
    while services_of(client).clients.client_count:
        assert time.monotonic() < deadline
        time.sleep(0.01)


def test_alert_delivery_to_aws_is_reported_on_the_feed(
    tmp_path: Path, log_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        monkeypatch.setenv(key, "testing")
    overrides = {**TEST_SETTINGS, "aws_enabled": True, "aws_endpoint_url": None}
    settings = Settings(log_path=log_path, db_path=tmp_path / "aws.db", **overrides)

    with mock_aws(), TestClient(create_app(settings)) as aws_client:
        health = aws_client.get("/api/health").json()
        with aws_client.websocket_connect("/ws") as ws:
            run_incident(aws_client, log_path)
            alerts = [
                m["data"] for m in (ws.receive_json() for _ in range(9)) if m["type"] == "alert"
            ]

    assert health["aws"]["sns_topic_arn"].endswith(":claimswatch-alerts")
    assert health["aws"]["cloudwatch_log_group"] == "/claimswatch/alerts"
    assert alerts[0]["delivery"]["sns"]["status"] == "pending"
    assert alerts[-1]["delivery"]["sns"]["status"] == "sent"
    assert alerts[-1]["delivery"]["sns"]["message_id"]
    assert alerts[-1]["delivery"]["cloudwatch"]["status"] == "sent"
