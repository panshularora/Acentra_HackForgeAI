"""Replay a deterministic log through the real detector and score the result.

The scenario is 20 minutes of normal claims traffic with two incidents at
known times. Lines are generated with a fixed seed, parsed and masked by the
production parser, and fed to the production ``Detector``, with buckets closed
on the timestamps in the log instead of the wall clock. The report shows, for
each incident, how long detection took, and how many alerts fired outside any
incident (false alarms).

    python tools/replay.py                    # print the report
    python tools/replay.py --out logs/replay.log   # also keep the generated log
"""

from __future__ import annotations

import argparse
import math
import random
import sys
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import median

import loggen
from app.detection.detector import AlertChange, Detector, DetectorConfig
from app.ingest.parser import LogParser
from app.models import Alert, LogEvent

START = datetime(2026, 9, 28, 9, 0, 0, tzinfo=UTC)


@dataclass(frozen=True)
class ScheduledIncident:
    """An incident injected at ``start_s`` seconds into the scenario."""

    kind: str
    start_s: int
    duration_s: int


@dataclass(frozen=True)
class Scenario:
    """What to generate: background traffic plus scheduled incidents."""

    duration_s: int = 1200
    rate: float = loggen.DEFAULT_RATE
    error_rate: float = loggen.DEFAULT_ERROR_RATE
    seed: int = 2026
    incidents: tuple[ScheduledIncident, ...] = (
        ScheduledIncident("db-outage", start_s=480, duration_s=45),
        ScheduledIncident("cred-stuffing", start_s=840, duration_s=30),
    )


@dataclass
class IncidentResult:
    """How the detector handled one scheduled incident."""

    incident: ScheduledIncident
    alert: Alert | None = None
    peak: Alert | None = None

    @property
    def detected(self) -> bool:
        """Whether an alert opened for this incident."""
        return self.alert is not None

    @property
    def latency_s(self) -> float | None:
        """Seconds from incident start to the alert opening."""
        if self.alert is None:
            return None
        return (self.alert.opened_at - START).total_seconds() - self.incident.start_s


@dataclass
class ReplayReport:
    """Outcome of a replay run."""

    bucket_seconds: int
    results: list[IncidentResult]
    false_alarms: list[Alert] = field(default_factory=list)
    lines: int = 0

    def latency_buckets(self, result: IncidentResult) -> int | None:
        """Detection latency rounded up to whole buckets."""
        latency = result.latency_s
        return None if latency is None else math.ceil(latency / self.bucket_seconds)


def generate_log(scenario: Scenario) -> list[str]:
    """Every line of the scenario, in timestamp order."""
    factory = loggen.LineFactory(random.Random(scenario.seed))
    lines: list[str] = []
    for second in range(scenario.duration_s):
        start = START + timedelta(seconds=second)
        batch = list(
            loggen.normal_second(factory, start, second, scenario.rate, scenario.error_rate)
        )
        for incident in scenario.incidents:
            if incident.start_s <= second < incident.start_s + incident.duration_s:
                rate = loggen.INCIDENTS[incident.kind][1]
                batch.extend(loggen.incident_second(factory, incident.kind, start, rate))
        lines.extend(sorted(batch))  # lines start with their timestamp
    return lines


def run_detector(lines: list[str], config: DetectorConfig) -> tuple[list[Alert], dict[str, Alert]]:
    """Feed lines through the parser and detector on a simulated clock.

    Returns each alert as it was when it opened, and its final state by id.
    """
    parser = LogParser()
    detector = Detector(config)
    step = timedelta(seconds=config.bucket_seconds)
    boundary = START + step
    opened: list[Alert] = []
    final: dict[str, Alert] = {}

    def close_until(moment: datetime) -> None:
        nonlocal boundary
        while moment >= boundary:
            result = detector.close_bucket(boundary)
            for event in result.alert_events:
                final[event.alert.id] = event.alert
                if event.change is AlertChange.OPENED:
                    opened.append(event.alert)
            boundary += step

    for line in lines:
        event = parser.parse(line)
        if event is None:
            continue
        close_until(event.ts)
        detector.observe(event)
    close_until(boundary)
    return opened, final


def score(
    scenario: Scenario, alerts: list[Alert], final: dict[str, Alert], config: DetectorConfig
) -> ReplayReport:
    """Match opened alerts to incidents; anything unmatched is a false alarm."""
    results = [IncidentResult(incident) for incident in scenario.incidents]
    report = ReplayReport(bucket_seconds=config.bucket_seconds, results=results)
    for alert in alerts:
        offset = (alert.opened_at - START).total_seconds()
        match = next(
            (
                r
                for r in results
                if r.alert is None
                and r.incident.start_s <= offset <= r.incident.start_s + r.incident.duration_s
            ),
            None,
        )
        if match is None:
            report.false_alarms.append(alert)
        else:
            match.alert = alert
            match.peak = final[alert.id]
    return report


def replay(scenario: Scenario | None = None, config: DetectorConfig | None = None) -> ReplayReport:
    """Generate, detect and score in one call."""
    scenario = scenario or Scenario()
    config = config or DetectorConfig()
    lines = generate_log(scenario)
    opened, final = run_detector(lines, config)
    report = score(scenario, opened, final, config)
    report.lines = len(lines)
    return report


