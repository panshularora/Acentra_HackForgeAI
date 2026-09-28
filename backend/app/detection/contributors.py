"""Explain an incident: which services, messages and source IPs the errors come from.

An alert that only says "error rate is 31%" sends the on-call engineer
digging through logs. Counting the error lines in the window by service,
message template and source IP usually answers "what broke and where" at
once, and :func:`summarise` turns the counts into one readable sentence.
"""

from collections import Counter
from collections.abc import Iterable, Sequence

from app.models import Contributor, LogEvent, TopContributors

# Background errors come from many client IPs, each with a tiny share, so one
# address behind this much of all errors is the story (40% lets the summary
# name an attacker in the first bucket of a burst, while background errors
# are still in the window).
DOMINANT_IP_SHARE = 0.4
AUTH_FAILURE_STATUSES = frozenset({401, 403})


def rank(values: Iterable[str], total: int, limit: int) -> list[Contributor]:
    """Most common values with their count and share of ``total``."""
    if total == 0:
        return []
    return [
        Contributor(value=value, count=count, share=count / total)
        for value, count in Counter(values).most_common(limit)
    ]


def top_contributors(events: Sequence[LogEvent], limit: int = 3) -> TopContributors:
    """Top services, message templates and source IPs among ``events``."""
    total = len(events)
    return TopContributors(
        services=rank((e.service for e in events), total, limit),
        messages=rank((e.message for e in events), total, limit),
        source_ips=rank((e.source_ip for e in events if e.source_ip), total, limit),
    )


def summarise(events: Sequence[LogEvent], window_seconds: int) -> str:
    """One sentence saying what is failing and where, based on the error events."""
    if not events:
        return "Error rate is above its normal range"

    ip_summary = _summarise_dominant_ip(events, window_seconds)
    if ip_summary:
        return ip_summary

    service, service_share = _most_common_with_share(e.service for e in events)
    service_events = [e for e in events if e.service == service]
    message, _ = _most_common_with_share(e.message for e in service_events)
    return f"{service_share:.0%} of errors come from {service}: {message}"


def sample_lines(events: Sequence[LogEvent], limit: int) -> list[str]:
    """Up to ``limit`` masked lines, newest first, showing the dominant error first.

    Lines carrying the most common message come before background errors, so
    the examples on an alert illustrate its summary rather than whatever
    happened to fail last.
    """
    if not events or limit <= 0:
        return []
    top_message, _ = _most_common_with_share(e.message for e in events)
    newest_first = list(reversed(events))
    typical = [e.raw for e in newest_first if e.message == top_message]
    others = [e.raw for e in newest_first if e.message != top_message]
    return (typical + others)[:limit]


def _summarise_dominant_ip(events: Sequence[LogEvent], window_seconds: int) -> str | None:
    """Describe the incident by source IP if a single address dominates the errors."""
    ips = [e.source_ip for e in events if e.source_ip]
    if not ips:
        return None
    ip, _ = _most_common_with_share(ips)
    ip_events = [e for e in events if e.source_ip == ip]
    if len(ip_events) / len(events) < DOMINANT_IP_SHARE:
        return None

    auth_failures = sum(1 for e in ip_events if e.http_status in AUTH_FAILURE_STATUSES)
    if auth_failures * 2 > len(ip_events):
        return f"{auth_failures} failed logins from {ip} in the last {window_seconds}s"
    message, _ = _most_common_with_share(e.message for e in ip_events)
    return f"{len(ip_events)} errors from {ip} in the last {window_seconds}s: {message}"


def _most_common_with_share(values: Iterable[str]) -> tuple[str, float]:
    counts = Counter(values)
    value, count = counts.most_common(1)[0]
    return value, count / counts.total()
