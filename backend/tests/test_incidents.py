from datetime import timedelta

from app.detection.incidents import AlertChange, Finding, IncidentTracker, WindowContext
from app.models import Explanation, Severity
from tests.factories import T0

CONTEXT = WindowContext(error_rate=0.1, baseline_median=0.02)


def finding(key: str, severity: Severity, score: float, first_bad_line: str) -> Finding:
    return Finding(
        key=key,
        severity=severity,
        score=score,
        summary=f"{key} at {score}",
        explanation=Explanation(detector="error_spike", first_bad_line=first_bad_line),
    )


def tracker() -> IncidentTracker:
    ids = iter(f"inc{n}" for n in range(10))
    return IncidentTracker(resolve_after_buckets=2, id_factory=lambda: next(ids))


def test_peak_refresh_keeps_the_first_bad_line() -> None:
    incidents = tracker()
    incidents.advance(T0, [finding("a", Severity.WARNING, 4.0, "first")], CONTEXT)

    [event] = incidents.advance(T0, [finding("a", Severity.CRITICAL, 9.0, "later")], CONTEXT)

    assert event.change is AlertChange.ESCALATED
    assert event.alert.summary == "a at 9.0"
    assert event.alert.explanation.first_bad_line == "first"


def test_keys_are_tracked_and_resolved_independently() -> None:
    incidents = tracker()
    incidents.advance(T0, [finding("a", Severity.HIGH, 6.0, "a1")], CONTEXT)
    later = T0 + timedelta(seconds=10)

    first = incidents.advance(later, [finding("b", Severity.HIGH, 6.0, "b1")], CONTEXT)
    second = incidents.advance(later, [finding("b", Severity.HIGH, 6.0, "b1")], CONTEXT)

    assert [(e.change, e.alert.id) for e in first] == [(AlertChange.OPENED, "inc1")]
    assert [(e.change, e.alert.id) for e in second] == [
        (AlertChange.UPDATED, "inc1"),
        (AlertChange.RESOLVED, "inc0"),
    ]
    assert incidents.is_open("b") and not incidents.is_open("a")


def test_a_finding_resets_the_normal_streak() -> None:
    incidents = tracker()
    incidents.advance(T0, [finding("a", Severity.HIGH, 6.0, "a1")], CONTEXT)
    incidents.advance(T0, [], CONTEXT)
    incidents.advance(T0, [finding("a", Severity.HIGH, 5.0, "a1")], CONTEXT)

    assert incidents.advance(T0, [], CONTEXT) == []
    assert incidents.open_incidents[0].score == 6.0
