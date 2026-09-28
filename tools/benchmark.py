"""Benchmark the global error-rate control against the template-aware detector.

Both detectors see the same seeded stream from ``tools/loggen.py``: an hour of
normal claims traffic, heartbeats and claim flows, with the five faults
injected at known times and long normal stretches in between. The stream is
parsed and masked by the production parser once, and every event goes to both
detectors, with buckets closed on the log timestamps.

An alert that opens between a fault's start and ``GRACE_SECONDS`` after its
end is attributed to that fault; the first one sets the detection time. Any
other alert is a false alarm, counted per hour of the remaining normal
traffic (warm-up included). Detectors named in the contract but not built
into ``app.detection`` are reported as not implemented, never guessed.

    python tools/benchmark.py                     # print the table (5 seeds)
    python tools/benchmark.py --out-dir docs      # also write benchmark.md and benchmark.json

Every number in the output comes from running this script; nothing is
edited by hand.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any, Protocol

import loggen
from app.detection import detector as production
from app.ingest.parser import LogParser
from app.models import LogEvent
from replay import START, GlobalErrorRateDetector, OpenedAlert

BUCKET_SECONDS = 10
# Window-based detectors can only react once a fault has filled part of the
# 60 s window, so alerts up to one window after a fault ends still count.
GRACE_SECONDS = 60
DEFAULT_SEEDS = 5
FIRST_SEED = 2026
COMMAND = "make benchmark"

CONTRACT_DETECTORS = ("error_spike", "silence", "new_pattern", "flow_break")
# The template-aware detector expected to catch each fault; used only to say
# why a fault was missed.
EXPECTED_DETECTOR = {
    "db-outage": "error_spike",
    "cred-stuffing": "error_spike",
    "new-error": "new_pattern",
    "heartbeat-stop": "silence",
    "flow-break": "flow_break",
}


@dataclass(frozen=True)
class BenchmarkScenario:
    """The stream every detector sees: duration, traffic and scheduled faults."""

    duration_s: int = 3600
    rate: float = loggen.DEFAULT_RATE
    error_rate: float = loggen.DEFAULT_ERROR_RATE
    faults: tuple[loggen.ScheduledFault, ...] = (
        loggen.ScheduledFault("db-outage", start_s=600, duration_s=45),
        loggen.ScheduledFault("cred-stuffing", start_s=1140, duration_s=30),
        loggen.ScheduledFault("new-error", start_s=1680, duration_s=60),
        loggen.ScheduledFault("heartbeat-stop", start_s=2220, duration_s=90),
        loggen.ScheduledFault("flow-break", start_s=2760, duration_s=90),
    )

    def fault_at(self, offset_s: float) -> loggen.ScheduledFault | None:
        """The fault whose scoring window contains ``offset_s``, if any."""
        return next(
            (
                f
                for f in self.faults
                if f.start_s <= offset_s <= f.start_s + f.duration_s + GRACE_SECONDS
            ),
            None,
        )

    @property
    def normal_hours(self) -> float:
        """Hours of the stream outside every fault's scoring window."""
        scored = sum(f.duration_s + GRACE_SECONDS for f in self.faults)
        return (self.duration_s - scored) / 3600


class StreamDetector(Protocol):
    """What the benchmark needs from a detector."""

    name: str

    def observe(self, event: LogEvent) -> None:
        """Count one parsed event."""

    def close_bucket(self, end: datetime) -> list[OpenedAlert]:
        """Close the bucket ending at ``end``; return alerts that opened."""


def implemented_detectors() -> tuple[str, ...]:
    """Contract detectors that the production detector runs, in contract order.

    Before template-aware detection landed, ``app.detection.detector`` had no
    ``DETECTORS`` list and alerted on the global rate only, so nothing counts.
    """
    built = set(getattr(production, "DETECTORS", ()))
    return tuple(name for name in CONTRACT_DETECTORS if name in built)


class TemplateAwareDetector:
    """The production detector from ``app.detection`` with its default configuration."""

    name = "template_aware"

    def __init__(self) -> None:
        self._detector = production.Detector(production.DetectorConfig())

    def observe(self, event: LogEvent) -> None:
        """Pass the event to the production detector."""
        self._detector.observe(event)

    def close_bucket(self, end: datetime) -> list[OpenedAlert]:
        """Close the bucket and report each alert that opened, with its detector."""
        result = self._detector.close_bucket(end)
        # ``alert_events`` arrives with contract v2; the detector name is read
        # from the contract's JSON shape, where it is a top-level field.
        events = getattr(result, "alert_events", ())
        return [
            OpenedAlert(
                e.alert.opened_at,
                e.alert.to_dict().get("detector") or "unlabelled",
                e.alert.summary,
            )
            for e in events
            if e.change is production.AlertChange.OPENED
        ]


