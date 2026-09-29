from datetime import timedelta

from app.detection.detector import AlertChange, Detector, DetectorConfig
from tests.factories import T0, make_event


def test_new_error_template_after_warmup_opens_new_pattern() -> None:
    config = DetectorConfig(window_buckets=6, bucket_seconds=10, baseline_min_buckets=6, min_errors=5)
    ids = iter(f"n{n}" for n in range(10))
    detector = Detector(config, id_factory=lambda: next(ids))
    now = T0
    for _ in range(12):
        detector.observe(make_event("INFO", "eligibility-check", "eligibility verified"))
        now += timedelta(seconds=10)
        detector.close_bucket(now)

    for _ in range(2):
        detector.observe(
            make_event(
                "ERROR",
                "payment-gateway",
                "TLS certificate verification failed for payer gateway",
            )
        )
    now += timedelta(seconds=10)
    result = detector.close_bucket(now)

    assert [e.change for e in result.alert_events] == [AlertChange.OPENED]
    assert result.alert_events[0].alert.explanation.detector == "new_pattern"
    assert result.alert_events[0].alert.explanation.observed == 2


def test_one_occurrence_does_not_fire() -> None:
    config = DetectorConfig(window_buckets=6, bucket_seconds=10, baseline_min_buckets=6)
    detector = Detector(config)
    now = T0
    for _ in range(12):
        detector.observe(make_event("INFO"))
        now += timedelta(seconds=10)
        detector.close_bucket(now)
    detector.observe(make_event("ERROR", "payment-gateway", "TLS certificate verification failed"))
    now += timedelta(seconds=10)
    assert not detector.close_bucket(now).alert_events


def test_error_spike_claims_a_loud_new_template() -> None:
    config = DetectorConfig(
        window_buckets=6, bucket_seconds=10, baseline_min_buckets=6, min_errors=5, min_total=10
    )
    ids = iter(f"n{n}" for n in range(10))
    detector = Detector(config, id_factory=lambda: next(ids))
    now = T0
    for _ in range(12):
        for _n in range(20):
            detector.observe(make_event("INFO"))
        now += timedelta(seconds=10)
        detector.close_bucket(now)
    for _ in range(20):
        detector.observe(make_event("ERROR", "claim-adjudication", "DB connection timeout"))
    now += timedelta(seconds=10)
    result = detector.close_bucket(now)
    detectors = [e.alert.explanation.detector for e in result.alert_events]
    assert "error_spike" in detectors
    assert "new_pattern" not in detectors
