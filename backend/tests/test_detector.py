import ast
from datetime import timedelta
from pathlib import Path

from app.detection.detector import AlertChange, DetectionResult, Detector, DetectorConfig
from app.models import LearningState, Severity
from tests.factories import T0, make_event

CONFIG = DetectorConfig(
    window_buckets=6,
    bucket_seconds=10,
    baseline_buckets=30,
    baseline_min_buckets=6,
    mad_floor=0.002,
    min_errors=5,
    min_total=50,
    resolve_after_buckets=3,
)


class Harness:
    """Drives a Detector bucket by bucket on a simulated clock."""

    def __init__(self, config: DetectorConfig = CONFIG) -> None:
        ids = iter(f"inc{n}" for n in range(100))
        self.detector = Detector(config, id_factory=lambda: next(ids))
        self.now = T0

    def bucket(
        self, total: int, errors: int, service: str = "eligibility-check"
    ) -> DetectionResult:
        for _ in range(total - errors):
            self.detector.observe(make_event("INFO"))
        for _ in range(errors):
            self.detector.observe(make_event("ERROR", service, "DB connection timeout"))
        self.now += timedelta(seconds=10)
        return self.detector.close_bucket(self.now)

    def warm_up(self, buckets: int = 12) -> None:
        for _ in range(buckets):
            self.bucket(300, 6)


def test_no_scores_or_alerts_while_warming_up() -> None:
    harness = Harness()

    results = [harness.bucket(300, 150) for _ in range(5)]

    assert all(r.stats.score is None and not r.alert_events for r in results)
    assert results[-1].stats.baseline_median is None
    assert results[-1].stats.learning == LearningState("learning", 0, 6, 2)


def test_learning_state_reports_ready_once_warm() -> None:
    harness = Harness()
    harness.warm_up()

    learning = harness.bucket(300, 6).stats.learning

    assert learning is not None
    assert (learning.state, learning.buckets_needed, learning.templates) == ("ready", 6, 2)
    assert learning.buckets_seen >= 6


def test_baseline_waits_for_a_full_window_before_learning() -> None:
    harness = Harness()
    for _ in range(10):
        harness.bucket(300, 6)
    assert not harness.detector.baseline_warm

    harness.bucket(300, 6)

    assert harness.detector.baseline_warm


def test_stats_point_reports_window_totals() -> None:
    harness = Harness()
    harness.warm_up()

    stats = harness.bucket(300, 6).stats

    assert (stats.total, stats.errors) == (1800, 36)
    assert stats.error_rate == 0.02
    assert stats.baseline_median == 0.02
    assert stats.score == 0.0
    assert stats.severity is None
    assert stats.band_upper is not None and stats.band_upper > 0.02


def test_spike_opens_exactly_one_incident_with_severity() -> None:
    harness = Harness()
    harness.warm_up()

    opened = harness.bucket(300, 90, service="claim-adjudication")
    followups = [harness.bucket(300, 90, service="claim-adjudication") for _ in range(3)]

    assert [e.change for e in opened.alert_events] == [AlertChange.OPENED]
    assert opened.alert_events[0].alert.severity is Severity.CRITICAL
    assert opened.stats.severity is Severity.CRITICAL
    assert {e.alert.id for f in followups for e in f.alert_events} == {"inc0"}
    assert all([e.change for e in f.alert_events] == [AlertChange.UPDATED] for f in followups)


def test_incident_explains_what_broke() -> None:
    harness = Harness()
    harness.warm_up()

    for _ in range(3):
        harness.bucket(300, 90, service="claim-adjudication")

    [incident] = harness.detector.open_incidents
    assert incident.summary == "94% of errors come from claim-adjudication: DB connection timeout"
    assert incident.top_contributors.services[0].value == "claim-adjudication"
    assert 0 < len(incident.sample_lines) <= 5


def test_incident_carries_its_template_band_and_first_bad_line() -> None:
    harness = Harness()
    harness.warm_up()

    harness.bucket(300, 90, service="claim-adjudication")

    [incident] = harness.detector.open_incidents
    explanation = incident.explanation
    assert explanation.detector == "error_spike"
    assert explanation.template is not None
    assert explanation.template.service == "claim-adjudication"
    assert 'msg="DB connection timeout"' in explanation.template.text
    assert explanation.baseline_band is not None
    assert explanation.baseline_band.median == 0.0
    assert explanation.baseline_band.unit == "errors/60s"
    assert explanation.observed == 90
    assert explanation.first_bad_line is not None
    assert "claim-adjudication" in explanation.first_bad_line


def test_a_new_error_template_alerts_even_when_the_global_rate_barely_moves() -> None:
    harness = Harness()
    harness.warm_up()

    result = harness.bucket(300, 20, service="claim-adjudication")

    assert result.stats.score is not None and result.stats.score < 3.5
    assert [e.change for e in result.alert_events] == [AlertChange.OPENED]


