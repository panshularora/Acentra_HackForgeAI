"""Robust baseline of a "normal" value, and how far a new value is from it.

We use the modified z-score of Iglewicz and Hoaglin (1993, "How to Detect and
Handle Outliers"):

    score = 0.6745 * (value - median) / MAD

where MAD is the median absolute deviation of recent values from their median.
Median and MAD are used instead of mean and standard deviation because a few
extreme values barely move them, so one past spike does not inflate what we
consider normal. The constant 0.6745 rescales MAD so the score is comparable
to an ordinary z-score for normally distributed data.

The same maths scores every signal in the detector: the global error rate
(for the chart) and each template's error count per window (for alerting), so
it lives in one class that does not care about units.

Two practical adjustments:

* MAD floor: a very steady signal can have a MAD close to zero, which would
  make every tiny wobble look infinitely significant. MAD is clamped to at
  least ``mad_floor``.
* Counting noise: when the values are event counts (``counts=True``), MAD is
  also floored at the MAD of a Poisson count with the same median,
  0.6745 * sqrt(median). Random arrivals alone scatter a count that much, and
  consecutive sliding windows share most of their lines, so the MAD measured
  over them understates that scatter; without this floor ordinary Poisson
  noise in a busy template scores as an outlier.
* Warm-up: no score is produced until ``min_samples`` values have been seen.

The baseline does not decide when to learn; the detector stops calling
:meth:`RobustBaseline.update` while an incident is open, so an outage never
becomes the new normal.
"""

from collections import OrderedDict, deque
from collections.abc import Iterable, Iterator
from math import sqrt
from statistics import median

# Scales MAD to the standard deviation of a normal distribution (1 / 1.4826).
MAD_SCALE = 0.6745


class RobustBaseline:
    """Rolling median and MAD over the most recent values of one signal."""

    def __init__(
        self,
        capacity: int,
        min_samples: int,
        mad_floor: float,
        history: Iterable[float] = (),
        counts: bool = False,
    ) -> None:
        if min_samples > capacity:
            raise ValueError("min_samples cannot exceed capacity")
        self._values: deque[float] = deque(history, maxlen=capacity)
        self._min_samples = min_samples
        self._mad_floor = mad_floor
        self._counts = counts

    def update(self, value: float) -> None:
        """Record a value observed during normal operation."""
        self._values.append(value)

    @property
    def sample_count(self) -> int:
        """How many values the baseline currently holds."""
        return len(self._values)

    @property
    def is_warm(self) -> bool:
        """True once enough samples exist to trust the baseline."""
        return len(self._values) >= self._min_samples

    @property
    def median(self) -> float | None:
        """Median of recent values, or None while warming up."""
        return median(self._values) if self.is_warm else None

    @property
    def mad(self) -> float | None:
        """Median absolute deviation, clamped to the floor(s), or None while warming up."""
        centre = self.median
        if centre is None:
            return None
        raw_mad = median(abs(value - centre) for value in self._values)
        floor = self._mad_floor
        if self._counts:
            floor = max(floor, MAD_SCALE * sqrt(max(centre, 0.0)))
        return max(raw_mad, floor)

    def score(self, value: float) -> float | None:
        """Modified z-score of ``value``; positive means higher than usual."""
        centre, spread = self.median, self.mad
        if centre is None or spread is None:
            return None
        return MAD_SCALE * (value - centre) / spread

    def upper_band(self, threshold: float) -> float | None:
        """Value at which the score reaches ``threshold`` (the top of "normal")."""
        centre, spread = self.median, self.mad
        if centre is None or spread is None:
            return None
        return centre + threshold * spread / MAD_SCALE


class KeyedBaselines:
    """One :class:`RobustBaseline` per key (for example per log template), bounded in number.

    A key seen for the first time gets a history of zeros as long as the
    shared history so far: before a template existed, its count in every
    window we learned from was zero. Values are treated as counts (see the
    counting-noise floor above). That lets a brand-new error template be
    scored immediately against "this never happens" instead of waiting for
    its own warm-up, which is exactly when an outage needs catching.

    At most ``max_keys`` baselines are kept; the least recently touched one
    is dropped to make room, so a stream of unique templates cannot grow
    memory without bound.
    """

    def __init__(self, capacity: int, min_samples: int, mad_floor: float, max_keys: int) -> None:
        if max_keys < 1:
            raise ValueError("max_keys must be at least 1")
        self._capacity = capacity
        self._min_samples = min_samples
        self._mad_floor = mad_floor
        self._max_keys = max_keys
        self._baselines: OrderedDict[str, RobustBaseline] = OrderedDict()

    def touch(self, key: str, history_length: int) -> RobustBaseline:
        """Return the baseline for ``key``, creating it with ``history_length`` zeros if new."""
        baseline = self._baselines.get(key)
        if baseline is None:
            zeros = [0.0] * min(history_length, self._capacity)
            baseline = RobustBaseline(
                self._capacity, self._min_samples, self._mad_floor, zeros, counts=True
            )
            self._baselines[key] = baseline
            if len(self._baselines) > self._max_keys:
                self._baselines.popitem(last=False)
        self._baselines.move_to_end(key)
        return baseline

    def get(self, key: str) -> RobustBaseline | None:
        """The baseline for ``key`` without creating or refreshing it."""
        return self._baselines.get(key)

    def keys(self) -> list[str]:
        """Tracked keys, least recently touched first."""
        return list(self._baselines)

    def items(self) -> Iterator[tuple[str, RobustBaseline]]:
        """Tracked keys with their baselines, least recently touched first."""
        yield from list(self._baselines.items())

    def __len__(self) -> int:
        return len(self._baselines)