def format_report(report: ReplayReport) -> str:
    """Human-readable summary."""
    rows = [f"Replayed {report.lines} log lines ({report.bucket_seconds}s buckets)", ""]
    for result in report.results:
        incident = result.incident
        header = f"{incident.kind:<14} at +{incident.start_s}s for {incident.duration_s}s: "
        if result.alert is None or result.peak is None:
            rows.append(header + "NOT DETECTED")
            continue
        buckets = report.latency_buckets(result)
        plural = "" if buckets == 1 else "s"
        rows.append(
            header
            + f"detected after {result.latency_s:.0f}s ({buckets} bucket{plural}), "
            + f"opened {result.alert.severity.value}, peaked {result.peak.severity.value} "
            + f"(score {result.peak.score:.1f})"
        )
        rows.append(f"{'':16}{result.peak.summary}")
    rows += ["", f"False alarms outside incidents: {len(report.false_alarms)}"]
    return "\n".join(rows)


# The benchmark control: global error-rate alerting as it ran before
# template-aware detection. It is a frozen, self-contained copy of that
# decision rule (see git history of app/detection/detector.py before the
# Drain3 change), so the benchmark keeps comparing against the same baseline
# while the production detector evolves.


@dataclass(frozen=True)
class OpenedAlert:
    """An alert at the moment it opened: when, which detector and its one-line summary."""

    opened_at: datetime
    detector: str
    summary: str


@dataclass(frozen=True)
class GlobalRateConfig:
    """Settings of the control detector; the defaults are the pre-Drain3 production values."""

    window_buckets: int = 6
    bucket_seconds: int = 10
    baseline_buckets: int = 30
    baseline_min_buckets: int = 6
    mad_floor: float = 0.002
    min_errors: int = 5
    min_total: int = 50
    resolve_after_buckets: int = 3
    threshold: float = 3.5  # WARNING, the lowest severity that opens an incident


class GlobalErrorRateDetector:
    """One error rate for the whole log, scored against its own median and MAD.

    Errors divided by lines over the last ``window_buckets`` buckets gets a
    modified z-score against the last ``baseline_buckets`` normal window
    rates. A bucket is anomalous when the score reaches ``threshold`` and the
    window holds at least ``min_errors`` errors and ``min_total`` lines. The
    first anomalous bucket opens an incident, ``resolve_after_buckets``
    normal buckets resolve it, and the baseline only learns from buckets with
    no incident open and no incident change.
    """

    name = "global_error_rate"

    def __init__(self, config: GlobalRateConfig | None = None) -> None:
        self.config = config or GlobalRateConfig()
        self._window: deque[tuple[int, int]] = deque(maxlen=self.config.window_buckets)
        self._rates: deque[float] = deque(maxlen=self.config.baseline_buckets)
        self._total = 0
        self._errors = 0
        self._open = False
        self._normal_streak = 0

    def observe(self, event: LogEvent) -> None:
        """Count an event in the currently open bucket."""
        self._total += 1
        self._errors += event.is_error

    def close_bucket(self, end: datetime) -> list[OpenedAlert]:
        """Close the open bucket at ``end``; return the alert it opened, if any."""
        self._window.append((self._total, self._errors))
        self._total = self._errors = 0
        total = sum(t for t, _ in self._window)
        errors = sum(e for _, e in self._window)
        rate = errors / total if total else 0.0
        score = self._score(rate) if total else None
        anomalous = (
            score is not None
            and score >= self.config.threshold
            and errors >= self.config.min_errors
            and total >= self.config.min_total
        )

        opened: list[OpenedAlert] = []
        changed = anomalous
        if anomalous:
            self._normal_streak = 0
            if not self._open:
                self._open = True
                summary = f"error rate {rate:.1%} (modified z-score {score:.1f})"
                opened.append(OpenedAlert(end, self.name, summary))
        elif self._open:
            self._normal_streak += 1
            if self._normal_streak >= self.config.resolve_after_buckets:
                self._open, self._normal_streak, changed = False, 0, True

        learnable = len(self._window) == self.config.window_buckets and total > 0
        if learnable and not self._open and not changed:
            self._rates.append(rate)
        return opened

    def _score(self, rate: float) -> float | None:
        if len(self._rates) < self.config.baseline_min_buckets:
            return None
        centre = median(self._rates)
        spread = max(median(abs(r - centre) for r in self._rates), self.config.mad_floor)
        return MAD_SCALE * (rate - centre) / spread


# Scales MAD to the standard deviation of a normal distribution (1 / 1.4826).
MAD_SCALE = 0.6745


def main(argv: list[str] | None = None) -> int:
    """Entry point. Exits non-zero if an incident is missed or a false alarm fires."""
    parser = argparse.ArgumentParser(description="Replay a known scenario through the detector.")
    parser.add_argument("--seed", type=int, default=Scenario.seed)
    parser.add_argument("--out", type=Path, help="also write the generated log here")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    scenario = Scenario(seed=args.seed)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text("\n".join(generate_log(scenario)) + "\n")
    report = replay(scenario)
    print(format_report(report))
    ok = all(r.detected for r in report.results) and not report.false_alarms
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
