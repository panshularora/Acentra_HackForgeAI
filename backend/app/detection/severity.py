"""Map a modified z-score to a severity level.

WARNING starts at 3.5, the outlier cut-off recommended by Iglewicz and
Hoaglin. HIGH (5) and CRITICAL (8) are our own escalation points, chosen so a
clear outage lands in HIGH and a runaway failure or attack lands in CRITICAL.
All three are configurable.
"""

from dataclasses import dataclass

from app.models import Severity


@dataclass(frozen=True, slots=True)
class SeverityThresholds:
    """Minimum score for each severity level."""

    warning: float = 3.5
    high: float = 5.0
    critical: float = 8.0

    def __post_init__(self) -> None:
        if not self.warning < self.high < self.critical:
            raise ValueError("thresholds must satisfy warning < high < critical")


def classify(score: float | None, thresholds: SeverityThresholds) -> Severity | None:
    """Return the severity for ``score``, or None when it is within normal range."""
    if score is None or score < thresholds.warning:
        return None
    if score >= thresholds.critical:
        return Severity.CRITICAL
    if score >= thresholds.high:
        return Severity.HIGH
    return Severity.WARNING