def test_each_template_gets_its_own_incident() -> None:
    harness = Harness()
    harness.warm_up()

    harness.bucket(300, 40, service="claim-adjudication")
    result = harness.bucket(300, 40, service="payment-gateway")

    changes = {
        e.alert.explanation.template.service: e.change
        for e in result.alert_events
        if e.alert.explanation.template is not None
    }
    assert changes == {
        "claim-adjudication": AlertChange.UPDATED,
        "payment-gateway": AlertChange.OPENED,
    }
    assert len(harness.detector.open_incidents) == 2


def test_moderate_rise_is_high_then_escalates_to_critical() -> None:
    harness = Harness()
    harness.warm_up()

    # Baseline: 36 errors per window, MAD floored at 0.6745 * sqrt(36) for counts.
    first = harness.bucket(300, 40)
    second = harness.bucket(300, 90)

    assert first.alert_events[0].alert.severity is Severity.HIGH
    assert second.alert_events[0].change is AlertChange.ESCALATED
    assert second.alert_events[0].alert.severity is Severity.CRITICAL


def test_peak_figures_are_kept_when_incident_calms_down() -> None:
    harness = Harness()
    harness.warm_up()
    harness.bucket(300, 40)
    peak = harness.bucket(300, 120).alert_events[0].alert.score
    calmer = harness.bucket(300, 6).alert_events[0].alert

    [incident] = harness.detector.open_incidents
    assert incident.score == peak
    assert calmer.score == peak
    assert calmer.explanation.observed == 40 + 120 + 4 * 6


def test_incident_resolves_after_consecutive_normal_buckets() -> None:
    harness = Harness()
    harness.warm_up()
    harness.bucket(300, 90)

    # The spike stays in the 60 s window for five more buckets, then three
    # clean buckets are needed before the incident resolves.
    events = [harness.bucket(300, 6).alert_events for _ in range(12)]
    resolved = [
        n for n, bucket in enumerate(events) for e in bucket if e.change is AlertChange.RESOLVED
    ]

    assert resolved == [7]
    assert all(not bucket for bucket in events[8:])
    assert events[7][0].alert.status == "resolved"
    assert events[7][0].alert.resolved_at is not None
    assert harness.detector.open_incidents == []


def test_baseline_is_frozen_while_incident_is_open() -> None:
    harness = Harness()
    harness.warm_up()

    for _ in range(40):
        harness.bucket(300, 90)

    last = harness.bucket(300, 90)
    assert last.stats.baseline_median == 0.02
    assert last.alert_events[0].alert.status == "open"
    assert last.alert_events[0].alert.explanation.baseline_band is not None
    assert last.alert_events[0].alert.explanation.baseline_band.median == 36


def test_min_error_guard_blocks_alerts_on_tiny_counts() -> None:
    harness = Harness(DetectorConfig(min_errors=5, min_total=10, baseline_min_buckets=6))
    for _ in range(12):
        harness.bucket(20, 0)

    result = harness.bucket(20, 4)

    assert result.stats.score is not None and result.stats.score > 3.5
    assert result.stats.severity is None
    assert not result.alert_events


def test_min_total_guard_blocks_alerts_on_quiet_traffic() -> None:
    harness = Harness(DetectorConfig(min_errors=1, min_total=500, baseline_min_buckets=6))
    for _ in range(12):
        harness.bucket(20, 0)

    assert not harness.bucket(20, 15).alert_events


def test_second_spike_after_resolution_opens_a_new_incident() -> None:
    harness = Harness()
    harness.warm_up()
    harness.bucket(300, 90)
    for _ in range(12):
        harness.bucket(300, 6)

    again = harness.bucket(300, 90)

    assert [e.change for e in again.alert_events] == [AlertChange.OPENED]
    assert again.alert_events[0].alert.id == "inc1"


def test_empty_window_has_no_rate_and_teaches_the_baseline_nothing() -> None:
    harness = Harness()
    harness.warm_up()
    for _ in range(6):
        result = harness.bucket(0, 0)

    assert result.stats.total == 0
    assert result.stats.error_rate is None
    assert result.stats.score is None
    assert result.stats.severity is None
    assert result.stats.to_dict()["error_rate"] is None
    assert result.stats.baseline_median == 0.02


def test_partly_empty_window_still_has_a_rate() -> None:
    harness = Harness()
    harness.warm_up()

    stats = harness.bucket(0, 0).stats

    assert stats.error_rate == 0.02
    assert stats.score == 0.0


def test_detection_package_has_no_web_or_cloud_dependencies() -> None:
    forbidden = {"fastapi", "starlette", "boto3", "botocore", "uvicorn"}
    package = Path(__file__).parents[1] / "app" / "detection"

    for source in package.glob("*.py"):
        tree = ast.parse(source.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = {node.module.split(".")[0]}
            else:
                continue
            assert not names & forbidden, f"{source.name} imports {names & forbidden}"


def test_emitted_alerts_are_snapshots() -> None:
    harness = Harness()
    harness.warm_up()
    [opened] = harness.bucket(300, 40).alert_events
    harness.bucket(300, 120)

    assert opened.alert.severity is Severity.HIGH
