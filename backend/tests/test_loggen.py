import random
import re
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path

import pytest

import loggen
from app.ingest.parser import LogParser
from app.models import LogEvent

START = datetime(2026, 9, 28, 13, 0, 0, tzinfo=UTC)


def generate(seconds: int, rate: float = 40, error_rate: float = 0.02, seed: int = 7) -> list[str]:
    factory = loggen.LineFactory(random.Random(seed))
    lines: list[str] = []
    for second in range(seconds):
        start = START.replace(second=second % 60)
        lines.extend(loggen.normal_second(factory, start, float(second), rate, error_rate))
    return lines


def test_every_generated_line_parses() -> None:
    parser = LogParser()

    events = [parser.parse(line) for line in generate(30)]

    assert parser.malformed == 0
    assert {e.service for e in events if e} == {s.name for s in loggen.SERVICES}


def test_background_error_rate_is_close_to_requested() -> None:
    parser = LogParser()
    events = [parser.parse(line) for line in generate(120)]

    errors = sum(1 for e in events if e and e.is_error)

    assert 0.01 < errors / len(events) < 0.03


def test_output_is_reproducible_with_a_seed() -> None:
    assert generate(3, seed=42) == generate(3, seed=42)


def test_generated_phi_is_masked_by_the_parser() -> None:
    line = generate(1)[0]
    event = LogParser().parse(line)

    assert "member_id=M" in line and 'name="' in line
    assert event is not None
    assert "member_id=<MEMBER_ID>" in event.raw and 'name="<NAME>"' in event.raw


def test_db_outage_lines_are_claim_adjudication_timeouts() -> None:
    factory = loggen.LineFactory(random.Random(1))
    event = LogParser().parse(factory.incident("db-outage", START))

    assert event is not None
    assert (event.service, event.message, event.http_status) == (
        "claim-adjudication",
        "DB connection timeout",
        503,
    )


def test_cred_stuffing_lines_are_401s_from_one_ip() -> None:
    factory = loggen.LineFactory(random.Random(1))
    parser = LogParser()
    events = [parser.parse(factory.incident("cred-stuffing", START)) for _ in range(20)]

    assert {(e.source_ip, e.http_status) for e in events if e} == {(loggen.CRED_STUFFING_IP, 401)}
    assert all(e and "<EMAIL>" in e.raw for e in events)


def test_unknown_incident_is_rejected() -> None:
    with pytest.raises(ValueError):
        loggen.LineFactory(random.Random()).incident("meteor", START)


def test_cli_writes_incident_lines_to_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(loggen.time, "sleep", lambda _seconds: None)
    out = tmp_path / "logs" / "app.log"

    loggen.main(["--out", str(out), "--incident", "db-outage", "--duration", "2", "--seed", "3"])

    lines = out.read_text().splitlines()
    assert lines and all("DB connection timeout" in line for line in lines)


def test_timestamps_have_millisecond_precision() -> None:
    assert loggen.format_ts(START.replace(microsecond=412345)) == "2026-09-28T13:00:00.412Z"


# Heartbeats, claim flow and the new faults.

CLAIM_ID = re.compile(r"claim_id=(\S+)")


def simulate(
    seconds: int, faults: Sequence[loggen.ScheduledFault] = (), seed: int = 7
) -> list[str]:
    return loggen.simulate(START, seconds, faults, seed=seed)


def parse_all(lines: list[str]) -> list[LogEvent]:
    parser = LogParser()
    events = [parser.parse(line) for line in lines]
    assert parser.malformed == 0
    return [e for e in events if e is not None]


def offset(event: LogEvent) -> float:
    return (event.ts - START).total_seconds()


def heartbeats(events: list[LogEvent], service: str) -> list[float]:
    return [offset(e) for e in events if e.message == f"heartbeat service={service} ok"]


