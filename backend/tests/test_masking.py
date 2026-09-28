import pytest

from app.ingest.masking import mask, message_template


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("lookup failed for member M1234567", "lookup failed for member <MEMBER_ID>"),
        ("member_id=M7654321 status=500", "member_id=<MEMBER_ID> status=500"),
        ("member_id=ABC-99 status=500", "member_id=<MEMBER_ID> status=500"),
        ('user name="Maria Lopez" ok', 'user name="<NAME>" ok'),
        ("user name=Maria ok", "user name=<NAME> ok"),
        ("contact jane.doe+claims@example.org now", "contact <EMAIL> now"),
        ("ssn 123-45-6789 on file", "ssn <SSN> on file"),
        ("call (555) 123-4567 or 555-987-6543", "call <PHONE> or <PHONE>"),
        ("call +1 555 123 4567", "call <PHONE>"),
        ("dob=1984-02-11 plan=CHIP", "dob=<DOB> plan=CHIP"),
    ],
)
def test_mask_replaces_phi(raw: str, expected: str) -> None:
    assert mask(raw) == expected


def test_mask_leaves_operational_fields_alone() -> None:
    line = "2026-09-28T13:05:03Z ERROR claim-adjudication ip=10.4.2.17 status=503 latency_ms=5012"

    assert mask(line) == line


def test_mask_is_idempotent() -> None:
    once = mask('member_id=M1234567 name="Ana Ruiz" email=a@b.io ssn=123-45-6789')

    assert mask(once) == once


def test_mask_handles_several_identifiers_in_one_line() -> None:
    masked = mask('name="Li Wei" member_id=M1111111 email=li@example.com phone=555-222-3333')

    assert "Li Wei" not in masked
    assert "M1111111" not in masked
    assert "li@example.com" not in masked
    assert "555-222-3333" not in masked


def test_message_template_groups_errors_that_differ_only_in_numbers() -> None:
    first = message_template("DB connection timeout after 5012ms for member M1234567")
    second = message_template("DB connection timeout after 4980ms for member M7654321")

    assert first == second == "DB connection timeout after <N>ms for member <MEMBER_ID>"


def test_message_template_keeps_ip_addresses_intact() -> None:
    assert message_template("login failed from 10.4.2.17") == "login failed from 10.4.2.17"
