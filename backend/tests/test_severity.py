import pytest

from app.detection.severity import SeverityThresholds, classify
from app.models import Severity

THRESHOLDS = SeverityThresholds(warning=3.5, high=5.0, critical=8.0)


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (None, None),
        (-12.0, None),
        (0.0, None),
        (3.49, None),
        (3.5, Severity.WARNING),
        (4.99, Severity.WARNING),
        (5.0, Severity.HIGH),
        (7.99, Severity.HIGH),
        (8.0, Severity.CRITICAL),
        (250.0, Severity.CRITICAL),
    ],
)
def test_classify_boundaries(score: float | None, expected: Severity | None) -> None:
    assert classify(score, THRESHOLDS) == expected


def test_thresholds_must_increase() -> None:
    with pytest.raises(ValueError):
        SeverityThresholds(warning=5.0, high=5.0, critical=8.0)


def test_severity_rank_orders_levels() -> None:
    assert Severity.WARNING.rank < Severity.HIGH.rank < Severity.CRITICAL.rank