def claims(events: list[LogEvent], message: str) -> dict[str, float]:
    found: dict[str, float] = {}
    for e in events:
        match = CLAIM_ID.search(e.raw)
        if e.message == message and match:
            found[match[1]] = offset(e)
    return found


FAULT_WINDOW = (60, 30)  # start_s, duration_s used by the fault tests below


def in_window(seconds: float) -> bool:
    start, duration = FAULT_WINDOW
    return start <= seconds < start + duration


def with_fault(kind: str, seconds: int = 120) -> list[LogEvent]:
    return parse_all(simulate(seconds, [loggen.ScheduledFault(kind, *FAULT_WINDOW)]))


def test_simulated_lines_parse_are_ordered_and_mask_members() -> None:
    faults = [loggen.ScheduledFault(kind, 10, 20) for kind in loggen.FAULTS]
    lines = simulate(40, faults)

    events = parse_all(lines)

    assert lines == sorted(lines)
    assert {e.service for e in events} >= {"claim-intake", *loggen.HEARTBEAT_SERVICES}
    assert not any(re.search(r"\bM\d{7}\b", e.raw) for e in events)
    assert all("member_id=<MEMBER_ID>" in e.raw for e in events if "claim_id=" in e.raw)


def test_heartbeats_arrive_on_a_steady_cadence_per_service() -> None:
    events = parse_all(simulate(120))

    for service in loggen.HEARTBEAT_SERVICES:
        beats = heartbeats(events, service)
        gaps = [b - a for a, b in pairwise(beats)]
        assert len(beats) == 120 // loggen.HEARTBEAT_INTERVAL_SECONDS
        assert all(abs(gap - loggen.HEARTBEAT_INTERVAL_SECONDS) <= 0.1 for gap in gaps)


def test_most_validated_claims_are_adjudicated_shortly_after() -> None:
    events = parse_all(simulate(300))
    validated = claims(events, "claim validated")
    adjudicated = claims(events, "claim adjudicated")

    delays = [adjudicated[c] - validated[c] for c in adjudicated]

    assert adjudicated.keys() <= validated.keys()
    assert 0.95 < len(adjudicated) / len(validated) < 1.0
    low, high, _mode = loggen.ADJUDICATION_DELAY_SECONDS
    assert all(low <= delay <= high for delay in delays)


def test_claim_steps_share_the_same_member() -> None:
    factory = loggen.LineFactory(random.Random(3))
    member = factory.member()

    lines = [
        factory.claim_validated(START, "CLM-1", member),
        factory.claim_adjudicated(START, "CLM-1", member),
    ]

    assert all(f"member_id={member.member_id}" in line for line in lines)
    assert all(f'name="{member.name}"' in line for line in lines)


def test_heartbeat_stop_silences_one_service_only_during_the_fault() -> None:
    events = with_fault("heartbeat-stop")

    silenced = heartbeats(events, loggen.SILENCED_SERVICE)
    other = heartbeats(events, loggen.HEARTBEAT_SERVICES[1])

    assert silenced and not any(in_window(beat) for beat in silenced)
    assert max(silenced) > sum(FAULT_WINDOW)  # resumes afterwards
    assert any(in_window(beat) for beat in other)


def test_flow_break_stops_adjudication_but_not_validation() -> None:
    events = with_fault("flow-break")

    validated = claims(events, "claim validated").values()
    adjudicated = claims(events, "claim adjudicated").values()

    assert not any(in_window(ts) for ts in adjudicated)
    assert any(in_window(ts) for ts in validated)
    assert max(adjudicated) > sum(FAULT_WINDOW)


def test_new_error_is_unseen_before_the_fault_and_repeats_during_it() -> None:
    events = with_fault("new-error")

    tls = [e for e in events if "TLS certificate" in e.message]

    assert len(tls) >= 10 and all(in_window(offset(e)) for e in tls)
    assert {(e.level, e.service, e.http_status) for e in tls} == {("ERROR", "payment-gateway", 502)}


