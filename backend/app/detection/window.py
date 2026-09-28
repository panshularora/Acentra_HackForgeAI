"""Rolling error rate over a sliding window made of fixed-size buckets.

Events are counted into the currently open bucket. Every ``bucket_seconds``
the bucket is closed and pushed into the window, and the oldest bucket falls
out. With the defaults (10 s buckets, 60 s window) the error rate is refreshed
every 10 seconds but always reflects the last full minute, which smooths out
single-second blips without hiding a real spike for long.
"""

from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime

from app.models import LogEvent


@dataclass(slots=True)
class Bucket:
    """Counts for one closed time slice. Only error events are kept, for attribution."""

    end: datetime
    total: int = 0
    errors: int = 0
    error_events: list[LogEvent] = field(default_factory=list)


class BucketAccumulator:
    """Collects events for the bucket that is currently open."""

    def __init__(self) -> None:
        self._total = 0
        self._error_events: list[LogEvent] = []

    def add(self, event: LogEvent) -> None:
        """Count one event in the open bucket."""
        self._total += 1
        if event.is_error:
            self._error_events.append(event)

    def close(self, end: datetime) -> Bucket:
        """Return the finished bucket and start a new, empty one."""
        bucket = Bucket(
            end=end,
            total=self._total,
            errors=len(self._error_events),
            error_events=self._error_events,
        )
        self._total = 0
        self._error_events = []
        return bucket


class SlidingWindow:
    """The most recent ``bucket_count`` closed buckets."""

    def __init__(self, bucket_count: int) -> None:
        if bucket_count < 1:
            raise ValueError("bucket_count must be at least 1")
        self._buckets: deque[Bucket] = deque(maxlen=bucket_count)

    def push(self, bucket: Bucket) -> None:
        """Add a closed bucket, evicting the oldest one when the window is full."""
        self._buckets.append(bucket)

    @property
    def is_full(self) -> bool:
        """True once the window covers its whole duration."""
        return len(self._buckets) == self._buckets.maxlen

    @property
    def total(self) -> int:
        """Number of log lines in the window."""
        return sum(b.total for b in self._buckets)

    @property
    def errors(self) -> int:
        """Number of error lines in the window."""
        return sum(b.errors for b in self._buckets)

    @property
    def error_rate(self) -> float:
        """Errors divided by total lines, or 0.0 for an empty window."""
        total = self.total
        return self.errors / total if total else 0.0

    def error_events(self) -> Iterator[LogEvent]:
        """Error events in the window, oldest first."""
        for bucket in self._buckets:
            yield from bucket.error_events
