from app.detection.origin import suspected_origin


def test_lone_service_is_its_own_origin() -> None:
    assert suspected_origin("claim-adjudication", {"claim-adjudication"}) == "claim-adjudication"


def test_downstream_names_the_upstream_alerter() -> None:
    alerting = {"claim-adjudication", "payment-gateway"}
    assert suspected_origin("payment-gateway", alerting) == "claim-adjudication"
    assert suspected_origin("claim-adjudication", alerting) == "claim-adjudication"


def test_unknown_service_stays_itself() -> None:
    assert suspected_origin("member-auth", {"member-auth", "claim-adjudication"}) == "member-auth"