def test_existing_incidents_are_injectable_in_a_simulation() -> None:
    db = with_fault("db-outage")
    stuffing = with_fault("cred-stuffing")

    assert {in_window(offset(e)) for e in db if e.message == "DB connection timeout"} == {True}
    assert sum(1 for e in stuffing if e.source_ip == loggen.CRED_STUFFING_IP) > 100


def test_faults_change_only_their_own_lines() -> None:
    kinds = sorted(loggen.FAULTS)
    faults = [loggen.ScheduledFault(kind, 30 + 20 * i, 15) for i, kind in enumerate(kinds)]
    clean, faulty = set(simulate(150)), set(simulate(150, faults))

    removed = parse_all(sorted(clean - faulty))
    added = parse_all(sorted(faulty - clean))

    assert {e.message for e in removed} == {
        f"heartbeat service={loggen.SILENCED_SERVICE} ok",
        "claim adjudicated",
    }
    assert {e.message for e in added} == {
        "DB connection timeout",
        "login failed: invalid credentials",
        "TLS certificate verification failed for payer gateway",
    }


def test_simulation_is_reproducible_with_a_seed() -> None:
    faults = [loggen.ScheduledFault("new-error", 5, 5)]

    assert simulate(20, faults, seed=4) == simulate(20, faults, seed=4)
    assert simulate(20, faults, seed=4) != simulate(20, faults, seed=5)


def test_background_traffic_is_unchanged_by_the_extensions() -> None:
    factory = loggen.LineFactory(random.Random(7))
    background = [
        line
        for second in range(10)
        for line in loggen.normal_second(
            factory, START + timedelta(seconds=second), float(second), 40, 0.02
        )
    ]

    assert set(background) <= set(simulate(10))


def test_unknown_fault_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown fault"):
        loggen.Traffic(seed=1).second(START, 0.0, {"meteor"})


def test_control_file_round_trip(tmp_path: Path) -> None:
    control = loggen.control_path(tmp_path / "app.log")

    loggen.set_fault(control, "flow-break", until=100.0)
    loggen.set_fault(control, "heartbeat-stop", until=50.0)

    assert control.name == "app.log.faults.json"
    assert loggen.read_active_faults(control, now=75.0) == {"flow-break"}
    loggen.set_fault(control, "flow-break", until=None)
    assert loggen.read_active_faults(control, now=75.0) == frozenset()


@pytest.mark.parametrize("content", ["", "{not json", "[1, 2]", '{"flow-break": "soon"}'])
def test_unreadable_control_file_means_no_faults(tmp_path: Path, content: str) -> None:
    control = tmp_path / "app.log.faults.json"
    control.write_text(content)

    assert loggen.read_active_faults(control, now=0.0) == frozenset()


def test_cli_holds_a_suppression_fault_for_its_duration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "logs" / "app.log"
    control = loggen.control_path(out)
    seen: list[frozenset[str]] = []
    monkeypatch.setattr(
        loggen.time,
        "sleep",
        lambda _seconds: seen.append(loggen.read_active_faults(control, loggen.time.time())),
    )

    loggen.main(["--out", str(out), "--incident", "heartbeat-stop", "--duration", "30"])

    assert seen == [{"heartbeat-stop"}]
    assert loggen.read_active_faults(control, loggen.time.time()) == frozenset()
    assert not out.exists()  # a suppression writes no lines of its own


def test_cli_normal_traffic_applies_active_faults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(loggen.time, "sleep", lambda _seconds: None)
    clean, silenced = tmp_path / "clean.log", tmp_path / "silenced.log"
    loggen.set_fault(loggen.control_path(silenced), "heartbeat-stop", loggen.time.time() + 60)

    for out in (clean, silenced):
        loggen.main(["--out", str(out), "--duration", "1", "--seed", "3"])

    beat = f"heartbeat service={loggen.SILENCED_SERVICE} ok"
    assert beat in clean.read_text()
    assert beat not in silenced.read_text()
    assert "claim validated" in silenced.read_text()