@dataclass
class FaultOutcome:
    """How one detector handled one fault in one seeded run."""

    fault: loggen.ScheduledFault
    alert: OpenedAlert | None = None

    @property
    def latency_s(self) -> float | None:
        """Seconds from fault start to the first attributed alert."""
        if self.alert is None:
            return None
        return (self.alert.opened_at - START).total_seconds() - self.fault.start_s


@dataclass
class RunResult:
    """One detector on one seed."""

    detector: str
    seed: int
    outcomes: list[FaultOutcome]
    false_alarms: list[OpenedAlert] = field(default_factory=list)


def run_seed(
    scenario: BenchmarkScenario,
    seed: int,
    factories: Sequence[Callable[[], StreamDetector]],
) -> tuple[int, list[RunResult]]:
    """Generate one seeded stream, feed it to fresh detectors and score each.

    Returns the number of lines and one result per detector.
    """
    lines = loggen.simulate(
        START,
        scenario.duration_s,
        scenario.faults,
        seed=seed,
        rate=scenario.rate,
        error_rate=scenario.error_rate,
    )
    detectors = [make() for make in factories]
    opened: dict[str, list[OpenedAlert]] = {d.name: [] for d in detectors}
    parser = LogParser()
    step = timedelta(seconds=BUCKET_SECONDS)
    boundary = START + step

    def close_until(moment: datetime) -> None:
        nonlocal boundary
        while moment >= boundary:
            for d in detectors:
                opened[d.name] += d.close_bucket(boundary)
            boundary += step

    for line in lines:
        event = parser.parse(line)
        if event is None:
            continue
        close_until(event.ts)
        for d in detectors:
            d.observe(event)
    close_until(START + timedelta(seconds=scenario.duration_s))
    return len(lines), [score(scenario, seed, d.name, opened[d.name]) for d in detectors]


def score(
    scenario: BenchmarkScenario, seed: int, detector: str, alerts: list[OpenedAlert]
) -> RunResult:
    """Attribute alerts to faults by time; the rest are false alarms."""
    outcomes = {f: FaultOutcome(f) for f in scenario.faults}
    result = RunResult(detector, seed, list(outcomes.values()))
    for alert in alerts:
        fault = scenario.fault_at((alert.opened_at - START).total_seconds())
        if fault is None:
            result.false_alarms.append(alert)
        elif outcomes[fault].alert is None:
            outcomes[fault].alert = alert
    return result


@dataclass
class Benchmark:
    """All runs, plus what was and was not implemented when they ran."""

    scenario: BenchmarkScenario
    seeds: list[int]
    lines: int
    implemented: tuple[str, ...]
    runs: list[RunResult]

    @property
    def detectors(self) -> list[str]:
        """Detector names in the order they ran."""
        return list(dict.fromkeys(r.detector for r in self.runs))

    def runs_for(self, detector: str) -> list[RunResult]:
        """Every seed's result for ``detector``."""
        return [r for r in self.runs if r.detector == detector]

    @property
    def label(self) -> str:
        """What the numbers were measured on, for quoting next to them."""
        minutes = self.scenario.duration_s // 60
        seeds = f"{len(self.seeds)} seed{'' if len(self.seeds) == 1 else 's'}"
        return (
            f"Measured on our synthetic Medicaid-style replay generated by tools/loggen.py: "
            f"{seeds} x {minutes}-minute streams, {self.lines:,} log lines in total, "
            f"{len(self.scenario.faults)} injected faults per stream. Not live-run timings."
        )


def run_benchmark(scenario: BenchmarkScenario, seeds: Sequence[int]) -> Benchmark:
    """Run the control, and the template-aware detector if any of it is built, on every seed."""
    implemented = implemented_detectors()
    factories: list[Callable[[], StreamDetector]] = [GlobalErrorRateDetector]
    if implemented:
        factories.append(TemplateAwareDetector)
    total_lines = 0
    runs: list[RunResult] = []
    for seed in seeds:
        lines, results = run_seed(scenario, seed, factories)
        total_lines += lines
        runs += results
    return Benchmark(scenario, list(seeds), total_lines, implemented, runs)


