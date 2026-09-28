"""Domain objects shared by the pipeline, the store and the API.

The ``to_dict`` methods produce exactly the JSON shapes in CONTRACT.md, which
the dashboard depends on. Timestamps are always serialised as UTC with a
trailing ``Z``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

DeliveryState = Literal["pending", "sent", "failed", "disabled"]


def to_iso(moment: datetime) -> str:
    """Format a datetime as ISO-8601 UTC with second precision, e.g. 2026-09-28T13:05:10Z."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def from_iso(text: str) -> datetime:
    """Parse the output of :func:`to_iso` (or any ISO-8601 string) into an aware datetime."""
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


class Severity(StrEnum):
    """Alert severity, ordered from least to most urgent."""

    WARNING = "WARNING"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

    @property
    def rank(self) -> int:
        """Numeric order so severities can be compared (WARNING < HIGH < CRITICAL)."""
        return _SEVERITY_RANK[self]


_SEVERITY_RANK = {Severity.WARNING: 1, Severity.HIGH: 2, Severity.CRITICAL: 3}


@dataclass(frozen=True, slots=True)
class LogEvent:
    """One parsed log line. ``message`` and ``raw`` are already PHI-masked."""

    ts: datetime
    level: str
    service: str
    message: str
    raw: str
    source_ip: str | None = None
    http_status: int | None = None

    @property
    def is_error(self) -> bool:
        """Whether this line counts towards the error rate."""
        return self.level in {"ERROR", "FATAL", "CRITICAL"}


@dataclass(frozen=True, slots=True)
class StatsPoint:
    """Sliding-window statistics published once per closed bucket."""

    ts: datetime
    total: int
    errors: int
    error_rate: float
    baseline_median: float | None
    band_upper: float | None
    score: float | None
    severity: Severity | None

    def to_dict(self) -> dict[str, Any]:
        """Serialise to the contract's StatsPoint JSON."""
        return {
            "ts": to_iso(self.ts),
            "total": self.total,
            "errors": self.errors,
            "error_rate": round(self.error_rate, 4),
            "baseline_median": _round_or_none(self.baseline_median, 4),
            "band_upper": _round_or_none(self.band_upper, 4),
            "score": _round_or_none(self.score, 2),
            "severity": self.severity.value if self.severity else None,
        }


@dataclass(frozen=True, slots=True)
class Contributor:
    """A value that appears in many error lines, with its count and share of errors."""

    value: str
    count: int
    share: float

    def to_dict(self) -> dict[str, Any]:
        """Serialise to ``{"value", "count", "share"}``."""
        return {"value": self.value, "count": self.count, "share": round(self.share, 2)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Contributor:
        """Inverse of :meth:`to_dict`."""
        return cls(value=data["value"], count=int(data["count"]), share=float(data["share"]))


@dataclass(frozen=True, slots=True)
class TopContributors:
    """The services, message templates and source IPs behind an incident's errors."""

    services: list[Contributor] = field(default_factory=list)
    messages: list[Contributor] = field(default_factory=list)
    source_ips: list[Contributor] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to the contract's ``top_contributors`` object."""
        return {
            "services": [c.to_dict() for c in self.services],
            "messages": [c.to_dict() for c in self.messages],
            "source_ips": [c.to_dict() for c in self.source_ips],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TopContributors:
        """Inverse of :meth:`to_dict`."""
        return cls(
            services=[Contributor.from_dict(c) for c in data.get("services", [])],
            messages=[Contributor.from_dict(c) for c in data.get("messages", [])],
            source_ips=[Contributor.from_dict(c) for c in data.get("source_ips", [])],
        )


@dataclass(slots=True)
class ChannelDelivery:
    """Delivery state of an alert on one AWS channel."""

    status: DeliveryState = "pending"
    message_id: str | None = None
    error: str | None = None


@dataclass(slots=True)
class Delivery:
    """Per-channel delivery state for an alert."""

    sns: ChannelDelivery = field(default_factory=ChannelDelivery)
    cloudwatch: ChannelDelivery = field(default_factory=ChannelDelivery)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to the contract's ``delivery`` object (CloudWatch has no message id)."""
        return {
            "sns": {
                "status": self.sns.status,
                "message_id": self.sns.message_id,
                "error": self.sns.error,
            },
            "cloudwatch": {"status": self.cloudwatch.status, "error": self.cloudwatch.error},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Delivery:
        """Inverse of :meth:`to_dict`."""
        sns = data.get("sns", {})
        cloudwatch = data.get("cloudwatch", {})
        return cls(
            sns=ChannelDelivery(
                sns.get("status", "pending"), sns.get("message_id"), sns.get("error")
            ),
            cloudwatch=ChannelDelivery(
                cloudwatch.get("status", "pending"), None, cloudwatch.get("error")
            ),
        )


@dataclass(slots=True)
class Alert:
    """An incident: one alert per sustained deviation, updated until it resolves."""

    id: str
    status: Literal["open", "resolved"]
    severity: Severity
    score: float
    error_rate: float
    baseline_median: float
    opened_at: datetime
    updated_at: datetime
    summary: str
    top_contributors: TopContributors
    sample_lines: list[str]
    resolved_at: datetime | None = None
    acknowledged: bool = False
    delivery: Delivery = field(default_factory=Delivery)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to the contract's Alert JSON."""
        return {
            "id": self.id,
            "status": self.status,
            "severity": self.severity.value,
            "score": round(self.score, 2),
            "error_rate": round(self.error_rate, 4),
            "baseline_median": round(self.baseline_median, 4),
            "opened_at": to_iso(self.opened_at),
            "updated_at": to_iso(self.updated_at),
            "resolved_at": to_iso(self.resolved_at) if self.resolved_at else None,
            "summary": self.summary,
            "top_contributors": self.top_contributors.to_dict(),
            "sample_lines": list(self.sample_lines),
            "acknowledged": self.acknowledged,
            "delivery": self.delivery.to_dict(),
        }


def _round_or_none(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)
