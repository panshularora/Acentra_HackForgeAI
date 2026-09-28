import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

import benchmark
import loggen
import replay
from app.ingest.parser import LogParser

SHORT = benchmark.BenchmarkScenario(
    duration_s=600,
    faults=(
        loggen.ScheduledFault("db-outage", start_s=240, duration_s=45),
        loggen.ScheduledFault("heartbeat-stop", start_s=420, duration_s=60),
    ),
)


@pytest.fixture(scope="module")
def short_run() -> dict[str, Any]:
    return benchmark.to_json(benchmark.run_benchmark(SHORT, seeds=[1, 2]))


def result(data: dict[str, Any], fault: str, detector: str) -> dict[str, Any]:
    return next(r for r in data["results"] if r["fault"] == fault and r["detector"] == detector)


def test_benchmark_runs_on_a_short_stream(short_run: dict[str, Any]) -> None:
    control = result(short_run, "db-outage", "global_error_rate")

    assert short_run["scenario"]["seeds"] == [1, 2]
    assert short_run["scenario"]["lines_total"] > 2 * 600 * 40
    assert control["detected"] == 2 and control["runs"] == 2
    assert 0 < control["latency_s"]["max"] <= 45
    assert "global_error_rate" in short_run["false_alarms"]


def test_every_fault_has_a_result_for_every_detector(short_run: dict[str, Any]) -> None:
    for fault in SHORT.faults:
        for detector in short_run["detectors"]:
            assert result(short_run, fault.kind, detector)


def test_template_aware_components_are_reported_honestly(short_run: dict[str, Any]) -> None:
    candidate = short_run["detectors"]["template_aware"]

    assert candidate["components"] == list(benchmark.implemented_detectors())
    assert set(candidate["components"]) | set(candidate["not_implemented"]) == set(
        benchmark.CONTRACT_DETECTORS
    )
    if not candidate["implemented"]:
        assert result(short_run, "db-outage", "template_aware") == {
            "fault": "db-outage",
            "detector": "template_aware",
            "implemented": False,
        }
        assert "not implemented" in benchmark.format_table(short_run)


def test_label_names_the_synthetic_source_and_size(short_run: dict[str, Any]) -> None:
    label = short_run["label"]

    assert "synthetic" in label and "tools/loggen.py" in label
    assert "2 seeds x 10-minute streams" in label
    assert f"{short_run['scenario']['lines_total']:,} log lines" in label


def test_alerts_are_attributed_by_time() -> None:
    at = replay.START + timedelta(seconds=250)
    early = replay.START + timedelta(seconds=100)
    late = replay.START + timedelta(seconds=285 + benchmark.GRACE_SECONDS + 10)
    alerts = [replay.OpenedAlert(t, "x", "") for t in (early, at, late)]

    run = benchmark.score(SHORT, seed=0, detector="x", alerts=alerts)

    assert [o.latency_s for o in run.outcomes] == [10.0, None]
    assert [a.opened_at for a in run.false_alarms] == [early, late]


def test_normal_hours_exclude_fault_windows() -> None:
    scored = 45 + 60 + 2 * benchmark.GRACE_SECONDS

    assert SHORT.normal_hours == pytest.approx((600 - scored) / 3600)


def test_cli_writes_markdown_and_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(benchmark, "BenchmarkScenario", lambda: SHORT)

    assert benchmark.main(["--seeds", "1", "--first-seed", "5", "--out-dir", str(tmp_path)]) == 0

    data = json.loads((tmp_path / "benchmark.json").read_text())
    page = (tmp_path / "benchmark.md").read_text()
    printed = capsys.readouterr().out
    assert data["scenario"]["seeds"] == [5] and data["command"] == "make benchmark"
    assert benchmark.format_table(data) in page and benchmark.format_table(data) in printed
    assert data["label"] in page


def test_control_matches_the_pre_template_replay_results() -> None:
    """The control reproduces the published replay: +20 s and +10 s, no false alarms.

    These are the numbers the global-rate production detector produced on the
    default replay scenario before template-aware detection replaced it.
    """
    parser = LogParser()
    control = replay.GlobalErrorRateDetector()
    step = timedelta(seconds=control.config.bucket_seconds)
    boundary = replay.START + step
    opened: list[float] = []
    for line in replay.generate_log(replay.Scenario()):
        event = parser.parse(line)
        assert event is not None
        while event.ts >= boundary:
            opened += [
                (a.opened_at - replay.START).total_seconds() for a in control.close_bucket(boundary)
            ]
            boundary += step
        control.observe(event)

    assert opened == [480 + 20, 840 + 10]
