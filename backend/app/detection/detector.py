"""Turn a stream of log events into stats points and incident updates.

The detector is deliberately free of I/O: it knows nothing about files,
FastAPI or AWS, and time only moves when the caller closes a bucket. The live
pipeline closes buckets on a wall-clock timer; the replay tool closes them on
a simulated clock. Both get identical behaviour.

Per bucket
----------
* Every observed line is matched to a Drain3 template (``templates.py``).
* The global error rate over the window is scored against its own baseline
  for the chart (``StatsPoint``); it no longer raises alerts itself and
  remains the benchmark control.
* Each detector reports findings; :class:`IncidentTracker` turns them into
  one alert per incident key (detector + template id), updated in place.
* While any incident is open no baseline learns, so a long outage never
  teaches the detector that failing is normal.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime

from app.detection.baseline import RobustBaseline
from app.detection.config import DetectorConfig
from app.detection.error_spike import ErrorSpikeDetector
from app.detection.incidents import (
    AlertChange,
    AlertEvent,
    IncidentTracker,
    WindowContext,
)
from app.detection.templates import TemplateCatalog
from app.detection.window import BucketAccumulator, SlidingWindow
from app.models import Alert, DetectorName, LearningState, LogEvent, StatsPoint

__all__ = [
    "DETECTORS",
    "AlertChange",
    "AlertEvent",
    "DetectionResult",
    "Detector",
    "DetectorConfig",
]

# Detectors this build runs, in the order their findings are applied.
DETECTORS: tuple[DetectorName, ...] = ("error_spike",)


@dataclass(frozen=True, slots=True)
class DetectionResult:
    """Output of closing one bucket."""

    stats: StatsPoint
    alert_events: tuple[AlertEvent, ...] = ()


def _new_alert_id() -> str:
    return uuid.uuid4().hex[:8]


class Detector:
    """Template mining, sliding window, baselines, detectors and the incident tracker."""

    def __init__(
        self,
        config: DetectorConfig | None = None,
        id_factory: Callable[[], str] = _new_alert_id,
    ) -> None:
        self.config = config or DetectorConfig()
        self._catalog = TemplateCatalog(
            max_templates=self.config.max_templates, similarity=self.config.template_similarity
        )
        self._accumulator = BucketAccumulator()
        self._window = SlidingWindow(self.config.window_buckets)
        self._rate_baseline = RobustBaseline(
            capacity=self.config.baseline_buckets,
            min_samples=self.config.baseline_min_buckets,
            mad_floor=self.config.mad_floor,
        )
        self._error_spike = ErrorSpikeDetector(self.config)
        self._incidents = IncidentTracker(self.config.resolve_after_buckets, id_factory)

    @property
    def open_incidents(self) -> list[Alert]:
        """Incidents currently open, oldest first."""
        return self._incidents.open_incidents

    @property
    def baseline_warm(self) -> bool:
        """Whether the baselines have enough history to score new buckets."""
        return self._rate_baseline.is_warm

    @property
    def learning(self) -> LearningState:
        """Warm-up progress, and how many distinct templates have been seen."""
        return LearningState(
            state="ready" if self.baseline_warm else "learning",
            buckets_seen=self._rate_baseline.sample_count,
            buckets_needed=self.config.baseline_min_buckets,
            templates=self._catalog.count,
        )

    def observe(self, event: LogEvent) -> None:
        """Match an event to its template and count it in the currently open bucket."""
        match = self._catalog.match(event.raw)
        self._accumulator.add(replace(event, template_id=match.id, params=match.params))

    def close_bucket(self, end: datetime) -> DetectionResult:
        """Close the open bucket at ``end``, run the detectors and advance incidents."""
        self._window.push(self._accumulator.close(end))
        # A window with no lines has no error rate (not 0%): nothing is scored,
        # nothing is learned, and the chart shows a gap.
        empty = self._window.total == 0
        rate = self._window.error_rate
        history = self._rate_baseline.sample_count

        findings = [] if empty else self._error_spike.evaluate(self._window, self._catalog, history)
        severity = max((f.severity for f in findings), key=lambda s: s.rank, default=None)
        context = WindowContext(error_rate=rate, baseline_median=self._rate_baseline.median or 0.0)
        events = self._incidents.advance(end, findings, context)

        stats = StatsPoint(
            ts=end,
            total=self._window.total,
            errors=self._window.errors,
            error_rate=None if empty else rate,
            baseline_median=self._rate_baseline.median,
            band_upper=self._rate_baseline.upper_band(self.config.thresholds.warning),
            score=None if empty else self._rate_baseline.score(rate),
            severity=severity,
            learning=self.learning,
        )

        learnable = self._window.is_full and not empty
        if learnable and not events and not self.open_incidents:
            self._rate_baseline.update(rate)
            self._error_spike.learn(self._window)
        return DetectionResult(stats=stats, alert_events=tuple(events))
