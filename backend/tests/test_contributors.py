import pytest

from app.detection.contributors import rank, summarise, top_contributors
from tests.factories import make_event


def db_outage_errors() -> list:
    errors = [make_event("ERROR", "claim-adjudication", "DB connection timeout") for _ in range(47)]
    errors += [make_event("ERROR", "eligibility-check", "upstream 502") for _ in range(3)]
    return errors


def test_rank_orders_by_count_and_computes_share() -> None:
    ranked = rank(["a", "b", "a", "a"], total=4, limit=2)

    assert [(c.value, c.count) for c in ranked] == [("a", 3), ("b", 1)]
    assert ranked[0].share == pytest.approx(0.75)


def test_rank_of_nothing_is_empty() -> None:
    assert rank([], total=0, limit=3) == []


def test_top_contributors_counts_each_dimension() -> None:
    top = top_contributors(db_outage_errors())

    assert top.services[0].value == "claim-adjudication"
    assert top.services[0].share == pytest.approx(0.94)
    assert top.messages[0].value == "DB connection timeout"
    assert top.source_ips == []


def test_source_ip_share_is_relative_to_all_errors() -> None:
    errors = [make_event("ERROR", source_ip="10.0.0.1") for _ in range(3)]
    errors.append(make_event("ERROR"))

    assert top_contributors(errors).source_ips[0].share == pytest.approx(0.75)


def test_summary_names_service_and_message_for_service_outage() -> None:
    summary = summarise(db_outage_errors(), window_seconds=60)

    assert summary == "94% of errors come from claim-adjudication: DB connection timeout"


def test_summary_names_ip_for_credential_stuffing() -> None:
    errors = [
        make_event("ERROR", "member-auth", "login failed", source_ip="10.4.2.17", http_status=401)
        for _ in range(312)
    ]
    errors += [make_event("ERROR", "payment-gateway", "card declined") for _ in range(8)]

    assert (
        summarise(errors, window_seconds=60) == "312 failed logins from 10.4.2.17 in the last 60s"
    )


def test_summary_for_dominant_ip_without_auth_failures_uses_message() -> None:
    errors = [
        make_event(
            "ERROR", "provider-directory", "rate limited", source_ip="10.9.9.9", http_status=429
        )
        for _ in range(20)
    ]

    assert (
        summarise(errors, window_seconds=60)
        == "20 errors from 10.9.9.9 in the last 60s: rate limited"
    )


def test_summary_without_errors_is_generic() -> None:
    assert summarise([], window_seconds=60) == "Error rate is above its normal range"
