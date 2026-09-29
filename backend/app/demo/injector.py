"""Inject demo faults into the live log, matching tools/loggen.py.

Additive faults (db-outage, cred-stuffing, new-error) append lines to the log
the tailer is already reading. Suppression faults (heartbeat-stop, flow-break)
write the same control file the running generator already watches
(``<log>.faults.json``).
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FAULTS: dict[str, str] = {
    "db-outage": "claim-adjudication database timeouts",
    "cred-stuffing": "failed member logins from 10.4.2.17",
    "new-error": "never-seen TLS certificate failures calling payer-gw.example.org",
    "heartbeat-stop": "eligibility-sync heartbeats go silent",
    "flow-break": "validated claims stop being adjudicated",
}
SUPPRESSIONS = frozenset({"heartbeat-stop", "flow-break"})
INCIDENT_RATES: dict[str, float] = {
    "db-outage": 3.0,
    "cred-stuffing": 6.0,
    "new-error": 0.5,
}
DEFAULT_DURATIONS: dict[str, float] = {
    "db-outage": 45.0,
    "cred-stuffing": 30.0,
    "new-error": 45.0,
    "heartbeat-stop": 60.0,
    "flow-break": 60.0,
}
CRED_STUFFING_IP = "10.4.2.17"
PAYER_GATEWAY_HOST = "payer-gw.example.org"


@dataclass(frozen=True, slots=True)
class FaultStatus:
    """One fault that is active right now."""

    name: str
    until: float
    mode: str

    def to_dict(self) -> dict[str, Any]:
        until = datetime.fromtimestamp(self.until, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        return {"name": self.name, "until": until, "mode": self.mode}


def control_path(log_path: Path) -> Path:
    """Control file next to the log; same path loggen reads."""
    return log_path.with_name(log_path.name + ".faults.json")


def set_fault(path: Path, kind: str, until: float | None) -> None:
    """Record ``kind`` as active until ``until`` (epoch seconds), or clear it."""
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        entries = {}
    if not isinstance(entries, dict):
        entries = {}
    if until is None:
        entries.pop(kind, None)
    else:
        entries[kind] = until
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".tmp")
    partial.write_text(json.dumps(entries), encoding="utf-8")
    partial.replace(path)


def _format_ts(ts: datetime) -> str:
    return ts.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z"


def _incident_line(kind: str, ts: datetime, rng: random.Random) -> str:
    stamp = _format_ts(ts)
    member = f"M{rng.randint(1_000_000, 9_999_999)}"
    req = f"{rng.getrandbits(32):08x}"
    if kind == "db-outage":
        ip = f"10.{rng.randint(0, 3)}.{rng.randint(0, 255)}.{rng.randint(1, 254)}"
        return (
            f'{stamp} ERROR claim-adjudication msg="DB connection timeout" '
            f"req={req} member_id={member} name=\"Demo User\" plan=MEDICAID-A "
            f"pool=claims-primary ip={ip} status=503 latency_ms={rng.randint(5000, 5200)}"
        )
    if kind == "cred-stuffing":
        return (
            f'{stamp} ERROR member-auth msg="login failed: invalid credentials" '
            f"req={req} member_id={member} name=\"Demo User\" plan=MEDICAID-A "
            f"email=demo{rng.randint(1, 999)}@example.com ip={CRED_STUFFING_IP} "
            f"status=401 latency_ms={rng.randint(20, 60)}"
        )
    if kind == "new-error":
        ip = f"10.{rng.randint(0, 3)}.{rng.randint(0, 255)}.{rng.randint(1, 254)}"
        return (
            f'{stamp} ERROR payment-gateway '
            f'msg="TLS certificate verification failed for payer gateway" '
            f"req={req} member_id={member} name=\"Demo User\" plan=MEDICAID-A "
            f"host={PAYER_GATEWAY_HOST} ip={ip} status=502 latency_ms={rng.randint(15, 40)}"
        )
    raise ValueError(f"unknown incident: {kind}")


class FaultInjector:
    """Starts and tracks demo faults for the dashboard."""

    def __init__(self, log_path: Path) -> None:
        self.log_path = log_path
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._additive_until: dict[str, float] = {}

    @property
    def control_file(self) -> Path:
        return control_path(self.log_path)

    def active(self) -> list[FaultStatus]:
        """Faults whose until-time is still in the future."""
        now = time.time()
        found: list[FaultStatus] = []
        try:
            entries = json.loads(self.control_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            entries = {}
        if isinstance(entries, dict):
            for name, until in entries.items():
                if name in FAULTS and isinstance(until, int | float) and until > now:
                    mode = "suppress" if name in SUPPRESSIONS else "lines"
                    found.append(FaultStatus(name, float(until), mode))
        for name, until in self._additive_until.items():
            if until > now and all(item.name != name for item in found):
                found.append(FaultStatus(name, until, "lines"))
        return sorted(found, key=lambda item: item.name)

    async def inject(self, name: str, duration: float | None = None) -> FaultStatus:
        """Start ``name`` for ``duration`` seconds (or the demo default)."""
        if name not in FAULTS:
            raise ValueError(f"unknown fault: {name}")
        seconds = float(duration if duration is not None else DEFAULT_DURATIONS[name])
        if seconds <= 0:
            raise ValueError("duration must be positive")
        until = time.time() + seconds
        set_fault(self.control_file, name, until)
        if name in SUPPRESSIONS:
            return FaultStatus(name, until, "suppress")
        self._additive_until[name] = until
        existing = self._tasks.get(name)
        if existing is not None and not existing.done():
            existing.cancel()
        self._tasks[name] = asyncio.create_task(
            self._write_lines(name, seconds), name=f"fault-{name}"
        )
        return FaultStatus(name, until, "lines")

    def stop(self, name: str) -> None:
        """Clear ``name`` from the control file and cancel its writer."""
        if name not in FAULTS:
            raise ValueError(f"unknown fault: {name}")
        set_fault(self.control_file, name, None)
        self._additive_until.pop(name, None)
        task = self._tasks.pop(name, None)
        if task is not None and not task.done():
            task.cancel()

    def stop_all(self) -> list[str]:
        """Stop every known fault, including leftover control-file keys."""
        names = set(self._tasks) | set(self._additive_until)
        names.update(item.name for item in self.active())
        try:
            entries = json.loads(self.control_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            entries = {}
        if isinstance(entries, dict):
            names.update(key for key in entries if key in FAULTS)
        stopped = sorted(names)
        for name in stopped:
            self.stop(name)
        return stopped

    async def _write_lines(self, name: str, duration: float) -> None:
        rng = random.Random()
        rate = INCIDENT_RATES[name]
        started = time.monotonic()
        tick = 0
        try:
            while tick < duration:
                second_start = datetime.now(UTC)
                count = max(0, round(rng.gauss(rate, rate * 0.1)))
                lines = [
                    _incident_line(name, second_start, rng) for _ in range(count)
                ]
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                with self.log_path.open("a", encoding="utf-8") as handle:
                    handle.writelines(line + "\n" for line in lines)
                tick += 1
                await asyncio.sleep(max(0.0, started + tick - time.monotonic()))
        except asyncio.CancelledError:
            raise
        finally:
            self._additive_until.pop(name, None)

    def close(self) -> None:
        """Cancel writers and drop the generator control file."""
        self.stop_all()
