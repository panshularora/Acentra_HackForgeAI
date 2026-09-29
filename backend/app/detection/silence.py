"""Silence detector: a steady template has been missing for too long.

A template qualifies as steady when we have enough inter-arrival gaps and
their coefficient of variation is low (heartbeats). Bursty traffic never
qualifies, so a quiet error template does not look like a missing heartbeat.

Evaluated on every closed bucket, including empty ones: that is how a
service that stops logging is visible.
"""

from collections import deque
from dataclasses import dataclass
from datetime import datetime
from statistics import mean, pstdev

from app.detection.config import DetectorConfig
from app.detection.incidents import Finding
from app.detection.templates import TemplateCatalog
from app.models import BaselineBand, DetectorName, Explanation, LogEvent, Severity, TemplateRef

NAME: DetectorName = "silence"


@dataclass(slots=True)
class _TemplateCadence:
    """Gap history and last sighting for one template."""

    gaps: deque[float]
    last_seen: datetime
    last_line: str
    service: str
    text: str


class SilenceDetector:
    """Fires when a regular template is overdue."""

    def __init__(self, config: DetectorConfig) -> None:
        self.config = config
        self._templates: dict[str, _TemplateCadence] = {}

    def observe(self, event: LogEvent) -> None:
        """Record a sighting. Zero-length gaps (same timestamp in tests) are ignored."""
        template_id = event.template_id
        if template_id is None:
            return
        state = self._templates.get(template_id)
        if state is None:
            self._templates[template_id] = _TemplateCadence(
                gaps=deque(maxlen=self.config.silence_gap_history),
                last_seen=event.ts,
                last_line=event.raw,
                service=event.service,
                text=event.message,
            )
            return
        gap = (event.ts - state.last_seen).total_seconds()
        if gap >= 0.01:
            state.gaps.append(gap)
        state.last_seen = event.ts
        state.last_line = event.raw
        state.service = event.service
        state.text = event.message

    def evaluate(self, end: datetime, catalog: TemplateCatalog) -> list[Finding]:
        """Return a finding per overdue steady template."""
        findings: list[Finding] = []
        for template_id, state in self._templates.items():
            if len(state.gaps) < self.config.silence_min_gaps:
                continue
            median_gap = _median(state.gaps)
            if median_gap <= 0:
                continue
            if _cv(state.gaps) > self.config.silence_max_cv:
                continue
            threshold = max(
                self.config.silence_factor * median_gap, self.config.silence_min_seconds
            )
            observed = (end - state.last_seen).total_seconds()
            if observed < threshold:
                continue
            score = 3.5 * observed / threshold
            severity = _severity(score)
            text = catalog.text(template_id) or state.text
            findings.append(
                Finding(
                    key=f"{NAME}:{template_id}",
                    severity=severity,
                    score=score,
                    summary=(
                        f"{state.service} went silent: "
                        f"{text} last seen {observed:.0f}s ago "
                        f"(usual gap {median_gap:.1f}s)"
                    ),
                    explanation=Explanation(
                        detector=NAME,
                        template=TemplateRef(id=template_id, text=text, service=state.service),
                        baseline_band=BaselineBand(
                            median=median_gap, upper=threshold, unit="seconds between lines"
                        ),
                        observed=observed,
                        first_bad_line=None,
                    ),
                )
            )
        return findings


def _median(values: deque[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _cv(values: deque[float]) -> float:
    if len(values) < 2:
        return 0.0
    centre = mean(values)
    if centre <= 0:
        return 0.0
    return pstdev(values) / centre


def _severity(score: float) -> Severity:
    if score >= 8.0:
        return Severity.CRITICAL
    if score >= 5.0:
        return Severity.HIGH
    return Severity.WARNING
