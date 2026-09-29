import json
import sqlite3
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
from tests.aws import cloudwatch_messages, receive_envelopes, subscribe_queue
from tests.factories import T0, make_alert

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
    "aws_region": "us-east-1",
    "sns_topic_arn": None,
    "sns_topic_name": "claimswatch-alerts",
    "cw_enabled": True,
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


def write_lines(
    client: TestClient,
    log_path: Path,
    total: int,
    errors: int,
    error_message: str = "DB connection timeout",
) -> None:
    """Append lines and wait until the pipeline has parsed them."""
    services = services_of(client)
    expected = services.parser.parsed + total
    with log_path.open("a") as handle:
        for n in range(total):
            level, message = ("ERROR", error_message) if n < errors else ("INFO", "ok")
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


def run_incident(
    client: TestClient, log_path: Path, error_message: str = "DB connection timeout"
) -> None:
    for n in range(6):
        write_lines(client, log_path, total=100, errors=2, error_message=error_message)
        close_buckets(client, 1, start=n)
    write_lines(client, log_path, total=100, errors=60, error_message=error_message)
    close_buckets(client, 1, start=6)


def test_health_reports_pipeline_state(client: TestClient, log_path: Path) -> None:
    write_lines(client, log_path, total=5, errors=0)

    body = client.get("/api/health").json()

    assert body["status"] == "ok"
    assert body["app"] == "ClaimsWatch"
    assert body["log_path"] == str(log_path)
    assert body["tailer_offset"] == log_path.stat().st_size
    assert body["aws"] == {"sns_topic_arn": None, "cloudwatch_log_group": None, "endpoint": None}
    assert body["detector"] == {
        "window_seconds": 3 * 3600,
        "bucket_seconds": 3600,
        "baseline_min_buckets": 3,
        "detectors": ["error_spike", "silence", "new_pattern", "flow_break"],
    }
    assert body["learning"] == {
        "state": "learning",
        "buckets_seen": 0,
        "buckets_needed": 3,
        "templates": 1,
    }
    assert body["pipeline"] == {
        "parsed_lines": 5,
        "malformed_lines": 0,
        "baseline_warm": False,
        "websocket_clients": 0,
    }
    assert body["faults"] == []


def test_inject_silence_fault_writes_the_generator_control_file(
    client: TestClient, log_path: Path
) -> None:
    response = client.post("/api/faults", json={"name": "heartbeat-stop", "duration": 12})
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "heartbeat-stop"
    assert body["mode"] == "suppress"
    control = log_path.with_name(log_path.name + ".faults.json")
    assert "heartbeat-stop" in control.read_text(encoding="utf-8")
    listed = client.get("/api/faults").json()["faults"]
    assert listed[0]["name"] == "heartbeat-stop"


def test_inject_unknown_fault_is_rejected(client: TestClient) -> None:
    response = client.post("/api/faults", json={"name": "not-a-fault"})
    assert response.status_code == 400


def test_stop_fault_clears_the_generator_control_file(
    client: TestClient, log_path: Path
) -> None:
    injected = client.post("/api/faults", json={"name": "heartbeat-stop", "duration": 60})
    assert injected.status_code == 200
    control = log_path.with_name(log_path.name + ".faults.json")
    assert "heartbeat-stop" in control.read_text(encoding="utf-8")

    stopped = client.delete("/api/faults/heartbeat-stop")
    assert stopped.status_code == 200
    body = stopped.json()
    assert body["stopped"] == "heartbeat-stop"
    assert body["faults"] == []
    assert "heartbeat-stop" not in control.read_text(encoding="utf-8")
    assert client.get("/api/faults").json()["faults"] == []


def test_stop_all_faults_clears_every_active_fault(client: TestClient) -> None:
    first = client.post("/api/faults", json={"name": "heartbeat-stop", "duration": 60})
    second = client.post("/api/faults", json={"name": "flow-break", "duration": 60})
    assert first.status_code == 200
    assert second.status_code == 200

    stopped = client.delete("/api/faults")
    assert stopped.status_code == 200
    body = stopped.json()
    assert body["stopped"] == ["flow-break", "heartbeat-stop"]
    assert body["faults"] == []
    assert client.get("/api/faults").json()["faults"] == []


def test_stop_unknown_fault_is_rejected(client: TestClient) -> None:
    response = client.delete("/api/faults/not-a-fault")
    assert response.status_code == 400