def fault_summary(bench: Benchmark, detector: str, fault: loggen.ScheduledFault) -> dict[str, Any]:
    """Detection count, latency statistics and per-seed detail for one detector and fault."""
    outcomes = [
        next(o for o in run.outcomes if o.fault == fault) for run in bench.runs_for(detector)
    ]
    latencies = [o.latency_s for o in outcomes if o.latency_s is not None]
    return {
        "fault": fault.kind,
        "detector": detector,
        "implemented": True,
        "detected": len(latencies),
        "runs": len(outcomes),
        "latency_s": (
            {"median": median(latencies), "min": min(latencies), "max": max(latencies)}
            if latencies
            else None
        ),
        "fired_by": sorted({o.alert.detector for o in outcomes if o.alert is not None}),
        "per_seed": [
            {
                "seed": run.seed,
                "detected": o.alert is not None,
                "latency_s": o.latency_s,
                "fired_by": o.alert.detector if o.alert else None,
                "summary": o.alert.summary if o.alert else None,
            }
            for run, o in zip(bench.runs_for(detector), outcomes, strict=True)
        ],
    }


def false_alarm_summary(bench: Benchmark, detector: str) -> dict[str, Any]:
    """False alarms per hour of normal traffic, over all seeds."""
    runs = bench.runs_for(detector)
    hours = bench.scenario.normal_hours * len(runs)
    count = sum(len(r.false_alarms) for r in runs)
    return {
        "count": count,
        "normal_hours": round(hours, 3),
        "per_hour": round(count / hours, 3),
        "per_seed": [
            {
                "seed": r.seed,
                "count": len(r.false_alarms),
                "alerts": [
                    {
                        "offset_s": (a.opened_at - START).total_seconds(),
                        "fired_by": a.detector,
                        "summary": a.summary,
                    }
                    for a in r.false_alarms
                ],
            }
            for r in runs
        ],
    }


def to_json(bench: Benchmark) -> dict[str, Any]:
    """The results file the deck reads."""
    missing = [d for d in CONTRACT_DETECTORS if d not in bench.implemented]
    template_aware_ran = TemplateAwareDetector.name in bench.detectors
    results = [
        fault_summary(bench, detector, fault)
        for fault in bench.scenario.faults
        for detector in bench.detectors
    ]
    if not template_aware_ran:
        results += [
            {"fault": f.kind, "detector": TemplateAwareDetector.name, "implemented": False}
            for f in bench.scenario.faults
        ]
    return {
        "label": bench.label,
        "command": COMMAND,
        "scenario": {
            "generator": "tools/loggen.py (loggen.simulate)",
            "duration_s": bench.scenario.duration_s,
            "lines_per_second": bench.scenario.rate,
            "background_error_rate": bench.scenario.error_rate,
            "seeds": bench.seeds,
            "lines_total": bench.lines,
            "bucket_seconds": BUCKET_SECONDS,
            "grace_seconds": GRACE_SECONDS,
            "normal_hours_per_seed": round(bench.scenario.normal_hours, 3),
            "faults": [
                {"kind": f.kind, "start_s": f.start_s, "duration_s": f.duration_s}
                for f in bench.scenario.faults
            ],
        },
        "detectors": {
            GlobalErrorRateDetector.name: {
                "role": "control",
                "description": "one global error rate, median + MAD baseline (pre-Drain3 rule)",
                "implemented": True,
            },
            TemplateAwareDetector.name: {
                "role": "candidate",
                "description": "app.detection.detector.Detector (Drain3 templates, contract v2)",
                "implemented": template_aware_ran,
                "components": list(bench.implemented),
                "not_implemented": missing,
            },
        },
        "results": results,
        "false_alarms": {d: false_alarm_summary(bench, d) for d in bench.detectors},
    }


def _cell(summary: dict[str, Any]) -> str:
    if not summary.get("implemented", True):
        return "not implemented"
    detected, runs = summary["detected"], summary["runs"]
    if not detected:
        return f"missed (0/{runs})"
    latency = summary["latency_s"]
    spread = (
        f"{latency['median']:.0f} s"
        if latency["min"] == latency["max"]
        else f"{latency['median']:.0f} s (range {latency['min']:.0f}-{latency['max']:.0f})"
    )
    if summary["detector"] == GlobalErrorRateDetector.name:
        return f"{detected}/{runs}, {spread}"
    return f"{detected}/{runs}, {spread}, {'/'.join(summary['fired_by'])}"


