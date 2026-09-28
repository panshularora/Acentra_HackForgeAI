"""Parse one log line into a :class:`~app.models.LogEvent`.

Expected format (the one ``tools/loggen.py`` writes, and a common shape for
structured service logs)::

    2026-09-28T13:05:03.412Z ERROR claim-adjudication msg="DB connection timeout" \
        member_id=M1234567 ip=10.4.2.17 status=503 latency_ms=5012

The whole line is masked before any field is extracted, so PHI never reaches
the detector, the database, the dashboard or AWS. Lines that do not match are
counted and skipped rather than crashing the pipeline: a single corrupt write
should not take monitoring down.
"""

import re
from datetime import UTC, datetime

from app.ingest.masking import mask, message_template
from app.models import LogEvent

_LINE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}T\S+)\s+(?P<level>[A-Za-z]+)\s+(?P<service>[\w.-]+)\s*(?P<rest>.*)$"
)
_FIELD = re.compile(r'(?P<key>\w+)=(?P<value>"(?:[^"\\]|\\.)*"|\S+)')

_LEVEL_ALIASES = {"WARNING": "WARN", "ERR": "ERROR", "CRIT": "CRITICAL"}
_KNOWN_LEVELS = frozenset({"TRACE", "DEBUG", "INFO", "WARN", "ERROR", "FATAL", "CRITICAL"})
_IP_KEYS = ("ip", "source_ip", "client_ip")
_STATUS_KEYS = ("status", "http_status")


def parse_fields(text: str) -> dict[str, str]:
    """Extract ``key=value`` and ``key="quoted value"`` pairs, unquoting values."""
    fields: dict[str, str] = {}
    for match in _FIELD.finditer(text):
        value = match["value"]
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1].replace('\\"', '"')
        fields[match["key"]] = value
    return fields


class LogParser:
    """Stateful parser that keeps counts of parsed and malformed lines."""

    def __init__(self) -> None:
        self.parsed = 0
        self.malformed = 0

    def parse(self, line: str) -> LogEvent | None:
        """Return the event for ``line``, or None if it is blank or malformed."""
        line = line.strip()
        if not line:
            return None
        event = _parse_masked(mask(line))
        if event is None:
            self.malformed += 1
        else:
            self.parsed += 1
        return event


def _parse_masked(line: str) -> LogEvent | None:
    match = _LINE.match(line)
    if match is None:
        return None
    ts = _parse_timestamp(match["ts"])
    level = _normalise_level(match["level"])
    if ts is None or level is None:
        return None

    rest = match["rest"]
    fields = parse_fields(rest)
    message = fields.get("msg") or _FIELD.sub("", rest).strip() or "(no message)"
    return LogEvent(
        ts=ts,
        level=level,
        service=match["service"],
        message=message_template(message),
        raw=line,
        source_ip=_first(fields, _IP_KEYS),
        http_status=_to_int(_first(fields, _STATUS_KEYS)),
    )


def _parse_timestamp(text: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _normalise_level(text: str) -> str | None:
    level = text.upper()
    level = _LEVEL_ALIASES.get(level, level)
    return level if level in _KNOWN_LEVELS else None


def _first(fields: dict[str, str], keys: tuple[str, ...]) -> str | None:
    return next((fields[key] for key in keys if key in fields), None)


def _to_int(text: str | None) -> int | None:
    return int(text) if text is not None and text.isdigit() else None
