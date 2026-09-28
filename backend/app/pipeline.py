"""Glue between the stages: tailer -> parser -> detector -> store -> dashboard / AWS.

Two coroutines share one event loop, so no locks are needed:

* the ingest loop feeds every parsed line into the detector's open bucket;
* the clock loop closes a bucket every ``bucket_seconds`` on wall-clock
  boundaries (13:05:00, 13:05:10, ...), even when no lines arrived. A silent
  log still produces a stats point, which is exactly what should be visible
  when a service stops logging.

AWS delivery is handed to an :class:`AlertSink` that does its work in the
background, so a slow or unreachable AWS endpoint never delays detection.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Protocol

from app.alerts.store import AlertStore, StatsHistory
from app.api.ws import ConnectionManager
from app.detection.detector import AlertChange, AlertEvent, DetectionResult, Detector
from app.ingest.parser import LogParser
from app.ingest.tailer import FileTailer
from app.models import Alert, ChannelDelivery, Delivery, DeliveryState

logger = logging.getLogger(__name__)

# Updates within an incident only refresh the dashboard; these changes are
# worth paging someone about.
PUBLISHED_CHANGES = frozenset({AlertChange.OPENED, AlertChange.ESCALATED, AlertChange.RESOLVED})


class AlertSink(Protocol):
    """Something that delivers alerts outside the process (see ``alerts.publisher``)."""

    def submit(self, event: AlertEvent) -> None:
        """Queue an alert and the change that triggered it for delivery without blocking."""


class Pipeline:
    """Runs ingestion and the bucket clock, and routes results to their consumers."""

    def __init__(
        self,
        *,
        tailer: FileTailer,
        parser: LogParser,
        detector: Detector,
        store: AlertStore,
        stats: StatsHistory,
        clients: ConnectionManager,
        sink: AlertSink | None = None,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.tailer = tailer
        self.parser = parser
        self.detector = detector
        self.store = store
        self.stats = stats
        self.clients = clients
        self.sink = sink
        self._bucket_seconds = detector.config.bucket_seconds
        self._clock = clock
        self._sleep = sleep
        self._last_boundary: float | None = None

    async def run(self) -> None:
        """Run until cancelled."""
        async with asyncio.TaskGroup() as group:
            group.create_task(self._ingest_loop(), name="ingest")
            group.create_task(self._clock_loop(), name="bucket-clock")

    async def close_bucket(self, end: datetime) -> DetectionResult:
        """Close the current bucket at ``end`` and publish the results."""
        result = self.detector.close_bucket(end)
        self.stats.append(result.stats)
        await self.clients.broadcast("stats", result.stats.to_dict())
        if result.alert_event is not None:
            await self._handle_alert(result.alert_event.change, result.alert_event.alert)
        return result

    async def record_delivery(self, alert_id: str, delivery: Delivery) -> None:
        """Store an AWS delivery outcome and show it on the dashboard."""
        alert = self.store.set_delivery(alert_id, delivery)
        if alert is not None:
            await self.clients.broadcast("alert", alert.to_dict())

    async def acknowledge(self, alert_id: str) -> Alert | None:
        """Mark an alert as acknowledged and tell every dashboard."""
        alert = self.store.acknowledge(alert_id)
        if alert is not None:
            await self.clients.broadcast("alert", alert.to_dict())
        return alert

    async def _handle_alert(self, change: AlertChange, alert: Alert) -> None:
        initial: DeliveryState = "pending" if self.sink else "disabled"
        alert.delivery = Delivery(sns=ChannelDelivery(initial), cloudwatch=ChannelDelivery(initial))
        stored = self.store.save_detection(alert, reset_delivery=change in PUBLISHED_CHANGES)
        logger.info("incident %s %s: %s %s", stored.id, change, stored.severity, stored.summary)
        await self.clients.broadcast("alert", stored.to_dict())
        if self.sink is not None and change in PUBLISHED_CHANGES:
            self.sink.submit(AlertEvent(change, stored))

    async def _ingest_loop(self) -> None:
        async for lines in self.tailer.follow():
            for line in lines:
                event = self.parser.parse(line)
                if event is not None:
                    self.detector.observe(event)

    async def _clock_loop(self) -> None:
        while True:
            boundary = self._next_boundary()
            await self._sleep_until(boundary)
            self._last_boundary = boundary
            try:
                await self.close_bucket(datetime.fromtimestamp(boundary, UTC))
            except Exception:
                # One bad bucket must not stop monitoring; log it and carry on.
                logger.exception("failed to close bucket")

    def _next_boundary(self) -> float:
        """The next bucket edge after now, and never one that was already closed.

        If the process stalled past several edges, the missed ones are skipped
        rather than closed back to back as empty buckets.
        """
        step = self._bucket_seconds
        boundary = (self._clock() // step + 1) * step
        if self._last_boundary is not None:
            boundary = max(boundary, self._last_boundary + step)
        return boundary

    async def _sleep_until(self, boundary: float) -> None:
        """Sleep until the clock has really reached ``boundary``.

        Event-loop timers can wake a little early; closing the bucket then
        would let the next iteration pick the same edge again.
        """
        while (remaining := boundary - self._clock()) > 0:
            await self._sleep(remaining)
