from app.detection.templates import TemplateCatalog, line_content
from app.ingest.masking import mask

LOGIN = (
    '2026-09-28T13:00:0{n}.000Z ERROR member-auth msg="login failed: invalid credentials" '
    "req=ab12cd{n} member_id=M123456{n} email=user{n}@example.com ip={ip} status=401"
)


def login(n: int, ip: str = "10.4.2.17") -> str:
    return mask(LOGIN.format(n=n, ip=ip))


def catalog() -> TemplateCatalog:
    return TemplateCatalog(max_templates=100, similarity=0.5)


def test_lines_of_the_same_shape_share_a_template() -> None:
    templates = catalog()

    ids = {templates.match(login(n)).id for n in range(5)}

    assert len(ids) == 1
    assert templates.count == 1


def test_varying_tokens_become_wildcards_in_the_template_text() -> None:
    templates = catalog()
    templates.match(login(1))

    match = templates.match(login(2))

    assert "<*>" in match.text
    assert "ab12cd" not in match.text
    assert templates.text(match.id) == match.text


def test_source_ip_is_a_named_parameter_even_when_it_never_varies() -> None:
    templates = catalog()

    matches = [templates.match(login(n)) for n in range(3)]

    assert all(("source_ip", "10.4.2.17") in m.params for m in matches)
    assert "ip=<IP>" in matches[-1].text


def test_whole_token_parameters_are_named_by_their_key() -> None:
    templates = catalog()
    templates.match(login(1))

    params = dict(templates.match(login(2)).params)

    assert params["req"] == "ab12cd2"


def test_different_services_or_levels_never_share_a_template() -> None:
    templates = catalog()
    base = '2026-09-28T13:00:00Z {level} {service} msg="request failed" status=500'

    ids = {
        templates.match(base.format(level=level, service=service)).id
        for level in ("ERROR", "WARN")
        for service in ("claim-adjudication", "payment-gateway")
    }

    assert len(ids) == 4


def test_masked_phi_never_reaches_template_text_or_parameters() -> None:
    templates = catalog()

    matches = [templates.match(login(n)) for n in range(3)]

    for match in matches:
        text = match.text + " ".join(value for _, value in match.params)
        assert "M123456" not in text
        assert "@example.com" not in text
    assert "<MEMBER_ID>" in matches[-1].text


def test_timestamp_is_not_part_of_the_mined_content() -> None:
    assert line_content("2026-09-28T13:00:00Z INFO svc msg=x") == "INFO svc msg=x"
    assert line_content("oneword") == "oneword"


def test_unknown_template_id_has_no_text() -> None:
    assert catalog().text("999") is None
