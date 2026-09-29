"""Flow-break detector: validated claims stop being adjudicated.

Pairs ``claim validated`` with ``claim adjudicated`` on ``claim_id``. A claim
still pending after ``flow_timeout_seconds`` is incomplete. Incomplete counts
over the sliding window are scored with the same robust baseline as error
spikes; loggen leaves about 2% of claims incomplete, so the baseline is not
zero.
"""

import re
from collections import OrderedDict, deque
from datetime import datetime

from app.detection.baseline import RobustBaseline
from app.detection.config import DetectorConfig
from app.detection.incidents import Finding
from app.detection.severity import classify
from app.models import BaselineBand, DetectorName, Explanation, LogEvent, TemplateRef

NAME: DetectorName = "flow_break"
_CLAIM_ID = re.compile(r"claim_id=(\S+)")
KEY = f"{NAME}:claim_flow"


class FlowBreakDetector:
    """Incomplete claim-flow counts against a robust baseline."""

    def __init__(self, config: DetectorConfig) -> None:
        self.config = config
        self._pending: OrderedDict[str, tuple[float, LogEvent]] = OrderedDict()
        self._window: deque[int] = deque(maxlen=config.window_buckets)
        self._baseline = RobustBaseline(
            capacity=config.baseline_buckets,
            min_samples=config.baseline_min_buckets,
            mad_floor=config.template_mad_floor,
            counts=True,
        )
        self._last_validated: LogEvent | None = None

    def observe(self, event: LogEvent) -> None:
        """Track validations and adjudications by claim_id."""
        claim_id = _claim_id(event)
        if claim_id is None:
            return
        message = event.message.lower()
        if "claim validated" in message:
            self._pending[claim_id] = (event.ts.timestamp(), event)
            self._last_validated = event
            if len(self._pending) > self.config.flow_map_cap:
                self._pending.popitem(last=False)
        elif "claim adjudicated" in message:
            self._pending.pop(claim_id, None)

    def evaluate(self, end: datetime) -> list[Finding]:
        """Time out overdue claims, score the window, return a finding if anomalous."""
        deadline = end.timestamp() - self.config.flow_timeout_seconds
        timed_out = 0
        first_bad: LogEvent | None = None
        for claim_id, (started, event) in list(self._pending.items()):
            if started <= deadline:
                timed_out += 1
                if first_bad is None:
                    first_bad = event
                del self._pending[claim_id]
        self._window.append(timed_out)
        incomplete = sum(self._window)
        score = self._baseline.score(float(incomplete))
        median = self._baseline.median
        upper = self._baseline.upper_band(self.config.thresholds.warning)
        severity = classify(score, self.config.thresholds)
        if (
            severity is None
            or score is None
            or median is None
            or upper is None
            or not self._window.maxlen
            or len(self._window) < self._window.maxlen
        ):
            return []
        sample = first_bad or self._last_validated
        text = "claim validated → claim adjudicated"
        service = sample.service if sample is not None else "claim-intake"
        return [
            Finding(
                key=KEY,
                severity=severity,
                score=score,
                summary=(
                    f"{incomplete} claims validated without adjudication "
                    f"in {self.config.window_seconds}s "
                    f"(normal {median:.0f})"
                ),
                explanation=Explanation(
                    detector=NAME,
                    template=TemplateRef(id="claim_flow", text=text, service=service),
                    baseline_band=BaselineBand(
                        median=median, upper=upper, unit="incomplete flows/60s"
                    ),
                    observed=float(incomplete),
                    first_bad_line=sample.raw if sample is not None else None,
                    params=[],
                ),
            )
        ]

    def learn(self) -> None:
        """Teach the baseline the incomplete count of a normal full window."""
        if len(self._window) < (self._window.maxlen or 0):
            return
        self._baseline.update(float(sum(self._window)))


def _claim_id(event: LogEvent) -> str | None:
    for name, value in event.params:
        if name == "claim_id":
            return value
    match = _CLAIM_ID.search(event.raw)
    return match.group(1) if match else None
