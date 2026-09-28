import pytest

from app.detection.baseline import RobustBaseline


def warm_baseline(rates: list[float], floor: float = 0.001) -> RobustBaseline:
    baseline = RobustBaseline(capacity=30, min_samples=len(rates), mad_floor=floor)
    for rate in rates:
        baseline.update(rate)
    return baseline


def test_no_score_until_warm() -> None:
    baseline = RobustBaseline(capacity=30, min_samples=3, mad_floor=0.001)
    baseline.update(0.02)
    baseline.update(0.02)

    assert not baseline.is_warm
    assert baseline.score(0.5) is None
    assert baseline.median is None
    assert baseline.upper_band(3.5) is None


def test_modified_z_score_matches_formula() -> None:
    baseline = warm_baseline([0.01, 0.02, 0.03, 0.02, 0.02])
    # median = 0.02, deviations = [0.01, 0, 0.01, 0, 0] -> MAD = 0.0

    assert baseline.median == pytest.approx(0.02)
    assert baseline.mad == pytest.approx(0.001)  # floored


def test_score_uses_real_mad_when_above_floor() -> None:
    baseline = warm_baseline([0.01, 0.02, 0.03, 0.04, 0.05])
    # median 0.03, deviations [0.02, 0.01, 0, 0.01, 0.02] -> MAD 0.01

    assert baseline.score(0.10) == pytest.approx(0.6745 * 0.07 / 0.01)


def test_zero_mad_is_clamped_to_floor_instead_of_dividing_by_zero() -> None:
    baseline = warm_baseline([0.02] * 10, floor=0.002)

    assert baseline.mad == 0.002
    assert baseline.score(0.02) == 0.0
    assert baseline.score(0.03) == pytest.approx(0.6745 * 0.01 / 0.002)


def test_score_is_negative_when_errors_drop() -> None:
    baseline = warm_baseline([0.02] * 10)

    score = baseline.score(0.0)

    assert score is not None and score < 0


def test_single_outlier_barely_moves_the_median() -> None:
    baseline = warm_baseline([0.02] * 9 + [0.9])

    assert baseline.median == pytest.approx(0.02)


def test_upper_band_is_where_score_reaches_threshold() -> None:
    baseline = warm_baseline([0.01, 0.02, 0.03, 0.04, 0.05])
    band = baseline.upper_band(3.5)

    assert band is not None
    assert baseline.score(band) == pytest.approx(3.5)


def test_capacity_drops_old_samples() -> None:
    baseline = RobustBaseline(capacity=3, min_samples=3, mad_floor=0.001)
    for rate in (0.5, 0.5, 0.5, 0.01, 0.01, 0.01):
        baseline.update(rate)

    assert baseline.sample_count == 3
    assert baseline.median == pytest.approx(0.01)


def test_min_samples_cannot_exceed_capacity() -> None:
    with pytest.raises(ValueError):
        RobustBaseline(capacity=3, min_samples=5, mad_floor=0.001)
