"""Turn a stream of log events into stats points and incident updates.

The detector is deliberately free of I/O: it knows nothing about files,
FastAPI or AWS, and time only moves when the caller closes a bucket. The live
pipeline closes buckets on a wall-clock timer; the replay tool closes them on
a simulated clock. Both get identical behaviour.

Incident lifecycle
------------------
* A closed bucket is *anomalous* when the baseline is warm, the window holds
  at least ``min_errors`` errors and ``min_total`` lines, and the modified
  z-score reaches the WARNING threshold.
* The first anomalous bucket opens an incident (one alert). Further anomalous
  buckets update it; a higher severity escalates it.
* After ``resolve_after_buckets`` consecutive normal buckets it resolves.
* While an incident is open the baseline is frozen, so a long outage never
  teaches the detector that failing is normal.
"""

import copy
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from app.config import Settings
from app.detection.baseline import RobustBaseline
from app.detection.contributors import sample_lines, summarise, top_contributors
from app.detection.severity import SeverityThresholds, classify
from app.detection.window import BucketAccumulator, SlidingWindow
from app.models import Alert, LogEvent, Severity, StatsPoint


@dataclass(frozen=True, slots=True)
class DetectorConfig:
    """Tuning knobs for :class:`Detector`. See :class:`app.config.Settings` for meanings."""

    window_buckets: int = 6
    bucket_seconds: int = 10
    baseline_buckets: int = 30
    baseline_min_buckets: int = 6
    mad_floor: float = 0.002
    min_errors: int = 5
    min_total: int = 50
    resolve_after_buckets: int = 3
    thresholds: SeverityThresholds = field(default_factory=SeverityThresholds)
    sample_line_limit: int = 5
    contributor_limit: int = 3

    @property
    def window_seconds(self) -> int:
        """Duration covered by the sliding window."""
        return self.window_buckets * self.bucket_seconds

    @classmethod
    def from_settings(cls, settings: Settings) -> "DetectorConfig":
        """Build the detector configuration from application settings."""
        return cls(
            window_buckets=settings.buckets_per_window,
            bucket_seconds=settings.bucket_seconds,
            baseline_buckets=settings.baseline_buckets,
            baseline_min_buckets=settings.baseline_min_buckets,
            mad_floor=settings.mad_floor,
            min_errors=settings.min_errors,
            min_total=settings.min_total,
            resolve_after_buckets=settings.resolve_after_buckets,
            thresholds=SeverityThresholds(
                warning=settings.threshold_warning,
                high=settings.threshold_high,
                critical=settings.threshold_critical,
            ),
        )


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
class DetectionResult:
    """Output of closing one bucket."""

    stats: StatsPoint
    alert_event: AlertEvent | None = None


def _new_alert_id() -> str:
    return uuid.uuid4().hex[:8]


class Detector:
    """Sliding window + robust baseline + incident state machine."""

    def __init__(
        self,
        config: DetectorConfig | None = None,
        id_factory: Callable[[], str] = _new_alert_id,
    ) -> None:
        self.config = config or DetectorConfig()
        self._id_factory = id_factory
        self._accumulator = BucketAccumulator()
        self._window = SlidingWindow(self.config.window_buckets)
        self._baseline = RobustBaseline(
            capacity=self.config.baseline_buckets,
            min_samples=self.config.baseline_min_buckets,
            mad_floor=self.config.mad_floor,
        )
        self._incident: Alert | None = None
        self._normal_streak = 0

    @property
    def open_incident(self) -> Alert | None:
        """The incident currently open, if any."""
        return self._incident

    @property
    def baseline_warm(self) -> bool:
        """Whether the baseline has enough history to score new buckets."""
        return self._baseline.is_warm

    def observe(self, event: LogEvent) -> None:
        """Count an event in the currently open bucket."""
        self._accumulator.add(event)

    def close_bucket(self, end: datetime) -> DetectionResult:
        """Close the open bucket at ``end``, score the window and advance the incident."""
        self._window.push(self._accumulator.close(end))
        # A window with no lines has no error rate (not 0%): nothing is scored,
        # nothing is learned, and the chart shows a gap.
        empty = self._window.total == 0
        rate = self._window.error_rate
        score = None if empty else self._baseline.score(rate)
        severity = classify(score, self.config.thresholds) if self._has_enough_data() else None

        stats = StatsPoint(
            ts=end,
            total=self._window.total,
            errors=self._window.errors,
            error_rate=None if empty else rate,
            baseline_median=self._baseline.median,
            band_upper=self._baseline.upper_band(self.config.thresholds.warning),
            score=score,
            severity=severity,
        )
        alert_event = self._advance_incident(end, severity, score, rate)

        learnable = self._window.is_full and not empty
        if self._incident is None and alert_event is None and learnable:
            self._baseline.update(rate)
        return DetectionResult(stats=stats, alert_event=alert_event)

    def _has_enough_data(self) -> bool:
        """Minimum-count guard: small samples produce extreme but meaningless rates."""
        return (
            self._window.errors >= self.config.min_errors
            and self._window.total >= self.config.min_total
        )

    def _advance_incident(
        self, now: datetime, severity: Severity | None, score: float | None, rate: float
    ) -> AlertEvent | None:
        if severity is None or score is None:
            return self._record_normal_bucket(now)
        self._normal_streak = 0
        if self._incident is None:
            return self._open_incident(now, severity, score, rate)
        return self._update_incident(now, severity, score, rate)

    def _open_incident(
        self, now: datetime, severity: Severity, score: float, rate: float
    ) -> AlertEvent:
        errors = list(self._window.error_events())
        self._incident = Alert(
            id=self._id_factory(),
            status="open",
            severity=severity,
            score=score,
            error_rate=rate,
            baseline_median=self._baseline.median or 0.0,
            opened_at=now,
            updated_at=now,
            summary=summarise(errors, self.config.window_seconds),
            top_contributors=top_contributors(errors, self.config.contributor_limit),
            sample_lines=sample_lines(errors, self.config.sample_line_limit),
        )
        return AlertEvent.snapshot(AlertChange.OPENED, self._incident)

    def _update_incident(
        self, now: datetime, severity: Severity, score: float, rate: float
    ) -> AlertEvent:
        incident = self._incident
        assert incident is not None
        change = AlertChange.UPDATED
        if severity.rank > incident.severity.rank:
            incident.severity = severity
            change = AlertChange.ESCALATED
        if score > incident.score:
            self._record_peak(incident, score, rate)
        incident.updated_at = now
        return AlertEvent.snapshot(change, incident)

    def _record_peak(self, incident: Alert, score: float, rate: float) -> None:
        """Refresh the figures and explanation at the worst point of the incident."""
        errors = list(self._window.error_events())
        incident.score = score
        incident.error_rate = rate
        incident.summary = summarise(errors, self.config.window_seconds)
        incident.top_contributors = top_contributors(errors, self.config.contributor_limit)
        incident.sample_lines = sample_lines(errors, self.config.sample_line_limit)

    def _record_normal_bucket(self, now: datetime) -> AlertEvent | None:
        if self._incident is None:
            return None
        self._normal_streak += 1
        if self._normal_streak < self.config.resolve_after_buckets:
            return None
        resolved = self._incident
        resolved.status = "resolved"
        resolved.resolved_at = now
        resolved.updated_at = now
        self._incident = None
        self._normal_streak = 0
        return AlertEvent.snapshot(AlertChange.RESOLVED, resolved)