def format_table(data: dict[str, Any]) -> str:
    """Markdown table: one row per fault, one column per detector, then false alarms."""
    names = list(data["detectors"])
    header = ["Fault (start, duration)", *(f"`{n}`" for n in names)]
    rows = [header, ["---"] * len(header)]
    for fault in data["scenario"]["faults"]:
        cells = [f"`{fault['kind']}` (+{fault['start_s']} s, {fault['duration_s']} s)"]
        for name in names:
            summary = next(
                r for r in data["results"] if r["fault"] == fault["kind"] and r["detector"] == name
            )
            cell = _cell(summary)
            missing = data["detectors"][name].get("not_implemented", [])
            expected = EXPECTED_DETECTOR[fault["kind"]]
            if summary.get("implemented", True) and not summary["detected"] and expected in missing:
                cell += f"; `{expected}` not implemented"
            cells.append(cell)
        rows.append(cells)
    alarms = ["False alarms per hour of normal traffic"]
    for name in names:
        fa = data["false_alarms"].get(name)
        alarms.append(
            "not implemented"
            if fa is None
            else f"{fa['per_hour']:.2f} ({fa['count']} in {fa['normal_hours']:.1f} h)"
        )
    rows.append(alarms)
    return "\n".join("| " + " | ".join(r) + " |" for r in rows)


def format_markdown(data: dict[str, Any]) -> str:
    """The docs/benchmark.md page."""
    scenario = data["scenario"]
    candidate = data["detectors"][TemplateAwareDetector.name]
    built = ", ".join(f"`{d}`" for d in candidate["components"]) or "none"
    missing = ", ".join(f"`{d}`" for d in candidate["not_implemented"]) or "none"
    return f"""# Detection benchmark

{data["label"]}

Reproduce with `{data["command"]}` (runs `tools/benchmark.py --out-dir docs`). The
table below, [benchmark.json](benchmark.json) and this page are written by that
command; nothing is edited by hand.

## Results

Each cell: seeds detected / seeds run, then the median detection time from
fault start to the alert opening, with the range over seeds. For the
template-aware detector the detector that fired is named.

{format_table(data)}

## Setup

- Stream: {scenario["duration_s"] // 60} minutes per seed, about
  {scenario["lines_per_second"]:.0f} lines/s of background traffic
  ({scenario["background_error_rate"]:.0%} background errors) plus heartbeats
  and claim flows; seeds {", ".join(str(s) for s in scenario["seeds"])};
  {scenario["lines_total"]:,} lines in total.
- Faults: each seed has all five, at the offsets above, with at least eight
  minutes of normal traffic between them.
- Both detectors see the same parsed, masked events and close
  {scenario["bucket_seconds"]} s buckets on the log timestamps.
- An alert opening between a fault's start and {scenario["grace_seconds"]} s after
  its end counts for that fault; the first one sets the detection time. Every
  other alert is a false alarm, counted over the remaining
  {scenario["normal_hours_per_seed"]:.2f} h of normal traffic per seed (warm-up
  included).
- Control (`global_error_rate`): one error rate for the whole log, scored
  against its median and MAD, exactly the rule that alerted before
  template-aware detection (`GlobalErrorRateDetector` in `tools/replay.py`).
- Candidate (`template_aware`): the production `Detector` in
  `app/detection/detector.py`. Detectors built when this ran: {built}.
  Not implemented: {missing}.

These are replay measurements on synthetic data, not live-run timings; see
the README and the demo script for the live stack.
"""


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(description="Benchmark the detectors on seeded replays.")
    parser.add_argument("--seeds", type=int, default=DEFAULT_SEEDS, help="number of seeds")
    parser.add_argument("--first-seed", type=int, default=FIRST_SEED)
    parser.add_argument("--out-dir", type=Path, help="write benchmark.md and benchmark.json here")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    seeds = list(range(args.first_seed, args.first_seed + args.seeds))
    data = to_json(run_benchmark(BenchmarkScenario(), seeds))
    print(data["label"], "", format_table(data), sep="\n")
    if args.out_dir:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        (args.out_dir / "benchmark.md").write_text(format_markdown(data), encoding="utf-8")
        (args.out_dir / "benchmark.json").write_text(
            json.dumps(data, indent=2) + "\n", encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
