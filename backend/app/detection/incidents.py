"""Incident lifecycle shared by every detector: open, update, escalate, resolve.

Detectors only report *findings* ("template 7 is anomalous at HIGH in this
bucket"); this module turns them into alerts. Each incident has a key made of
the detector name and what it watches (a template id, a flow name), so one
problem produces one alert that updates in place, while unrelated problems
get their own.

* The first finding for a key opens an incident. Later findings update it; a
  higher severity escalates it; a higher score refreshes the figures and the
  explanation to the worst point seen.
* After ``resolve_after_buckets`` consecutive buckets without a finding for
  its key, the incident resolves.
"""

import copy
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum

from app.detection.origin import suspected_origin
from app.models import Alert, Explanation, Severity, TopContributors


class AlertChange(StrEnum):
    """What happened to an incident in this bucket."""

    OPENED = "opened"
    UPDATED = "updated"
    ESCALATED = "escalated"
    RESOLVED = "resolved"


@dataclass(frozen=True, slots=True)
class AlertEvent:
    """A snapshot of an incident together with the change that just happened to it.

    The snapshot is a copy, so later buckets never mutate an alert that the
    caller has already queued for storage or delivery.
    """

    change: AlertChange
    alert: Alert

    @classmethod
    def snapshot(cls, change: AlertChange, alert: Alert) -> "AlertEvent":
        """Create an event holding a deep copy of ``alert``."""
        return cls(change, copy.deepcopy(alert))


@dataclass(frozen=True, slots=True)
class Finding:
    """One detector's verdict that something is anomalous in the bucket just closed."""

    key: str
    severity: Severity
    score: float
    summary: str
    explanation: Explanation
    top_contributors: TopContributors = field(default_factory=TopContributors)
    sample_lines: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class WindowContext:
    """Global window figures recorded on every alert, as in contract v1."""

    error_rate: float
    baseline_median: float


def _service_of(explanation: Explanation) -> str | None:
    return explanation.template.service if explanation.template else None


def _alerting_services(
    findings: list[Finding],
    incidents: dict[str, Alert],
    streaks: dict[str, int],
    resolve_after: int,
) -> set[str]:
    """Services that will still have an open incident after this bucket."""
    alerting: set[str] = set()
    reported = {finding.key for finding in findings}
    for finding in findings:
        service = _service_of(finding.explanation)
        if service:
            alerting.add(service)
    for key, incident in incidents.items():
        if key not in reported and streaks.get(key, 0) + 1 >= resolve_after:
            continue
        service = _service_of(incident.explanation)
        if service:
            alerting.add(service)
    return alerting


def _with_origin(finding: Finding, alerting: set[str]) -> Finding:
    origin = suspected_origin(_service_of(finding.explanation), alerting)
    if origin == finding.explanation.suspected_origin:
        return finding
    return replace(finding, explanation=replace(finding.explanation, suspected_origin=origin))


class IncidentTracker:
    """Open incidents by key, advanced once per closed bucket."""

    def __init__(self, resolve_after_buckets: int, id_factory: Callable[[], str]) -> None:
        self._resolve_after = resolve_after_buckets
        self._id_factory = id_factory
        self._incidents: dict[str, Alert] = {}
        self._normal_streaks: dict[str, int] = {}

    @property
    def open_incidents(self) -> list[Alert]:
        """Incidents currently open, oldest first."""
        return list(self._incidents.values())

    def is_open(self, key: str) -> bool:
        """Whether an incident with ``key`` is open."""
        return key in self._incidents

    def advance(
        self, now: datetime, findings: list[Finding], context: WindowContext
    ) -> list[AlertEvent]:
        """Apply this bucket's findings; return what changed, in a stable order."""
        events: list[AlertEvent] = []
        reported = set()
        alerting = _alerting_services(findings, self._incidents, self._normal_streaks, self._resolve_after)
        annotated = [_with_origin(finding, alerting) for finding in findings]
        for finding in annotated:
            reported.add(finding.key)
            self._normal_streaks.pop(finding.key, None)
            if finding.key in self._incidents:
                events.append(self._update(now, finding, context))
            else:
                events.append(self._open(now, finding, context))
        for key in [k for k in self._incidents if k not in reported]:
            resolved = self._record_normal_bucket(now, key)
            if resolved is not None:
                events.append(resolved)
        return events

    def _open(self, now: datetime, finding: Finding, context: WindowContext) -> AlertEvent:
        incident = Alert(
            id=self._id_factory(),
            status="open",
            severity=finding.severity,
            score=finding.score,
            error_rate=context.error_rate,
            baseline_median=context.baseline_median,
            opened_at=now,
            updated_at=now,
            summary=finding.summary,
            top_contributors=finding.top_contributors,
            sample_lines=list(finding.sample_lines),
            explanation=copy.deepcopy(finding.explanation),
        )
        self._incidents[finding.key] = incident
        return AlertEvent.snapshot(AlertChange.OPENED, incident)

    def _update(self, now: datetime, finding: Finding, context: WindowContext) -> AlertEvent:
        incident = self._incidents[finding.key]
        change = AlertChange.UPDATED
        if finding.severity.rank > incident.severity.rank:
            incident.severity = finding.severity
            change = AlertChange.ESCALATED
        if finding.score > incident.score:
            self._record_peak(incident, finding, context)
        incident.updated_at = now
        return AlertEvent.snapshot(change, incident)

    @staticmethod
    def _record_peak(incident: Alert, finding: Finding, context: WindowContext) -> None:
        """Refresh the figures and explanation at the worst point, keeping the first bad line."""
        incident.score = finding.score
        incident.error_rate = context.error_rate
        incident.summary = finding.summary
        incident.top_contributors = finding.top_contributors
        incident.sample_lines = list(finding.sample_lines)
        first_bad_line = incident.explanation.first_bad_line or finding.explanation.first_bad_line
        incident.explanation = replace(
            copy.deepcopy(finding.explanation), first_bad_line=first_bad_line
        )

    def _record_normal_bucket(self, now: datetime, key: str) -> AlertEvent | None:
        streak = self._normal_streaks.get(key, 0) + 1
        if streak < self._resolve_after:
            self._normal_streaks[key] = streak
            return None
        resolved = self._incidents.pop(key)
        self._normal_streaks.pop(key, None)
        resolved.status = "resolved"
        resolved.resolved_at = now
        resolved.updated_at = now
        return AlertEvent.snapshot(AlertChange.RESOLVED, resolved)
