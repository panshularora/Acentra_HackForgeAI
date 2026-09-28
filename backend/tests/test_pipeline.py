import asyncio
import contextlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from moto import mock_aws

from app.alerts.publisher import AlertPublisher
from app.alerts.store import AlertStore, StatsHistory
from app.api.ws import ConnectionManager
from app.config import Settings
from app.detection.detector import AlertEvent, Detector, DetectorConfig
from app.ingest.parser import LogParser
from app.ingest.tailer import FileTailer
from app.models import ChannelDelivery, Delivery
from app.pipeline import AlertSink, Pipeline
from tests.aws import receive_envelopes, subscribe_queue
from tests.factories import T0, make_event


class RecordingSink:
    def __init__(self) -> None:
        self.submitted: list[AlertEvent] = []

    def submit(self, event: AlertEvent) -> None:
        self.submitted.append(event)


def build(tmp_path: Path, sink: AlertSink | None) -> Pipeline:
    return Pipeline(
        tailer=FileTailer(tmp_path / "app.log"),
        parser=LogParser(),
        detector=Detector(DetectorConfig(baseline_min_buckets=6)),
        store=AlertStore(":memory:"),
        stats=StatsHistory(100),
        clients=ConnectionManager(),
        sink=sink,
    )


async def feed(pipeline: Pipeline, bucket: int, total: int, errors: int) -> None:
    for n in range(total):
        pipeline.detector.observe(make_event("ERROR" if n < errors else "INFO"))
    await pipeline.close_bucket(T0 + timedelta(seconds=10 * (bucket + 1)))


async def run_incident(pipeline: Pipeline) -> None:
    for bucket, errors in enumerate([6] * 12 + [36, 90, 90] + [6] * 10):
        await feed(pipeline, bucket, 300, errors)


async def test_only_open_escalate_and_resolve_are_sent_to_aws(tmp_path: Path) -> None:
    sink = RecordingSink()
    pipeline = build(tmp_path, sink)

    await run_incident(pipeline)

    assert [(e.change, e.alert.status, e.alert.severity.value) for e in sink.submitted] == [
        ("opened", "open", "HIGH"),
        ("escalated", "open", "CRITICAL"),
        ("resolved", "resolved", "CRITICAL"),
    ]
    assert len({e.alert.id for e in sink.submitted}) == 1


async def test_incident_lifecycle_reaches_sns_as_three_messages_in_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        monkeypatch.setenv(key, "testing")
    with mock_aws():
        publisher = AlertPublisher(Settings(aws_endpoint_url=None, aws_region="us-east-1"))
        await publisher.start()
        assert publisher.topic_arn is not None
        queue_url = subscribe_queue(publisher.topic_arn)
        pipeline = build(tmp_path, publisher)
        publisher.on_delivery = pipeline.record_delivery

        await run_incident(pipeline)
        await asyncio.wait_for(publisher.drain(), timeout=10)
        await publisher.stop()
        envelopes = receive_envelopes(queue_url)

    attributes = [
        {name: value["Value"] for name, value in envelope["MessageAttributes"].items()}
        for envelope in envelopes
    ]
    assert attributes == [
        {"event": "opened", "status": "open", "severity": "HIGH"},
        {"event": "escalated", "status": "open", "severity": "CRITICAL"},
        {"event": "resolved", "status": "resolved", "severity": "CRITICAL"},
    ]
    bodies = [json.loads(envelope["Message"]) for envelope in envelopes]
    assert [body["event"] for body in bodies] == ["opened", "escalated", "resolved"]
    assert len({body["id"] for body in bodies}) == 1
    stored = pipeline.store.list_recent()
    assert len(stored) == 1
    assert stored[0].delivery.sns.message_id == envelopes[-1]["MessageId"]


async def test_every_bucket_is_kept_in_stats_history(tmp_path: Path) -> None:
    pipeline = build(tmp_path, None)

    await run_incident(pipeline)

    assert len(pipeline.stats.since(minutes=60)) == 25


async def test_delivery_is_disabled_without_a_sink(tmp_path: Path) -> None:
    pipeline = build(tmp_path, None)

    await run_incident(pipeline)

    alert = pipeline.store.list_recent()[0]
    assert alert.delivery.sns.status == alert.delivery.cloudwatch.status == "disabled"


async def test_recorded_delivery_survives_later_detection_updates(tmp_path: Path) -> None:
    pipeline = build(tmp_path, RecordingSink())
    for bucket, errors in enumerate([6] * 12 + [36]):
        await feed(pipeline, bucket, 300, errors)
    alert_id = pipeline.store.list_recent()[0].id

    await pipeline.record_delivery(alert_id, Delivery(sns=ChannelDelivery("sent", "m-1")))
    await feed(pipeline, 13, 300, 6)

    stored = pipeline.store.get(alert_id)
    assert stored is not None
    assert stored.updated_at == T0 + timedelta(seconds=140)
    assert stored.delivery.sns.message_id == "m-1"


async def test_escalation_marks_the_new_delivery_pending(tmp_path: Path) -> None:
    pipeline = build(tmp_path, RecordingSink())
    for bucket, errors in enumerate([6] * 12 + [36]):
        await feed(pipeline, bucket, 300, errors)
    alert_id = pipeline.store.list_recent()[0].id
    failed = ChannelDelivery("failed", error="timeout")
    await pipeline.record_delivery(alert_id, Delivery(ChannelDelivery("sent", "m-1"), failed))
    broadcasts: list[dict[str, Any]] = []

    async def record(message_type: str, data: dict[str, Any]) -> None:
        if message_type == "alert":
            broadcasts.append(data)

    pipeline.clients.broadcast = record  # type: ignore[method-assign]
    await feed(pipeline, 13, 300, 90)

    stored = pipeline.store.get(alert_id)
    assert stored is not None
    assert stored.severity.value == "CRITICAL"
    assert stored.delivery == Delivery()
    assert [b["delivery"] for b in broadcasts] == [Delivery().to_dict()]


