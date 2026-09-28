from pathlib import Path

import pytest

import replay
from app.detection.detector import DetectorConfig


@pytest.fixture(scope="module")
def report() -> replay.ReplayReport:
    return replay.replay()


def test_every_incident_is_detected_within_two_buckets(report: replay.ReplayReport) -> None:
    for result in report.results:
        buckets = report.latency_buckets(result)
        assert buckets is not None, f"{result.incident.kind} was not detected"
        assert buckets <= 2, f"{result.incident.kind} took {buckets} buckets"


def test_no_false_alarms_during_normal_traffic(report: replay.ReplayReport) -> None:
    assert report.false_alarms == []


def test_incidents_are_explained_correctly(report: replay.ReplayReport) -> None:
    by_kind = {r.incident.kind: r.peak for r in report.results}

    db_outage, cred_stuffing = by_kind["db-outage"], by_kind["cred-stuffing"]
    assert db_outage is not None and cred_stuffing is not None
    assert "claim-adjudication: DB connection timeout" in db_outage.summary
    assert cred_stuffing.summary.endswith("failed logins from 10.4.2.17 in the last 60s")
    assert cred_stuffing.severity.value == "CRITICAL"


def test_credential_stuffing_names_the_ip_when_the_alert_opens(
    report: replay.ReplayReport,
) -> None:
    opened = {r.incident.kind: r.alert for r in report.results}["cred-stuffing"]

    assert opened is not None
    assert "failed logins from 10.4.2.17" in opened.summary


def test_scenario_is_deterministic() -> None:
    scenario = replay.Scenario(duration_s=30, incidents=())

    assert replay.generate_log(scenario) == replay.generate_log(scenario)


def test_quiet_scenario_raises_nothing() -> None:
    quiet = replay.replay(replay.Scenario(duration_s=600, incidents=(), seed=11))

    assert quiet.false_alarms == []


def test_cli_writes_log_and_exits_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "replay.log"

    exit_code = replay.main(["--out", str(out)])

    assert exit_code == 0
    assert out.read_text().count("\n") > 40_000
    assert "False alarms outside incidents: 0" in capsys.readouterr().out


def test_missed_incident_is_reported() -> None:
    blind = DetectorConfig(min_errors=10**6)

    report = replay.replay(config=blind)

    assert not any(r.detected for r in report.results)
    assert "NOT DETECTED" in replay.format_report(report)
