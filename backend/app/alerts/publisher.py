"""Deliver alerts to AWS: an SNS topic (for paging) and CloudWatch Logs (for audit).

This is ordinary boto3 code. When ``AWS_ENDPOINT_URL`` is set it talks to that
endpoint instead of AWS, which is how we run it locally against the moto
emulator; unset it and provide real credentials to publish to a real account.

Design points:

* Delivery never blocks detection. Alerts go onto an asyncio queue and a
  single worker makes the boto3 calls in a thread.
* One message per incident transition (opened, escalated, resolved), in the
  order they happened; ``event`` in the body and attributes says which.
* Each channel is attempted independently and its outcome (``sent`` with the
  SNS message id, or ``failed`` with the error) is recorded on the alert and
  pushed to the dashboard through ``on_delivery``.
* The topic, log group and log stream are created idempotently on startup,
  and again lazily if AWS was unreachable at startup (an emulator forgets its
  state when restarted).
* Only already-masked alert fields are sent. No raw log line ever leaves the
  process.
"""

import asyncio
import contextlib
import json
import logging
import os
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.config import Settings
from app.detection.detector import AlertEvent
from app.models import Alert, ChannelDelivery, Delivery

if TYPE_CHECKING:
    from mypy_boto3_logs import CloudWatchLogsClient
    from mypy_boto3_sns import SNSClient

logger = logging.getLogger(__name__)

DeliveryCallback = Callable[[str, Delivery], Awaitable[None]]

AWS_ERRORS = (BotoCoreError, ClientError)
SNS_SUBJECT_LIMIT = 100
# Fail fast: a paging path that hangs for a minute is worse than one that
# reports "failed" in two seconds and lets the dashboard show it.
BOTO_CONFIG = Config(connect_timeout=2, read_timeout=5, retries={"max_attempts": 2})
# Emulators accept any credentials; real AWS uses the normal boto3 chain.
EMULATOR_CREDENTIALS = {"aws_access_key_id": "testing", "aws_secret_access_key": "testing"}


def alert_message(event: AlertEvent, app_name: str) -> dict[str, Any]:
    """The JSON document sent to SNS and CloudWatch: masked fields only."""
    data = event.alert.to_dict()
    return {
        "source": app_name,
        "event": event.change.value,
        "id": data["id"],
        "status": data["status"],
        "severity": data["severity"],
        "summary": data["summary"],
        "score": data["score"],
        "error_rate": data["error_rate"],
        "baseline_median": data["baseline_median"],
        "opened_at": data["opened_at"],
        "resolved_at": data["resolved_at"],
        "top_contributors": data["top_contributors"],
        "sample_lines": data["sample_lines"],
    }


def sns_subject(alert: Alert, app_name: str) -> str:
    """Short e-mail/SMS friendly subject, within SNS's 100 character limit."""
    prefix = "RESOLVED" if alert.status == "resolved" else alert.severity.value
    subject = f"[{prefix}] {app_name}: {alert.summary}"
    return (
        subject if len(subject) <= SNS_SUBJECT_LIMIT else subject[: SNS_SUBJECT_LIMIT - 3] + "..."
    )


