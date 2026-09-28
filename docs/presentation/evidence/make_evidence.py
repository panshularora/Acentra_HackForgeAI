"""Capture the real outputs the deck quotes, so every number can be traced.

Run from the repository root with the backend virtualenv:

    PYTHONPATH=backend:tools backend/.venv/bin/python docs/presentation/evidence/make_evidence.py

Writes, next to this file:

* ``replay.json``  - the replay benchmark (``tools/replay.py``) for the default
  seed and seeds 1-8: detection latency, severities and summaries per incident,
  false alarms per run.
* ``masking.txt``  - one credential-stuffing line from ``tools/loggen.py``
  (seed 7) before and after the production parser masks it.
* ``publisher.txt`` (with ``--sns``) - the default-seed db-outage alert, as the
  production detector opened it, published by the production ``AlertPublisher``
  to a moto server on :5000 (``make moto``). Start
  ``AWS_ENDPOINT_URL=http://localhost:5000 python tools/sns_tail.py --once > sns_tail.txt``
  first to read the message back through SNS -> SQS.
* ``tests.json`` (with ``--tests``) - pass counts from backend pytest and the
  frontend Vitest suite (needs Node 22 on PATH).

Finally it rewrites the ``facts`` section of ``../deck_data.json`` from these
files, which is the only place ``build_deck.py`` reads numbers from. Use
``--facts-only`` to refresh ``facts`` from the existing evidence files without
re-running anything (plain Python is enough for that).
"""

from __future__ import annotations

import argparse
import json
import random
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parents[2]
DECK_DATA = HERE.parent / "deck_data.json"
DEFAULT_SEED = 2026  # tools/replay.py Scenario.seed
SEEDS = (DEFAULT_SEED, 1, 2, 3, 4, 5, 6, 7, 8)


def replay_facts() -> None:
    import replay
    from app.detection.detector import DetectorConfig

    runs = []
    for seed in SEEDS:
        report = replay.replay(replay.Scenario(seed=seed), DetectorConfig())
        incidents = []
        for result in report.results:
            peak = result.peak
            incidents.append(
                {
                    "kind": result.incident.kind,
                    "start_s": result.incident.start_s,
                    "detected": result.detected,
                    "latency_s": result.latency_s,
                    "opened_severity": result.alert.severity.value if result.alert else None,
                    "opened_summary": result.alert.summary if result.alert else None,
                    "peak_severity": peak.severity.value if peak else None,
                    "peak_score": round(peak.score, 1) if peak else None,
                    "peak_error_rate": peak.error_rate if peak else None,
                    "peak_baseline_median": peak.baseline_median if peak else None,
                    "peak_summary": peak.summary if peak else None,
                }
            )
        runs.append(
            {
                "seed": seed,
                "lines": report.lines,
                "false_alarms": len(report.false_alarms),
                "incidents": incidents,
            }
        )
        print(f"seed {seed}: {[(i['kind'], i['latency_s']) for i in incidents]}")
    (HERE / "replay.json").write_text(json.dumps({"runs": runs}, indent=2) + "\n")


def masking_example() -> None:
    import loggen
    from app.ingest.parser import LogParser

    factory = loggen.LineFactory(random.Random(7))
    raw = factory.incident("cred-stuffing", datetime(2026, 9, 28, 9, 14, 3, 412000, tzinfo=UTC))
    event = LogParser().parse(raw)
    assert event is not None
    text = f"RAW    {raw}\nMASKED {event.raw}\n"
    (HERE / "masking.txt").write_text(text)
    print(text)


def publish_replay_alert() -> None:
    import replay
    from app.alerts.publisher import AlertPublisher
    from app.config import Settings
    from app.detection.detector import DetectorConfig

    report = replay.replay(replay.Scenario(), DetectorConfig())
    alert = next(r.alert for r in report.results if r.incident.kind == "db-outage")
    assert alert is not None
    publisher = AlertPublisher(Settings(aws_endpoint_url="http://localhost:5000"))
    publisher.ensure_resources()
    delivery = publisher.deliver(alert)
    out = {"alert_id": alert.id, "delivery": delivery.to_dict()}
    (HERE / "publisher.txt").write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))


