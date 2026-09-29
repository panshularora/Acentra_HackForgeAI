from datetime import timedelta

from app.detection.detector import AlertChange, Detector, DetectorConfig
from tests.factories import T0, make_event


def claim_pair(now, claim_id: str, complete: bool) -> list:
    validated = make_event(
        "INFO",
        "claim-intake",
        "claim validated",
        ts=now,
        params=(("claim_id", claim_id),),
        raw=f'{now.strftime("%Y-%m-%dT%H:%M:%SZ")} INFO claim-intake msg="claim validated" claim_id={claim_id}',
    )
    events = [validated]
    if complete:
        later = now + timedelta(seconds=1)
        events.append(
            make_event(
                "INFO",
                "claim-adjudication",
                "claim adjudicated",
                ts=later,
                params=(("claim_id", claim_id),),
                raw=(
                    f'{later.strftime("%Y-%m-%dT%H:%M:%SZ")} INFO claim-adjudication '
                    f'msg="claim adjudicated" claim_id={claim_id}'
                ),
            )
        )
    return events


def test_completed_pairs_do_not_alert() -> None:
    config = DetectorConfig(
        window_buckets=6, bucket_seconds=10, baseline_min_buckets=6, flow_timeout_seconds=5
    )
    detector = Detector(config)
    now = T0
    for bucket in range(12):
        for n in range(4):
            for event in claim_pair(now, f"CLM-{bucket:02d}{n}", complete=True):
                detector.observe(event)
        now += timedelta(seconds=10)
        result = detector.close_bucket(now)
        assert not any(e.alert.explanation.detector == "flow_break" for e in result.alert_events)


def test_stopped_adjudication_opens_flow_break() -> None:
    config = DetectorConfig(
        window_buckets=6, bucket_seconds=10, baseline_min_buckets=6, flow_timeout_seconds=5
    )
    ids = iter(f"f{n}" for n in range(10))
    detector = Detector(config, id_factory=lambda: next(ids))
    now = T0
    n = 0
    for _bucket in range(12):
        for _ in range(8):
            complete = n % 50 != 0  # ~2% incomplete, like loggen
            for event in claim_pair(now, f"CLM-{n:04d}", complete=complete):
                detector.observe(event)
            n += 1
        now += timedelta(seconds=10)
        detector.close_bucket(now)

    opened = None
    for _bucket in range(8):
        for _ in range(8):
            for event in claim_pair(now, f"CLM-{n:04d}", complete=False):
                detector.observe(event)
            n += 1
        now += timedelta(seconds=10)
        result = detector.close_bucket(now)
        flow = [e for e in result.alert_events if e.alert.explanation.detector == "flow_break"]
        if flow:
            opened = flow[0]
            break

    assert opened is not None
    assert opened.change is AlertChange.OPENED
    assert opened.alert.explanation.baseline_band is not None
    assert opened.alert.explanation.baseline_band.unit == "incomplete flows/60s"
    assert opened.alert.explanation.observed is not None
    assert opened.alert.explanation.observed > opened.alert.explanation.baseline_band.median
