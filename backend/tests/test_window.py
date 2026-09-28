from datetime import timedelta

import pytest

from app.detection.window import Bucket, BucketAccumulator, SlidingWindow
from tests.factories import T0, make_event


def bucket(total: int, errors: int, offset: int = 0) -> Bucket:
    return Bucket(end=T0 + timedelta(seconds=offset), total=total, errors=errors)


def test_accumulator_counts_totals_and_keeps_only_error_events() -> None:
    acc = BucketAccumulator()
    for _ in range(8):
        acc.add(make_event("INFO"))
    acc.add(make_event("ERROR"))
    acc.add(make_event("WARN"))

    closed = acc.close(T0)

    assert (closed.total, closed.errors) == (10, 1)
    assert [e.level for e in closed.error_events] == ["ERROR"]


def test_accumulator_starts_empty_after_close() -> None:
    acc = BucketAccumulator()
    acc.add(make_event("ERROR"))
    acc.close(T0)

    assert acc.close(T0).total == 0


def test_window_rate_covers_all_buckets() -> None:
    window = SlidingWindow(bucket_count=3)
    window.push(bucket(100, 2))
    window.push(bucket(100, 4))

    assert window.total == 200
    assert window.errors == 6
    assert window.error_rate == pytest.approx(0.03)
    assert not window.is_full


def test_window_evicts_oldest_bucket_on_rollover() -> None:
    window = SlidingWindow(bucket_count=2)
    window.push(bucket(100, 50))
    window.push(bucket(100, 0))
    window.push(bucket(100, 0))

    assert window.is_full
    assert window.errors == 0
    assert window.total == 200


def test_empty_window_has_zero_rate() -> None:
    assert SlidingWindow(bucket_count=6).error_rate == 0.0


def test_window_rejects_zero_buckets() -> None:
    with pytest.raises(ValueError):
        SlidingWindow(bucket_count=0)


def test_error_events_are_yielded_oldest_first() -> None:
    window = SlidingWindow(bucket_count=2)
    first, second = make_event("ERROR", service="a"), make_event("ERROR", service="b")
    window.push(Bucket(end=T0, total=1, errors=1, error_events=[first]))
    window.push(Bucket(end=T0, total=1, errors=1, error_events=[second]))

    assert [e.service for e in window.error_events()] == ["a", "b"]


def test_window_counts_errors_per_template() -> None:
    window = SlidingWindow(2)
    for templates in (["1", "1", "2"], ["1"], ["2"]):
        acc = BucketAccumulator()
        for template_id in templates:
            acc.add(make_event("ERROR", template_id=template_id))
        acc.add(make_event("INFO", template_id="3"))
        window.push(acc.close(T0))

    assert window.template_errors() == {"1": 1, "2": 1}
    assert [e.template_id for e in window.error_events("2")] == ["2"]
    assert len(list(window.error_events())) == 2
