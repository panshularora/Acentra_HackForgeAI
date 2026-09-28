"""Generate realistic logs from a (fictional) Medicaid claims platform.

Normal traffic comes from five services with a small, slightly drifting error
rate, the way real systems always have some background failures. Two incidents
can be injected on top:

* ``db-outage``: claim-adjudication loses its database and starts timing out.
* ``cred-stuffing``: one IP hammers member-auth with stolen credentials (401s).

Usage::

    python tools/loggen.py --rate 40                              # normal traffic, forever
    python tools/loggen.py --incident db-outage --duration 45     # extra incident lines only
    python tools/loggen.py --incident cred-stuffing --duration 30

Run the incident command in a second terminal while normal traffic is running;
both append to the same file. All names, member IDs and contact details are
randomly generated and belong to no one.
"""

from __future__ import annotations

import argparse
import contextlib
import math
import random
import sys
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

DEFAULT_OUTPUT = Path("logs/app.log")
DEFAULT_RATE = 40.0
DEFAULT_ERROR_RATE = 0.02
# Slow sinusoidal drift of the background error rate (relative amplitude, period).
DRIFT_AMPLITUDE = 0.08
DRIFT_PERIOD_SECONDS = 900
RATE_JITTER = 0.1

CRED_STUFFING_IP = "10.4.2.17"

FIRST_NAMES = (
    "Maria",
    "James",
    "Aisha",
    "Wei",
    "Carlos",
    "Priya",
    "John",
    "Fatima",
    "Luis",
    "Emma",
)
LAST_NAMES = (
    "Lopez",
    "Smith",
    "Khan",
    "Chen",
    "Garcia",
    "Patel",
    "Brown",
    "Okafor",
    "Nguyen",
)
PLANS = ("MEDICAID-A", "MEDICAID-B", "CHIP", "LTSS")


@dataclass(frozen=True)
class Outcome:
    """One kind of log line a service can emit."""

    level: str
    message: str
    status: int
    latency_ms: tuple[int, int]


@dataclass(frozen=True)
class Service:
    """A service with its share of traffic and the lines it emits."""

    name: str
    weight: float
    ok: tuple[Outcome, ...]
    warn: tuple[Outcome, ...]
    errors: tuple[Outcome, ...]


SERVICES = (
    Service(
        "eligibility-check",
        0.30,
        ok=(Outcome("INFO", "eligibility verified", 200, (40, 180)),),
        warn=(Outcome("WARN", "state MMIS response slow", 200, (900, 2500)),),
        errors=(
            Outcome(
                "ERROR", "eligibility lookup failed: upstream 502", 502, (100, 400)
            ),
        ),
    ),
    Service(
        "claim-adjudication",
        0.25,
        ok=(
            Outcome("INFO", "claim adjudicated", 200, (80, 300)),
            Outcome("INFO", "claim pended for review", 202, (80, 300)),
        ),
        warn=(
            Outcome(
                "WARN", "prior authorization missing, claim pended", 202, (80, 300)
            ),
        ),
        errors=(Outcome("ERROR", "claim rules engine error", 500, (200, 900)),),
    ),
    Service(
        "member-auth",
        0.20,
        ok=(Outcome("INFO", "login succeeded", 200, (30, 120)),),
        warn=(Outcome("WARN", "password reset requested", 200, (30, 120)),),
        errors=(Outcome("ERROR", "login failed: invalid credentials", 401, (30, 120)),),
    ),
    Service(
        "provider-directory",
        0.15,
        ok=(Outcome("INFO", "provider search completed", 200, (20, 150)),),
        warn=(
            Outcome(
                "WARN", "search index stale, serving cached results", 200, (20, 150)
            ),
        ),
        errors=(Outcome("ERROR", "NPI registry request failed", 504, (3000, 5000)),),
    ),
    Service(
        "payment-gateway",
        0.10,
        ok=(Outcome("INFO", "provider payment scheduled", 200, (100, 400)),),
        warn=(Outcome("WARN", "remittance file delayed", 200, (100, 400)),),
        errors=(Outcome("ERROR", "ACH transfer rejected by bank", 422, (100, 400)),),
    ),
)
WARN_SHARE = 0.03

INCIDENTS: dict[str, tuple[str, float]] = {
    # name: (description, extra lines per second)
    "db-outage": ("claim-adjudication database timeouts", 2.0),
    "cred-stuffing": (f"failed member logins from {CRED_STUFFING_IP}", 6.0),
}


