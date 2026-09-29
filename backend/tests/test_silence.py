from datetime import timedelta

from app.detection.detector import AlertChange, Detector, DetectorConfig
from app.models import Severity
from tests.factories import T0, make_event

CONFIG = DetectorConfig(
    window_buckets=6,
    bucket_seconds=10,
    baseline_min_buckets=6,
    silence_min_gaps=6,
    silence_min_seconds=20.0,
    silence_factor=3.0,
    silence_max_cv=0.25,
)


def heartbeat(ts, service: str = "eligibility-sync"):
    message = f"heartbeat service={service} ok"
    stamp = ts.strftime("%Y-%m-%dT%H:%M:%SZ")
    return make_event(
        "INFO",
        service,
        message,
        ts=ts,
        raw=f'{stamp} INFO {service} msg="{message}"',
    )


def test_steady_heartbeat_fires_after_it_stops() -> None:
    ids = iter(f"s{n}" for n in range(10))
    detector = Detector(CONFIG, id_factory=lambda: next(ids))
    now = T0
    for second in range(0, 60, 5):
        ts = T0 + timedelta(seconds=second)
        detector.observe(heartbeat(ts))
        if (second + 5) % 10 == 0:
            now = T0 + timedelta(seconds=second + 5)
            detector.close_bucket(now)

    opened = None
    for _ in range(6):
        now += timedelta(seconds=10)
        result = detector.close_bucket(now)
        if result.alert_events:
            opened = result
            break

    assert opened is not None
    [event] = opened.alert_events
    assert event.change is AlertChange.OPENED
    assert event.alert.explanation.detector == "silence"
    assert event.alert.explanation.template is not None
    assert event.alert.explanation.template.service == "eligibility-sync"
    assert event.alert.explanation.baseline_band is not None
    assert event.alert.explanation.baseline_band.unit == "seconds between lines"
    assert event.alert.explanation.first_bad_line is None
    assert event.alert.severity in {Severity.WARNING, Severity.HIGH, Severity.CRITICAL}


def test_bursty_errors_never_qualify_as_silence() -> None:
    ids = iter(f"s{n}" for n in range(10))
    detector = Detector(CONFIG, id_factory=lambda: next(ids))
    now = T0
    for bucket in range(12):
        for n in range(20):
            ts = now + timedelta(milliseconds=n * 30)
            detector.observe(
                make_event(
                    "ERROR",
                    "claim-adjudication",
                    "DB connection timeout",
                    ts=ts,
                    raw=f'{ts.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]}Z ERROR claim-adjudication msg="DB connection timeout"',
                )
            )
        now += timedelta(seconds=10)
        detector.close_bucket(now)
    for _ in range(6):
        now += timedelta(seconds=10)
        result = detector.close_bucket(now)
        assert not any(e.alert.explanation.detector == "silence" for e in result.alert_events)


def test_silence_does_not_fire_during_warm_up_of_gaps() -> None:
    ids = iter(f"s{n}" for n in range(10))
    detector = Detector(CONFIG, id_factory=lambda: next(ids))
    now = T0
    detector.observe(heartbeat(now))
    now += timedelta(seconds=10)
    result = detector.close_bucket(now)
    assert not result.alert_events