def test_dashboard_index_is_served_when_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dist = tmp_path / "frontend" / "dist" / "assets"
    dist.mkdir(parents=True)
    index = tmp_path / "frontend" / "dist" / "index.html"
    index.write_text("<!doctype html><title>ClaimsWatch</title>", encoding="utf-8")
    monkeypatch.setattr("app.main._REPO_ROOT", tmp_path)
    log_path = tmp_path / "app.log"
    log_path.write_text("ok\n", encoding="utf-8")
    settings = Settings(
        log_path=log_path,
        db_path=tmp_path / "test.db",
        serve_dashboard=True,
        **TEST_SETTINGS,
    )
    with TestClient(create_app(settings)) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert b"ClaimsWatch" in response.content


def test_liveness_probe(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_fails_while_the_log_cannot_be_read(tmp_path: Path) -> None:
    log_dir = tmp_path / "app.log"
    log_dir.mkdir()
    settings = Settings(log_path=log_dir, db_path=tmp_path / "test.db", **TEST_SETTINGS)
    with TestClient(create_app(settings)) as client:
        deadline = time.monotonic() + 5
        while client.get("/health").status_code == 200:
            assert time.monotonic() < deadline, "health never reported the dead ingest"
            time.sleep(0.01)

        assert client.get("/health").json() == {"status": "degraded"}
        body = client.get("/api/health").json()
        assert body["status"] == "degraded"
        assert body["ingest_error"].startswith(("IsADirectoryError", "PermissionError"))


def test_incident_left_open_by_a_previous_run_is_resolved_on_startup(
    tmp_path: Path, log_path: Path
) -> None:
    settings = Settings(log_path=log_path, db_path=tmp_path / "test.db", **TEST_SETTINGS)
    with TestClient(create_app(settings)) as first_run:
        services_of(first_run).store.save_detection(make_alert("stale"))
        assert first_run.get("/api/alerts").json()["alerts"][0]["status"] == "open"

    with TestClient(create_app(settings)) as second_run:
        [alert] = second_run.get("/api/alerts").json()["alerts"]

    assert alert["id"] == "stale"
    assert alert["status"] == "resolved"
    assert alert["resolved_at"] is not None


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
        "learning",
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
    assert alert["detector"] == "error_spike"
    assert alert["template"]["service"] == "claim-adjudication"
    assert 'msg="DB connection timeout"' in alert["template"]["text"]
    assert alert["baseline_band"]["unit"] == f"errors/{3 * 3600}s"
    assert alert["observed"] >= 60
    assert "<MEMBER_ID>" in alert["first_bad_line"]


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


def test_retry_delivery_with_aws_off_queues_nothing(client: TestClient) -> None:
    response = client.post("/api/delivery/retry")
    assert response.status_code == 200
    assert response.json() == {"queued": 0}


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


def test_phi_never_reaches_the_store_the_feed_or_aws(
    tmp_path: Path, log_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        monkeypatch.setenv(key, "testing")
    member_id, phone = "M7310042", "(212) 555-0142"
    overrides = {**TEST_SETTINGS, "aws_enabled": True, "aws_endpoint_url": None}
    settings = Settings(log_path=log_path, db_path=tmp_path / "phi.db", **overrides)

    with mock_aws(), TestClient(create_app(settings)) as aws_client:
        topic_arn = aws_client.get("/api/health").json()["aws"]["sns_topic_arn"]
        queue_url = subscribe_queue(topic_arn)
        with aws_client.websocket_connect("/ws") as ws:
            run_incident(aws_client, log_path, f"lookup failed for {member_id}, call {phone}")
            feed = [ws.receive_json() for _ in range(9)]
        sns = [envelope["Message"] for envelope in receive_envelopes(queue_url)]
        cloudwatch = cloudwatch_messages(settings.cw_log_group, settings.cw_log_stream)
    with sqlite3.connect(settings.db_path) as db:
        rows = db.execute("SELECT * FROM alerts").fetchall()

    assert len(rows) == len(sns) == len(cloudwatch) == 1
    outputs = {
        "sqlite": json.dumps(rows),
        "websocket": json.dumps(feed),
        "sns": json.dumps(sns),
        "cloudwatch": json.dumps(cloudwatch),
    }
    for channel, text in outputs.items():
        assert member_id not in text, channel
        assert phone not in text and "555-0142" not in text, channel
        assert "for <MEMBER_ID>, call <PHONE>" in text, channel
