"""Robust baseline of "normal" error rate, and how far a new rate is from it.

We use the modified z-score of Iglewicz and Hoaglin (1993, "How to Detect and
Handle Outliers"):

    score = 0.6745 * (rate - median) / MAD

where MAD is the median absolute deviation of recent rates from their median.
Median and MAD are used instead of mean and standard deviation because a few
extreme values barely move them, so one past spike does not inflate what we
consider normal. The constant 0.6745 rescales MAD so the score is comparable
to an ordinary z-score for normally distributed data.

Two practical adjustments:

* MAD floor: a very steady service can have a MAD close to zero, which would
  make every tiny wobble look infinitely significant. MAD is clamped to at
  least ``mad_floor``.
* Warm-up: no score is produced until ``min_samples`` rates have been seen.

The baseline does not decide when to learn; the detector stops calling
:meth:`RobustBaseline.update` while an incident is open, so an outage never
becomes the new normal.
"""

from collections import deque
from statistics import median

# Scales MAD to the standard deviation of a normal distribution (1 / 1.4826).
MAD_SCALE = 0.6745


class RobustBaseline:
    """Rolling median and MAD over the most recent window error rates."""

    def __init__(self, capacity: int, min_samples: int, mad_floor: float) -> None:
        if min_samples > capacity:
            raise ValueError("min_samples cannot exceed capacity")
        self._rates: deque[float] = deque(maxlen=capacity)
        self._min_samples = min_samples
        self._mad_floor = mad_floor

    def update(self, rate: float) -> None:
        """Record a rate observed during normal operation."""
        self._rates.append(rate)

    @property
    def sample_count(self) -> int:
        """How many rates the baseline currently holds."""
        return len(self._rates)

    @property
    def is_warm(self) -> bool:
        """True once enough samples exist to trust the baseline."""
        return len(self._rates) >= self._min_samples

    @property
    def median(self) -> float | None:
        """Median of recent rates, or None while warming up."""
        return median(self._rates) if self.is_warm else None

    @property
    def mad(self) -> float | None:
        """Median absolute deviation, clamped to the floor, or None while warming up."""
        centre = self.median
        if centre is None:
            return None
        raw_mad = median(abs(rate - centre) for rate in self._rates)
        return max(raw_mad, self._mad_floor)

    def score(self, rate: float) -> float | None:
        """Modified z-score of ``rate``; positive means more errors than usual."""
        centre, spread = self.median, self.mad
        if centre is None or spread is None:
            return None
        return MAD_SCALE * (rate - centre) / spread

    def upper_band(self, threshold: float) -> float | None:
        """Error rate at which the score reaches ``threshold`` (the top of "normal")."""
        centre, spread = self.median, self.mad
        if centre is None or spread is None:
            return None
        return centre + threshold * spread / MAD_SCALE