class LineFactory:
    """Builds individual log lines from a seeded random generator."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng

    def normal(self, ts: datetime, error_rate: float) -> str:
        """A line of background traffic; an error with probability ``error_rate``."""
        service = self.rng.choices(SERVICES, weights=[s.weight for s in SERVICES])[0]
        roll = self.rng.random()
        if roll < error_rate:
            outcome = self.rng.choice(service.errors)
        elif roll < error_rate + WARN_SHARE:
            outcome = self.rng.choice(service.warn)
        else:
            outcome = self.rng.choice(service.ok)
        return self._line(ts, service.name, outcome, self._client_ip())

    def incident(self, kind: str, ts: datetime) -> str:
        """A line belonging to the named incident."""
        if kind == "db-outage":
            outcome = Outcome("ERROR", "DB connection timeout", 503, (5000, 5200))
            return self._line(
                ts,
                "claim-adjudication",
                outcome,
                self._client_ip(),
                pool="claims-primary",
            )
        if kind == "cred-stuffing":
            outcome = Outcome(
                "ERROR", "login failed: invalid credentials", 401, (20, 60)
            )
            return self._line(
                ts, "member-auth", outcome, CRED_STUFFING_IP, email=self._email()
            )
        raise ValueError(f"unknown incident: {kind}")

    def _line(
        self, ts: datetime, service: str, outcome: Outcome, ip: str, **extra: str
    ) -> str:
        name = f"{self.rng.choice(FIRST_NAMES)} {self.rng.choice(LAST_NAMES)}"
        fields = {
            "msg": f'"{outcome.message}"',
            "req": f"{self.rng.getrandbits(32):08x}",
            "member_id": f"M{self.rng.randint(1_000_000, 9_999_999)}",
            "name": f'"{name}"',
            "plan": self.rng.choice(PLANS),
            **extra,
            "ip": ip,
            "status": str(outcome.status),
            "latency_ms": str(self.rng.randint(*outcome.latency_ms)),
        }
        body = " ".join(f"{key}={value}" for key, value in fields.items())
        return f"{format_ts(ts)} {outcome.level} {service} {body}"

    def _client_ip(self) -> str:
        return f"10.{self.rng.randint(0, 3)}.{self.rng.randint(0, 255)}.{self.rng.randint(1, 254)}"

    def _email(self) -> str:
        return f"{self.rng.choice(FIRST_NAMES).lower()}{self.rng.randint(1, 999)}@example.com"


def format_ts(ts: datetime) -> str:
    """ISO-8601 UTC with milliseconds, e.g. 2026-09-28T13:05:03.412Z."""
    return (
        ts.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.")
        + f"{ts.microsecond // 1000:03d}Z"
    )


def drifting_error_rate(base: float, elapsed_seconds: float) -> float:
    """Background error rate with a slow, gentle drift, as real services have."""
    phase = 2 * math.pi * elapsed_seconds / DRIFT_PERIOD_SECONDS
    return base * (1 + DRIFT_AMPLITUDE * math.sin(phase))


def lines_this_second(rng: random.Random, rate: float) -> int:
    """How many lines to write in one second: ``rate`` with some jitter."""
    return max(0, round(rng.gauss(rate, rate * RATE_JITTER)))


def spread_over_second(
    rng: random.Random, start: datetime, count: int
) -> list[datetime]:
    """``count`` sorted timestamps within the second starting at ``start``."""
    return sorted(start + timedelta(seconds=rng.random()) for _ in range(count))


def normal_second(
    factory: LineFactory,
    start: datetime,
    elapsed: float,
    rate: float,
    error_rate: float,
) -> Iterator[str]:
    """All background lines for the second beginning at ``start``."""
    current_error_rate = drifting_error_rate(error_rate, elapsed)
    count = lines_this_second(factory.rng, rate)
    for ts in spread_over_second(factory.rng, start, count):
        yield factory.normal(ts, current_error_rate)


def incident_second(
    factory: LineFactory, kind: str, start: datetime, rate: float
) -> Iterator[str]:
    """All incident lines for the second beginning at ``start``."""
    count = lines_this_second(factory.rng, rate)
    for ts in spread_over_second(factory.rng, start, count):
        yield factory.incident(kind, ts)


SecondProducer = Callable[[datetime, float], Iterable[str]]


def write_forever(
    path: Path, produce_second: SecondProducer, duration: float | None
) -> None:
    """Append one second of lines at a time, in real time, until ``duration`` elapses."""
    path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    tick = 0
    while duration is None or tick < duration:
        second_start = datetime.now(UTC)
        lines = list(produce_second(second_start, float(tick)))
        with path.open("a", encoding="utf-8") as handle:
            handle.writelines(line + "\n" for line in lines)
        tick += 1
        time.sleep(max(0.0, started + tick - time.monotonic()))


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Command-line interface."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--out", type=Path, default=DEFAULT_OUTPUT, help="log file to append to"
    )
    parser.add_argument(
        "--rate", type=float, help="lines per second (default 40, or per incident)"
    )
    parser.add_argument("--error-rate", type=float, default=DEFAULT_ERROR_RATE)
    parser.add_argument(
        "--incident", choices=sorted(INCIDENTS), help="write incident lines only"
    )
    parser.add_argument(
        "--duration", type=float, help="seconds to run (default: forever)"
    )
    parser.add_argument("--seed", type=int, help="random seed for reproducible output")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    args = parse_args(sys.argv[1:] if argv is None else argv)
    factory = LineFactory(random.Random(args.seed))

    if args.incident:
        description, default_rate = INCIDENTS[args.incident]
        rate = args.rate or default_rate
        duration = args.duration or 45.0
        print(
            f"injecting {args.incident} ({description}) for {duration:.0f}s into {args.out}",
            flush=True,
        )
        write_forever(
            args.out,
            lambda start, _elapsed: incident_second(
                factory, args.incident, start, rate
            ),
            duration,
        )
        return 0

    rate = args.rate or DEFAULT_RATE
    print(
        f"writing ~{rate:.0f} lines/s of normal traffic to {args.out} (Ctrl+C to stop)",
        flush=True,
    )
    with contextlib.suppress(KeyboardInterrupt):
        write_forever(
            args.out,
            lambda start, elapsed: normal_second(
                factory, start, elapsed, rate, args.error_rate
            ),
            args.duration,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