def test_counts() -> None:
    backend = subprocess.run(
        [".venv/bin/pytest", "-q"], cwd=ROOT / "backend", capture_output=True, text=True
    ).stdout
    frontend = subprocess.run(
        ["npm", "test"], cwd=ROOT / "frontend", capture_output=True, text=True
    ).stdout
    backend_passed = re.findall(r"(\d+) passed", backend)
    frontend_passed = re.findall(r"Tests\s+(\d+) passed", re.sub(r"\x1b\[[0-9;]*m", "", frontend))
    counts = {
        "backend_pytest_passed": int(backend_passed[-1]) if backend_passed else None,
        "frontend_vitest_passed": int(frontend_passed[-1]) if frontend_passed else None,
    }
    (HERE / "tests.json").write_text(json.dumps(counts, indent=2) + "\n")
    print(counts)


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _incident_facts(inc: dict, seed: int, duration_s: int) -> dict[str, str]:
    return {
        "latency_s": f"{inc['latency_s']:.0f}",
        "buckets": f"{inc['latency_s'] / 10:.0f}",
        "opened_severity": inc["opened_severity"],
        "opened_summary": inc["opened_summary"],
        "peak_severity": inc["peak_severity"],
        "peak_score": f"{inc['peak_score']:.1f}",
        "peak_error_rate": _pct(inc["peak_error_rate"]),
        "baseline_median": _pct(inc["peak_baseline_median"]),
        "ratio": f"{inc['peak_error_rate'] / inc['peak_baseline_median']:.1f}",
        "peak_summary": inc["peak_summary"],
        "duration_s": str(duration_s),
        "seed": str(seed),
    }


def write_facts() -> None:
    """Derive every number the deck shows from the evidence files."""
    runs = json.loads((HERE / "replay.json").read_text())["runs"]
    tests = json.loads((HERE / "tests.json").read_text())
    masking = dict(
        line.split(" ", 1) for line in (HERE / "masking.txt").read_text().splitlines() if line
    )
    sns_lines = (HERE / "sns_tail.txt").read_text().splitlines()
    subject = next(line.split(": ", 1)[1] for line in sns_lines if line.startswith("Subject:"))
    sns_body = json.loads("\n".join(sns_lines[sns_lines.index("{") :]))
    publisher = json.loads((HERE / "publisher.txt").read_text())["delivery"]

    default = {i["kind"]: i for i in runs[0]["incidents"]}
    incidents = [i for r in runs for i in r["incidents"]]
    detected = [i for i in incidents if i["detected"]]
    latencies = sorted(i["latency_s"] for i in detected)
    attack = _incident_facts(default["cred-stuffing"], runs[0]["seed"], 30)
    attack["ip"] = re.search(r"\d+\.\d+\.\d+\.\d+", attack["peak_summary"]).group(0)

    def row(kind: str) -> list[str]:
        cells = []
        for run in runs:
            inc = next(i for i in run["incidents"] if i["kind"] == kind)
            cells.append(f"{inc['latency_s']:.0f} s" if inc["detected"] else "missed")
        return [kind, *cells]

    facts = {
        "outage": _incident_facts(default["db-outage"], runs[0]["seed"], 45),
        "attack": attack,
        "replay": {
            "runs": str(len(runs)),
            "incidents": str(len(incidents)),
            "detected": str(len(detected)),
            "latency_min": f"{latencies[0]:.0f}",
            "latency_max": f"{latencies[-1]:.0f}",
            "false_alarms": str(sum(r["false_alarms"] for r in runs)),
            "all_peaked": "CRITICAL"
            if all(i["peak_severity"] == "CRITICAL" for i in detected)
            else "mixed",
        },
        "replay_table": {
            "caption": "Detection latency per replay seed "
            "(tools/replay.py --seed N, 20-minute scenario each)",
            "header": ["Seed", *[str(r["seed"]) for r in runs]],
            "rows": [
                row("db-outage"),
                row("cred-stuffing"),
                ["False alarms", *[str(r["false_alarms"]) for r in runs]],
            ],
        },
        "tests": {
            "backend": str(tests["backend_pytest_passed"]),
            "frontend": str(tests["frontend_vitest_passed"]),
        },
        "masking": {"raw": masking["RAW"].strip(), "masked": masking["MASKED"].strip()},
        "sns": {
            "message_id": next(
                line.split()[-1] for line in sns_lines if line.startswith("SNS MessageId")
            ),
            "severity": subject[1 : subject.index("]")],
            "subject_rest": subject.split("] ", 1)[1],
            "sample_line": sns_body["sample_lines"][0],
            "publisher_line": f"sns {publisher['sns']['status']}, "
            f"id {publisher['sns']['message_id'][:8]}…; "
            f"cloudwatch {publisher['cloudwatch']['status']}",
        },
    }
    if len(detected) != len(incidents) or facts["replay"]["false_alarms"] != "0":
        print("WARNING: missed incidents or false alarms; review the results headline template")
    data = json.loads(DECK_DATA.read_text()) if DECK_DATA.exists() else {}
    data["facts"] = {**data.get("facts", {}), **facts}
    DECK_DATA.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print(f"facts written to {DECK_DATA}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--sns", action="store_true", help="publish to moto on :5000")
    parser.add_argument("--tests", action="store_true", help="run pytest and npm test")
    parser.add_argument("--facts-only", action="store_true", help="only refresh deck facts")
    args = parser.parse_args()
    if args.facts_only:
        write_facts()
        return
    replay_facts()
    masking_example()
    if args.sns:
        publish_replay_alert()
    if args.tests:
        test_counts()
    write_facts()


if __name__ == "__main__":
    main()
