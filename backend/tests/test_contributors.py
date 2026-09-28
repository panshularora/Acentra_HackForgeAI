import pytest

from app.detection.contributors import (
    rank,
    sample_lines,
    summarise,
    top_contributors,
    top_params,
)
from app.models import LogEvent
from tests.factories import make_event


def db_outage_errors() -> list[LogEvent]:
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


def failed_login(ip: str = "10.4.2.17") -> LogEvent:
    return make_event(
        "ERROR",
        "member-auth",
        "login failed",
        source_ip=ip,
        http_status=401,
        params=(("source_ip", ip), ("req", "ab12")),
    )


def test_summary_names_service_and_message_for_service_outage() -> None:
    timeouts = db_outage_errors()[:47]

    summary = summarise(timeouts, error_count=50, window_seconds=60)

    assert summary == "94% of errors come from claim-adjudication: DB connection timeout"


def test_summary_names_ip_for_credential_stuffing() -> None:
    logins = [failed_login() for _ in range(312)]

    summary = summarise(logins, error_count=320, window_seconds=60)

    assert summary == "312 failed logins from 10.4.2.17 in the last 60s"


def test_summary_reads_the_ip_from_template_parameters_not_the_parser() -> None:
    logins = [
        make_event(
            "ERROR",
            "member-auth",
            "login failed",
            http_status=401,
            params=(("source_ip", "10.4.2.17"),),
        )
        for _ in range(10)
    ]

    assert summarise(logins, error_count=10, window_seconds=60) == (
        "10 failed logins from 10.4.2.17 in the last 60s"
    )


def test_summary_for_dominant_ip_without_auth_failures_uses_message() -> None:
    errors = [
        make_event(
            "ERROR",
            "provider-directory",
            "rate limited",
            http_status=429,
            params=(("source_ip", "10.9.9.9"),),
        )
        for _ in range(20)
    ]

    assert (
        summarise(errors, error_count=20, window_seconds=60)
        == "20 errors from 10.9.9.9 in the last 60s: rate limited"
    )


def test_summary_without_errors_is_generic() -> None:
    assert summarise([], error_count=0, window_seconds=60) == "Errors are above their normal range"


def test_ip_is_named_once_it_drives_forty_percent_of_the_template() -> None:
    logins = [failed_login() for _ in range(45)]
    logins += [failed_login(f"10.1.0.{n}") for n in range(55)]

    summary = summarise(logins, error_count=100, window_seconds=60)

    assert summary == "45 failed logins from 10.4.2.17 in the last 60s"


def test_ip_below_the_dominance_share_falls_back_to_service_summary() -> None:
    logins = [failed_login() for _ in range(30)]
    logins += [failed_login(f"10.1.0.{n}") for n in range(70)]

    summary = summarise(logins, error_count=200, window_seconds=60)

    assert summary == "50% of errors come from member-auth: login failed"


def test_top_params_keep_values_that_dominate_the_template() -> None:
    logins = [failed_login() for _ in range(8)]
    logins += [
        make_event("ERROR", params=(("source_ip", "10.1.0.1"), ("req", f"r{n}"))) for n in range(2)
    ]

    params = top_params(logins, limit=3)

    assert [(p.name, p.value, p.count) for p in params] == [
        ("req", "ab12", 8),
        ("source_ip", "10.4.2.17", 8),
    ]
    assert params[1].share == pytest.approx(0.8)


def test_top_params_drop_values_unique_to_each_line() -> None:
    events = [make_event("ERROR", params=(("req", f"r{n}"),)) for n in range(10)]

    assert top_params(events, limit=3) == []
    assert top_params([], limit=3) == []


def test_sample_lines_show_the_dominant_error_first_newest_first() -> None:
    def timeout(n: int) -> LogEvent:
        return make_event("ERROR", "claim-adjudication", "DB connection timeout", raw=f"t{n}")

    background = make_event("ERROR", "payment-gateway", "card declined", raw="declined")

    lines = sample_lines([timeout(0), timeout(1), background, timeout(2)], limit=3)

    assert lines == ["t2", "t1", "t0"]


def test_sample_lines_fill_up_with_other_errors() -> None:
    events = [make_event("ERROR", message="a"), make_event("ERROR", message="a")]
    events.append(make_event("ERROR", message="b"))

    assert len(sample_lines(events, limit=5)) == 3
    assert sample_lines([], limit=5) == []
