import random
from datetime import UTC, datetime
from pathlib import Path

import pytest

import loggen
from app.ingest.parser import LogParser

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
