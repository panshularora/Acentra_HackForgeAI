import ast
from datetime import timedelta
from pathlib import Path

from app.detection.detector import AlertChange, DetectionResult, Detector, DetectorConfig
from app.models import Severity
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

    assert all(r.stats.score is None and r.alert_event is None for r in results)
    assert results[-1].stats.baseline_median is None


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

    assert opened.alert_event is not None
    assert opened.alert_event.change is AlertChange.OPENED
    assert opened.alert_event.alert.severity is Severity.CRITICAL
    assert opened.stats.severity is Severity.CRITICAL
    assert {f.alert_event.alert.id for f in followups if f.alert_event} == {"inc0"}
    assert all(f.alert_event and f.alert_event.change is AlertChange.UPDATED for f in followups)


def test_incident_explains_what_broke() -> None:
    harness = Harness()
    harness.warm_up()

    for _ in range(3):
        harness.bucket(300, 90, service="claim-adjudication")

    incident = harness.detector.open_incident
    assert incident is not None
    assert incident.summary.endswith("claim-adjudication: DB connection timeout")
    assert incident.top_contributors.services[0].value == "claim-adjudication"
    assert 0 < len(incident.sample_lines) <= 5


def test_moderate_rise_is_high_then_escalates_to_critical() -> None:
    harness = Harness()
    harness.warm_up()

    first = harness.bucket(300, 36)
    second = harness.bucket(300, 90)

    assert first.alert_event and first.alert_event.alert.severity is Severity.HIGH
    assert second.alert_event and second.alert_event.change is AlertChange.ESCALATED
    assert second.alert_event.alert.severity is Severity.CRITICAL


def test_peak_figures_are_kept_when_incident_calms_down() -> None:
    harness = Harness()
    harness.warm_up()
    harness.bucket(300, 120)
    peak = harness.bucket(300, 120).stats.score
    calmer = [harness.bucket(300, 6).stats.score for _ in range(5)][-1]

    incident = harness.detector.open_incident
    assert incident is not None and incident.score == peak
    assert calmer is not None and peak is not None and calmer < peak


def test_incident_resolves_after_consecutive_normal_buckets() -> None:
    harness = Harness()
    harness.warm_up()
    harness.bucket(300, 90)

    # The spike stays in the 60 s window for five more buckets, then three
    # clean buckets are needed before the incident resolves.
    events = [harness.bucket(300, 6).alert_event for _ in range(12)]
    resolved = [e for e in events if e is not None and e.change is AlertChange.RESOLVED]

    assert len(resolved) == 1
    assert events.index(resolved[0]) == 7
    assert all(e is None for e in events[8:])
    assert resolved[0].alert.status == "resolved"
    assert resolved[0].alert.resolved_at is not None
    assert harness.detector.open_incident is None


def test_baseline_is_frozen_while_incident_is_open() -> None:
    harness = Harness()
    harness.warm_up()

    for _ in range(40):
        harness.bucket(300, 90)

    last = harness.bucket(300, 90)
    assert last.stats.baseline_median == 0.02
    assert last.alert_event is not None and last.alert_event.alert.status == "open"


def test_min_error_guard_blocks_alerts_on_tiny_counts() -> None:
    harness = Harness(DetectorConfig(min_errors=5, min_total=10, baseline_min_buckets=6))
    for _ in range(12):
        harness.bucket(20, 0)

    result = harness.bucket(20, 4)

    assert result.stats.score is not None and result.stats.score > 3.5
    assert result.stats.severity is None
    assert result.alert_event is None


def test_min_total_guard_blocks_alerts_on_quiet_traffic() -> None:
    harness = Harness(DetectorConfig(min_errors=1, min_total=500, baseline_min_buckets=6))
    for _ in range(12):
        harness.bucket(20, 0)

    assert harness.bucket(20, 15).alert_event is None


def test_second_spike_after_resolution_opens_a_new_incident() -> None:
    harness = Harness()
    harness.warm_up()
    harness.bucket(300, 90)
    for _ in range(12):
        harness.bucket(300, 6)

    again = harness.bucket(300, 90)

    assert again.alert_event and again.alert_event.change is AlertChange.OPENED
    assert again.alert_event.alert.id == "inc1"


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
    opened = harness.bucket(300, 36).alert_event
    harness.bucket(300, 120)

    assert opened is not None
    assert opened.alert.severity is Severity.HIGH
