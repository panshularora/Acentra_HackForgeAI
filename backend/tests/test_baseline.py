import pytest

from app.detection.baseline import KeyedBaselines, RobustBaseline


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


def test_count_baselines_floor_mad_at_poisson_noise() -> None:
    baseline = RobustBaseline(capacity=30, min_samples=5, mad_floor=1.0, counts=True)
    for count in (36, 36, 37, 36, 36):
        baseline.update(count)

    # Raw MAD is 0 and the fixed floor is 1, but a count of 36 scatters by about 6.
    assert baseline.mad == pytest.approx(0.6745 * 6)
    assert baseline.score(57) == pytest.approx(21 / 6)


def test_count_floor_does_not_apply_to_rates() -> None:
    baseline = warm_baseline([0.02] * 10, floor=0.002)

    assert baseline.mad == 0.002


def test_history_prefills_the_baseline() -> None:
    baseline = RobustBaseline(capacity=3, min_samples=3, mad_floor=1.0, history=[0.0] * 5)

    assert baseline.sample_count == 3
    assert baseline.median == 0.0


def test_new_key_starts_from_a_history_of_zeros() -> None:
    bank = KeyedBaselines(capacity=30, min_samples=6, mad_floor=1.0, max_keys=10)

    baseline = bank.touch("7", history_length=12)

    assert baseline.is_warm
    assert baseline.median == 0.0
    assert baseline.score(6) == pytest.approx(0.6745 * 6)


def test_new_key_during_warm_up_waits_for_its_own_samples() -> None:
    bank = KeyedBaselines(capacity=30, min_samples=6, mad_floor=1.0, max_keys=10)

    assert not bank.touch("7", history_length=2).is_warm


def test_existing_key_keeps_its_history() -> None:
    bank = KeyedBaselines(capacity=30, min_samples=3, mad_floor=1.0, max_keys=10)
    bank.touch("7", history_length=3).update(9.0)

    assert bank.touch("7", history_length=3).sample_count == 4


def test_least_recently_touched_key_is_evicted_at_the_cap() -> None:
    bank = KeyedBaselines(capacity=30, min_samples=3, mad_floor=1.0, max_keys=2)
    bank.touch("a", 0)
    bank.touch("b", 0)
    bank.touch("a", 0)

    bank.touch("c", 0)

    assert bank.keys() == ["a", "c"]
    assert len(bank) == 2
    assert bank.get("b") is None


def test_key_cap_must_be_positive() -> None:
    with pytest.raises(ValueError):
        KeyedBaselines(capacity=30, min_samples=3, mad_floor=1.0, max_keys=0)
