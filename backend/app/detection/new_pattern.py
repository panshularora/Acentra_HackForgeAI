"""New-pattern detector: an ERROR/WARN template never seen in warm-up repeats.

error_spike already catches a brand-new failure that is loud enough to beat
the per-template MAD floor. This detector covers the quieter case: the same
unseen template appearing at least ``new_pattern_min_count`` times after the
baseline is ready, when error_spike did not already claim it.
"""

from collections import Counter, deque

from app.detection.config import DetectorConfig
from app.detection.incidents import Finding
from app.detection.templates import TemplateCatalog
from app.models import (
    BaselineBand,
    DetectorName,
    Explanation,
    LogEvent,
    Severity,
    TemplateRef,
)

NAME: DetectorName = "new_pattern"
_ERROR_LEVELS = frozenset({"ERROR", "WARN", "FATAL", "CRITICAL"})


class NewPatternDetector:
    """Alerts on ERROR/WARN templates that did not exist during warm-up."""

    def __init__(self, config: DetectorConfig) -> None:
        self.config = config
        self._known_ids: set[str] = set()
        self._known_texts: set[str] = set()
        self._current: Counter[str] = Counter()
        self._windows: deque[Counter[str]] = deque(maxlen=config.window_buckets)
        self._first_line: dict[str, str] = {}
        self._service: dict[str, str] = {}
        self._text: dict[str, str] = {}
        self._ready = False

    def observe(self, event: LogEvent) -> None:
        """Track templates. Warm-up sightings join the known set."""
        template_id = event.template_id
        if template_id is None:
            return
        text = event.message
        if not self._ready:
            self._known_ids.add(template_id)
            self._known_texts.add(text)
        if event.level not in _ERROR_LEVELS:
            return
        self._current[template_id] += 1
        self._first_line.setdefault(template_id, event.raw)
        self._service[template_id] = event.service
        self._text[template_id] = text

    def mark_ready(self) -> None:
        """Stop adding templates to the known set. Called once the global baseline is warm."""
        self._ready = True

    def close_bucket(self) -> None:
        """Slide the window of per-bucket counts, including empty buckets."""
        self._windows.append(self._current)
        self._current = Counter()

    def evaluate(
        self, catalog: TemplateCatalog, claimed_template_ids: set[str]
    ) -> list[Finding]:
        """Findings for unseen ERROR/WARN templates that error_spike did not already take."""
        if not self._ready:
            return []
        totals: Counter[str] = Counter()
        for bucket in self._windows:
            totals.update(bucket)
        findings: list[Finding] = []
        for template_id, count in totals.items():
            if count < self.config.new_pattern_min_count:
                continue
            if template_id in claimed_template_ids:
                continue
            text = catalog.text(template_id) or self._text.get(template_id, "")
            if template_id in self._known_ids or text in self._known_texts:
                continue
            severity = _severity(count)
            service = self._service.get(template_id)
            findings.append(
                Finding(
                    key=f"{NAME}:{template_id}",
                    severity=severity,
                    score=_score(count),
                    summary=f"new {severity.name.lower()} pattern on {service}: {text}",
                    explanation=Explanation(
                        detector=NAME,
                        template=TemplateRef(id=template_id, text=text, service=service),
                        baseline_band=BaselineBand(median=0.0, upper=0.0, unit="errors/60s"),
                        observed=float(count),
                        first_bad_line=self._first_line.get(template_id),
                    ),
                )
            )
        return findings


def _score(count: int) -> float:
    if count >= 10:
        return 8.0
    if count >= 5:
        return 5.0
    return 3.5


def _severity(count: int) -> Severity:
    if count >= 10:
        return Severity.CRITICAL
    if count >= 5:
        return Severity.HIGH
    return Severity.WARNING