class EarlyWakingClock:
    """Fake wall clock whose sleep always returns slightly before the deadline."""

    def __init__(self, start: float) -> None:
        self.now = start

    def time(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += max(seconds - 0.004, 0.001)


async def run_clock(pipeline: Pipeline, closes: int) -> list[datetime]:
    closed: list[datetime] = []

    async def record(end: datetime) -> None:
        closed.append(end)
        if len(closed) == closes:
            raise asyncio.CancelledError

    pipeline.close_bucket = record  # type: ignore[method-assign,assignment]
    with contextlib.suppress(asyncio.CancelledError):
        await pipeline._clock_loop()
    return closed


async def test_bucket_clock_closes_each_boundary_once_even_when_sleep_wakes_early(
    tmp_path: Path,
) -> None:
    clock = EarlyWakingClock(start=1_000_003.2)
    pipeline = build(tmp_path, None)
    pipeline._clock, pipeline._sleep = clock.time, clock.sleep

    closed = await run_clock(pipeline, closes=6)

    seconds = [c.timestamp() for c in closed]
    assert seconds == [1_000_010.0 + 10 * n for n in range(6)]
    assert all(c.tzinfo is UTC for c in closed)


async def test_bucket_clock_skips_missed_boundaries_after_a_stall(tmp_path: Path) -> None:
    clock = EarlyWakingClock(start=1_000_000.0)
    pipeline = build(tmp_path, None)
    pipeline._clock, pipeline._sleep = clock.time, clock.sleep
    pipeline._last_boundary = 999_950.0  # stalled for five buckets

    closed = await run_clock(pipeline, closes=2)

    assert [c.timestamp() for c in closed] == [1_000_010.0, 1_000_020.0]


class StopLoopError(Exception):
    pass


async def test_ingest_survives_an_unreadable_log_and_recovers(tmp_path: Path) -> None:
    log = tmp_path / "app.log"
    log.mkdir()  # opening a directory raises IsADirectoryError, like a bad rotation
    delays: list[float] = []
    health: list[bool] = []

    async def fake_sleep(seconds: float) -> None:
        delays.append(seconds)
        health.append(pipeline.healthy)
        if len(delays) == 2:
            log.rmdir()
            log.write_text("")
        elif len(delays) == 3:
            log.write_text('2026-09-28T13:00:00Z INFO eligibility-check msg="ok"\n')
        elif len(delays) == 4:
            raise StopLoopError

    pipeline = Pipeline(
        tailer=FileTailer(log, poll_interval=0.25),
        parser=LogParser(),
        detector=Detector(DetectorConfig()),
        store=AlertStore(":memory:"),
        stats=StatsHistory(100),
        clients=ConnectionManager(),
        sleep=fake_sleep,
    )

    with pytest.raises(StopLoopError):
        await pipeline._ingest_loop()

    assert delays == [1.0, 2.0, 0.25, 0.25]
    assert health == [False, False, True, True]
    assert pipeline.ingest_error is None
    assert pipeline.parser.parsed == 1


async def test_a_line_that_breaks_processing_is_dropped_not_fatal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = tmp_path / "app.log"
    log.write_text("")
    pipeline = build(tmp_path, None)
    pipeline.tailer = FileTailer(log, from_start=True)
    real_parse = pipeline.parser.parse

    def parse(line: str) -> Any:
        if "boom" in line:
            raise ValueError("parser bug")
        return real_parse(line)

    monkeypatch.setattr(pipeline.parser, "parse", parse)
    log.write_text(
        '2026-09-28T13:00:00Z INFO eligibility-check msg="boom"\n'
        '2026-09-28T13:00:00Z INFO eligibility-check msg="ok"\n'
    )

    async def stop_after_first_poll(seconds: float) -> None:
        raise StopLoopError

    pipeline._sleep = stop_after_first_poll
    with pytest.raises(StopLoopError):
        await pipeline._ingest_loop()

    assert pipeline.parser.parsed == 1
    assert pipeline.healthy


async def test_pipeline_reports_unhealthy_once_it_stops(tmp_path: Path) -> None:
    pipeline = build(tmp_path, None)
    task = asyncio.create_task(pipeline.run())
    await asyncio.sleep(0)
    assert pipeline.healthy

    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    assert not pipeline.healthy


async def test_recovering_from_a_read_error_does_not_reread_old_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = tmp_path / "app.log"
    line = '2026-09-28T13:00:00Z INFO eligibility-check msg="ok"\n'
    log.write_text(line * 1000)
    tailer = FileTailer(log)
    assert tailer.read_lines() == []  # tail -f: starts at the end
    real_read = tailer.read_lines
    calls = 0

    def flaky_read() -> list[str]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError(5, "Input/output error")
        return real_read()

    monkeypatch.setattr(tailer, "read_lines", flaky_read)

    async def fake_sleep(seconds: float) -> None:
        if calls == 1:
            with log.open("a") as handle:
                handle.write(line)
        elif calls == 2:
            raise StopLoopError

    pipeline = build(tmp_path, None)
    pipeline.tailer = tailer
    pipeline._sleep = fake_sleep

    with pytest.raises(StopLoopError):
        await pipeline._ingest_loop()

    assert pipeline.parser.parsed == 1
    assert pipeline.ingest_error is None