class AlertPublisher:
    """Publishes alerts to SNS and CloudWatch Logs from a background worker."""

    def __init__(self, settings: Settings, on_delivery: DeliveryCallback | None = None) -> None:
        self.settings = settings
        self.on_delivery = on_delivery
        self.topic_arn: str | None = None
        self.log_group = settings.cw_log_group
        self._log_stream = settings.cw_log_stream
        self._logs_ready = False
        self._queue: asyncio.Queue[AlertEvent] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None
        kwargs = self._client_kwargs()
        self._sns: SNSClient = boto3.client("sns", **kwargs)
        self._logs: CloudWatchLogsClient = boto3.client("logs", **kwargs)

    async def start(self) -> None:
        """Create AWS resources (best effort) and start the delivery worker."""
        await asyncio.to_thread(self.ensure_resources)
        self._worker = asyncio.create_task(self._run(), name="aws-publisher")

    async def stop(self) -> None:
        """Stop the worker. Undelivered alerts stay in SQLite with status pending."""
        if self._worker is not None:
            self._worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker
            self._worker = None

    def submit(self, event: AlertEvent) -> None:
        """Queue an alert transition for delivery; returns immediately."""
        self._queue.put_nowait(event)

    async def drain(self) -> None:
        """Wait until every queued alert has been delivered (used by tests)."""
        await self._queue.join()

    def ensure_resources(self) -> None:
        """Create the SNS topic, log group and log stream if missing. Safe to repeat."""
        self._ensure_topic()
        self._ensure_log_stream()

    def deliver(self, event: AlertEvent) -> Delivery:
        """Send one alert transition to both channels synchronously and report the outcome."""
        body = json.dumps(alert_message(event, self.settings.app_name))
        return Delivery(sns=self._publish_sns(event, body), cloudwatch=self._put_log_event(body))

    async def _run(self) -> None:
        while True:
            event = await self._queue.get()
            try:
                delivery = await asyncio.to_thread(self.deliver, event)
                if self.on_delivery is not None:
                    await self.on_delivery(event.alert.id, delivery)
            except Exception:
                logger.exception("delivery of alert %s failed unexpectedly", event.alert.id)
            finally:
                self._queue.task_done()

    def _publish_sns(self, event: AlertEvent, body: str) -> ChannelDelivery:
        alert = event.alert
        try:
            topic_arn = self.topic_arn or self._ensure_topic()
            if topic_arn is None:
                return ChannelDelivery("failed", error="SNS topic unavailable")
            response = self._sns.publish(
                TopicArn=topic_arn,
                Subject=sns_subject(alert, self.settings.app_name),
                Message=body,
                MessageAttributes={
                    "event": {"DataType": "String", "StringValue": event.change.value},
                    "severity": {"DataType": "String", "StringValue": alert.severity.value},
                    "status": {"DataType": "String", "StringValue": alert.status},
                },
            )
        except AWS_ERRORS as error:
            logger.warning("SNS publish failed for %s: %s", alert.id, error)
            return ChannelDelivery("failed", error=str(error))
        return ChannelDelivery("sent", message_id=response["MessageId"])

    def _put_log_event(self, body: str) -> ChannelDelivery:
        try:
            if not self._logs_ready and not self._ensure_log_stream():
                return ChannelDelivery("failed", error="CloudWatch log stream unavailable")
            self._logs.put_log_events(
                logGroupName=self.log_group,
                logStreamName=self._log_stream,
                logEvents=[{"timestamp": int(time.time() * 1000), "message": body}],
            )
        except AWS_ERRORS as error:
            logger.warning("CloudWatch put_log_events failed: %s", error)
            return ChannelDelivery("failed", error=str(error))
        return ChannelDelivery("sent")

    def _ensure_topic(self) -> str | None:
        try:
            # CreateTopic is idempotent: it returns the existing ARN if present.
            self.topic_arn = self._sns.create_topic(Name=self.settings.sns_topic_name)["TopicArn"]
        except AWS_ERRORS as error:
            logger.warning("could not create SNS topic: %s", error)
            self.topic_arn = None
        return self.topic_arn

    def _ensure_log_stream(self) -> bool:
        try:
            with contextlib.suppress(self._logs.exceptions.ResourceAlreadyExistsException):
                self._logs.create_log_group(logGroupName=self.log_group)
            with contextlib.suppress(self._logs.exceptions.ResourceAlreadyExistsException):
                self._logs.create_log_stream(
                    logGroupName=self.log_group, logStreamName=self._log_stream
                )
        except AWS_ERRORS as error:
            logger.warning("could not create CloudWatch log group/stream: %s", error)
            self._logs_ready = False
        else:
            self._logs_ready = True
        return self._logs_ready

    def _client_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"region_name": self.settings.aws_region, "config": BOTO_CONFIG}
        endpoint = self.settings.aws_endpoint_url
        if endpoint:
            kwargs["endpoint_url"] = endpoint
            if not os.environ.get("AWS_ACCESS_KEY_ID"):
                kwargs.update(EMULATOR_CREDENTIALS)
        return kwargs
