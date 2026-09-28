from datetime import UTC, datetime

import pytest

from app.ingest.parser import LogParser, parse_fields

LINE = (
    '2026-09-28T13:05:03.412Z ERROR claim-adjudication msg="DB connection timeout" '
    'member_id=M1234567 name="Rosa Diaz" ip=10.4.2.17 status=503 latency_ms=5012'
)


def test_parses_well_formed_line() -> None:
    event = LogParser().parse(LINE)

    assert event is not None
    assert event.ts == datetime(2026, 9, 28, 13, 5, 3, 412000, tzinfo=UTC)
    assert event.level == "ERROR"
    assert event.service == "claim-adjudication"
    assert event.message == "DB connection timeout"
    assert event.source_ip == "10.4.2.17"
    assert event.http_status == 503
    assert event.is_error


def test_raw_line_is_masked() -> None:
    event = LogParser().parse(LINE)

    assert event is not None
    assert "M1234567" not in event.raw
    assert "Rosa Diaz" not in event.raw
    assert "member_id=<MEMBER_ID>" in event.raw
    assert 'name="<NAME>"' in event.raw


def test_message_is_templated_for_grouping() -> None:
    line = (
        '2026-09-28T13:05:03Z ERROR eligibility-check msg="lookup failed for M7654321 after 812ms"'
    )

    event = LogParser().parse(line)

    assert event is not None
    assert event.message == "lookup failed for <MEMBER_ID> after <N>ms"


def test_message_falls_back_to_free_text_without_msg_field() -> None:
    event = LogParser().parse("2026-09-28T13:05:03Z WARN payment-gateway slow upstream status=200")

    assert event is not None
    assert event.message == "slow upstream"
    assert event.http_status == 200


@pytest.mark.parametrize(
    ("given", "expected"), [("warning", "WARN"), ("err", "ERROR"), ("Info", "INFO")]
)
def test_level_aliases_are_normalised(given: str, expected: str) -> None:
    event = LogParser().parse(f"2026-09-28T13:05:03Z {given} member-auth msg=ok")

    assert event is not None and event.level == expected


def test_naive_timestamp_is_treated_as_utc() -> None:
    event = LogParser().parse("2026-09-28T13:05:03 INFO member-auth msg=ok")

    assert event is not None and event.ts.tzinfo is UTC


@pytest.mark.parametrize(
    "line",
    [
        "not a log line",
        "2026-13-45T99:99:99Z ERROR svc msg=bad-date",
        "2026-09-28T13:05:03Z LOUD svc msg=unknown-level",
        "Traceback (most recent call last):",
    ],
)
def test_malformed_lines_are_counted_not_raised(line: str) -> None:
    parser = LogParser()

    assert parser.parse(line) is None
    assert (parser.parsed, parser.malformed) == (0, 1)


def test_blank_lines_are_ignored_silently() -> None:
    parser = LogParser()

    assert parser.parse("   \n") is None
    assert parser.malformed == 0


def test_non_numeric_status_is_ignored() -> None:
    event = LogParser().parse("2026-09-28T13:05:03Z ERROR svc msg=x status=abc")

    assert event is not None and event.http_status is None


def test_parse_fields_handles_quotes_and_escapes() -> None:
    fields = parse_fields(r'msg="said \"hi\"" a=1 b="two words"')

    assert fields == {"msg": 'said "hi"', "a": "1", "b": "two words"}
