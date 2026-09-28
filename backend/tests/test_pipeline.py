from datetime import timedelta
from pathlib import Path

from app.alerts.store import AlertStore, StatsHistory
from app.api.ws import ConnectionManager
from app.detection.detector import Detector, DetectorConfig
from app.ingest.parser import LogParser
from app.ingest.tailer import FileTailer
from app.models import Alert, ChannelDelivery, Delivery
from app.pipeline import Pipeline
from tests.factories import T0, make_event


class RecordingSink:
    def __init__(self) -> None:
        self.submitted: list[Alert] = []

    def submit(self, alert: Alert) -> None:
        self.submitted.append(alert)


def build(tmp_path: Path, sink: RecordingSink | None) -> Pipeline:
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

    assert [(a.status, a.severity.value) for a in sink.submitted] == [
        ("open", "HIGH"),
        ("open", "CRITICAL"),
        ("resolved", "CRITICAL"),
    ]
    assert len({a.id for a in sink.submitted}) == 1


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
    await feed(pipeline, 13, 300, 90)

    stored = pipeline.store.get(alert_id)
    assert stored is not None
    assert stored.severity.value == "CRITICAL"
    assert stored.delivery.sns.message_id == "m-1"
