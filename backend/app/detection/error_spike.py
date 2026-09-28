"""Error-spike detector: each template's error count against its own baseline.

Every closed bucket, the error lines in the sliding window are counted per
Drain3 template, and each count is scored with the modified z-score against
that template's rolling median and MAD (:class:`KeyedBaselines`). A template
is anomalous when:

* its baseline is warm (the detector has learned from ``baseline_min_buckets``
  windows; a template first seen after that starts from a history of zeros),
* the template has at least ``min_errors`` errors and the window at least
  ``min_total`` lines (small samples produce extreme but meaningless scores),
* and the score reaches the WARNING threshold.

Scoring per template means a new failure mode stands out on its own scale
instead of being diluted by, or hidden in, the background errors of every
other service.
"""

from app.detection.baseline import KeyedBaselines
from app.detection.config import DetectorConfig
from app.detection.contributors import sample_lines, summarise, top_contributors, top_params
from app.detection.incidents import Finding
from app.detection.severity import classify
from app.detection.templates import TemplateCatalog
from app.detection.window import SlidingWindow
from app.models import BaselineBand, DetectorName, Explanation, Severity, TemplateRef

NAME: DetectorName = "error_spike"


class ErrorSpikeDetector:
    """Per-template error counts scored against per-template robust baselines."""

    def __init__(self, config: DetectorConfig) -> None:
        self.config = config
        self._baselines = KeyedBaselines(
            capacity=config.baseline_buckets,
            min_samples=config.baseline_min_buckets,
            mad_floor=config.template_mad_floor,
            max_keys=config.max_templates,
        )

    @property
    def tracked_templates(self) -> int:
        """How many error templates currently have a baseline."""
        return len(self._baselines)

    def evaluate(
        self, window: SlidingWindow, catalog: TemplateCatalog, history_length: int
    ) -> list[Finding]:
        """Score every template with errors in ``window``; return the anomalous ones.

        ``history_length`` is how many windows the detector has learned from,
        used to give a template seen for the first time a matching history of
        zeros.
        """
        findings = []
        for template_id, count in window.template_errors().most_common():
            baseline = self._baselines.touch(template_id, history_length)
            score = baseline.score(count)
            guarded = count >= self.config.min_errors and window.total >= self.config.min_total
            severity = classify(score, self.config.thresholds) if guarded else None
            median = baseline.median
            upper = baseline.upper_band(self.config.thresholds.warning)
            if severity is None or score is None or median is None or upper is None:
                continue
            findings.append(
                self._finding(window, catalog, template_id, count, score, median, upper, severity)
            )
        return findings

    def learn(self, window: SlidingWindow) -> None:
        """Teach every tracked template its count in a window of normal operation."""
        counts = window.template_errors()
        for template_id, baseline in self._baselines.items():
            baseline.update(counts.get(template_id, 0))

    def _finding(
        self,
        window: SlidingWindow,
        catalog: TemplateCatalog,
        template_id: str,
        count: int,
        score: float,
        median: float,
        upper: float,
        severity: Severity,
    ) -> Finding:
        events = list(window.error_events(template_id))
        all_errors = list(window.error_events())
        # The window's count first exceeded the band at this line (oldest first).
        first_bad = events[min(int(upper), len(events) - 1)]
        template = TemplateRef(
            id=template_id,
            text=catalog.text(template_id) or first_bad.message,
            service=first_bad.service,
        )
        limit = self.config.contributor_limit
        return Finding(
            key=f"{NAME}:{template_id}",
            severity=severity,
            score=score,
            summary=summarise(events, len(all_errors), self.config.window_seconds),
            explanation=Explanation(
                detector=NAME,
                template=template,
                baseline_band=BaselineBand(
                    median=median, upper=upper, unit=f"errors/{self.config.window_seconds}s"
                ),
                observed=float(count),
                first_bad_line=first_bad.raw,
                params=top_params(events, limit),
            ),
            top_contributors=top_contributors(all_errors, limit),
            sample_lines=sample_lines(events, self.config.sample_line_limit),
        )
