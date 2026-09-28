"""Generate realistic logs from a (fictional) Medicaid claims platform.

Normal traffic comes from five services with a small, slightly drifting error
rate, the way real systems always have some background failures. Alongside it
run two steady signals that only a template-aware detector can watch:

* heartbeats: ``eligibility-sync`` and ``payment-reconciler`` each log
  ``heartbeat service=<name> ok`` every 5 seconds.
* a claim flow: ``claim validated claim_id=<id>`` from claim-intake, followed
  0.3 to 3 seconds later by ``claim adjudicated claim_id=<id>`` from
  claim-adjudication for 98% of claims.

Five faults can be injected on top:

* ``db-outage``: claim-adjudication loses its database and starts timing out.
* ``cred-stuffing``: one IP hammers member-auth with stolen credentials (401s).
* ``new-error``: a never-before-seen TLS certificate failure calling the payer
  gateway, repeated every couple of seconds.
* ``heartbeat-stop``: eligibility-sync stops sending heartbeats.
* ``flow-break``: validated claims stop being adjudicated.

Usage::

    python tools/loggen.py --rate 40                              # normal traffic, forever
    python tools/loggen.py --incident db-outage --duration 45     # extra incident lines only
    python tools/loggen.py --incident cred-stuffing --duration 30
    python tools/loggen.py --incident new-error --duration 45
    python tools/loggen.py --incident heartbeat-stop --duration 60
    python tools/loggen.py --incident flow-break --duration 60

Run the incident command in a second terminal while normal traffic is running.
``db-outage``, ``cred-stuffing`` and ``new-error`` add lines, so they append to
the same file. ``heartbeat-stop`` and ``flow-break`` take lines away, which only
the running generator can do: the incident command records the fault in a small
control file next to the log (``app.log.faults.json``) and the generator drops
the affected lines until it expires. :func:`simulate` produces the same
traffic and faults offline, on a simulated clock, for replays and benchmarks.

All names, member IDs and contact details are randomly generated and belong to
no one.
"""

from __future__ import annotations

import argparse
import contextlib
import heapq
import json
import math
import random
import sys
import time
from collections.abc import Callable, Collection, Iterable, Iterator, Sequence
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

# Heartbeats: services that report in on a steady cadence. heartbeat-stop
# silences the first one.
HEARTBEAT_SERVICES = ("eligibility-sync", "payment-reconciler")
HEARTBEAT_INTERVAL_SECONDS = 5
HEARTBEAT_JITTER_SECONDS = 0.05
SILENCED_SERVICE = HEARTBEAT_SERVICES[0]

# Claim flow: validated claims are adjudicated after a short, skewed delay
# (triangular low, high, mode); the rest are left for manual review.
CLAIMS_PER_SECOND = 2.0
ADJUDICATED_SHARE = 0.98
ADJUDICATION_DELAY_SECONDS = (0.3, 3.0, 0.8)

PAYER_GATEWAY_HOST = "payer-gw.example.org"

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
class Member:
    """A (random, fictional) member whose claim moves through the flow."""

    member_id: str
    name: str


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
        errors=(Outcome("ERROR", "eligibility lookup failed: upstream 502", 502, (100, 400)),),
    ),
    Service(
        "claim-adjudication",
        0.25,
        ok=(
            Outcome("INFO", "claim adjudicated", 200, (80, 300)),
            Outcome("INFO", "claim pended for review", 202, (80, 300)),
        ),
        warn=(Outcome("WARN", "prior authorization missing, claim pended", 202, (80, 300)),),
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
        warn=(Outcome("WARN", "search index stale, serving cached results", 200, (20, 150)),),
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
    "db-outage": ("claim-adjudication database timeouts", 3.0),
    "cred-stuffing": (f"failed member logins from {CRED_STUFFING_IP}", 6.0),
    "new-error": (f"never-seen TLS certificate failures calling {PAYER_GATEWAY_HOST}", 0.5),
}
# Faults that remove lines from the running traffic instead of adding their own.
SUPPRESSIONS: dict[str, str] = {
    # name: description
    "heartbeat-stop": f"{SILENCED_SERVICE} heartbeats go silent",
    "flow-break": "validated claims stop being adjudicated",
}
FAULTS: dict[str, str] = {
    **{name: description for name, (description, _rate) in INCIDENTS.items()},
    **SUPPRESSIONS,
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
            outcome = Outcome("ERROR", "login failed: invalid credentials", 401, (20, 60))
            return self._line(ts, "member-auth", outcome, CRED_STUFFING_IP, email=self._email())
        if kind == "new-error":
            outcome = Outcome(
                "ERROR", "TLS certificate verification failed for payer gateway", 502, (15, 40)
            )
            return self._line(
                ts, "payment-gateway", outcome, self._client_ip(), host=PAYER_GATEWAY_HOST
            )
        raise ValueError(f"unknown incident: {kind}")

    def heartbeat(self, ts: datetime, service: str) -> str:
        """A liveness line; carries no member data."""
        return f'{format_ts(ts)} INFO {service} msg="heartbeat service={service} ok"'

    def claim_id(self) -> str:
        """A random claim identifier, e.g. CLM-5F3A09C2."""
        return f"CLM-{self.rng.getrandbits(32):08X}"

    def member(self) -> Member:
        """A random member (the parser masks both fields)."""
        return Member(self._member_id(), self._full_name())

    def claim_validated(self, ts: datetime, claim_id: str, member: Member) -> str:
        """The first step of the claim flow."""
        outcome = Outcome("INFO", "claim validated", 200, (20, 80))
        return self._claim_line(ts, "claim-intake", outcome, claim_id, member)

    def claim_adjudicated(self, ts: datetime, claim_id: str, member: Member) -> str:
        """The second step of the claim flow, for the same claim and member."""
        outcome = Outcome("INFO", "claim adjudicated", 200, (80, 300))
        return self._claim_line(ts, "claim-adjudication", outcome, claim_id, member)

    def _claim_line(
        self, ts: datetime, service: str, outcome: Outcome, claim_id: str, member: Member
    ) -> str:
        # Later keys replace the random member fields in place, keeping the field order.
        return self._line(
            ts,
            service,
            outcome,
            self._client_ip(),
            member_id=member.member_id,
            name=f'"{member.name}"',
            claim_id=claim_id,
        )

    def _line(self, ts: datetime, service: str, outcome: Outcome, ip: str, **extra: str) -> str:
        name = self._full_name()
        fields = {
            "msg": f'"{outcome.message}"',
            "req": f"{self.rng.getrandbits(32):08x}",
            "member_id": self._member_id(),
            "name": f'"{name}"',
            "plan": self.rng.choice(PLANS),
            **extra,
            "ip": ip,
            "status": str(outcome.status),
            "latency_ms": str(self.rng.randint(*outcome.latency_ms)),
        }
        body = " ".join(f"{key}={value}" for key, value in fields.items())
        return f"{format_ts(ts)} {outcome.level} {service} {body}"

    def _full_name(self) -> str:
        return f"{self.rng.choice(FIRST_NAMES)} {self.rng.choice(LAST_NAMES)}"

    def _member_id(self) -> str:
        return f"M{self.rng.randint(1_000_000, 9_999_999)}"

    def _client_ip(self) -> str:
        return f"10.{self.rng.randint(0, 3)}.{self.rng.randint(0, 255)}.{self.rng.randint(1, 254)}"

    def _email(self) -> str:
        return f"{self.rng.choice(FIRST_NAMES).lower()}{self.rng.randint(1, 999)}@example.com"


def format_ts(ts: datetime) -> str:
    """ISO-8601 UTC with milliseconds, e.g. 2026-09-28T13:05:03.412Z."""
    return ts.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z"


def drifting_error_rate(base: float, elapsed_seconds: float) -> float:
    """Background error rate with a slow, gentle drift, as real services have."""
    phase = 2 * math.pi * elapsed_seconds / DRIFT_PERIOD_SECONDS
    return base * (1 + DRIFT_AMPLITUDE * math.sin(phase))


def lines_this_second(rng: random.Random, rate: float) -> int:
    """How many lines to write in one second: ``rate`` with some jitter."""
    return max(0, round(rng.gauss(rate, rate * RATE_JITTER)))


def spread_over_second(rng: random.Random, start: datetime, count: int) -> list[datetime]:
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


def incident_second(factory: LineFactory, kind: str, start: datetime, rate: float) -> Iterator[str]:
    """All incident lines for the second beginning at ``start``."""
    count = lines_this_second(factory.rng, rate)
    for ts in spread_over_second(factory.rng, start, count):
        yield factory.incident(kind, ts)


def heartbeat_second(
    factory: LineFactory, start: datetime, elapsed: int, silenced: Collection[str] = ()
) -> list[str]:
    """Heartbeat lines for the second beginning at ``start``, ``elapsed`` seconds in.

    Services are staggered one second apart. Silenced services still use up
    their random draws, so the rest of the stream is identical with or
    without the fault.
    """
    lines: list[str] = []
    for offset, service in enumerate(HEARTBEAT_SERVICES):
        if elapsed % HEARTBEAT_INTERVAL_SECONDS != offset % HEARTBEAT_INTERVAL_SECONDS:
            continue
        jitter = factory.rng.uniform(-HEARTBEAT_JITTER_SECONDS, HEARTBEAT_JITTER_SECONDS)
        line = factory.heartbeat(start + timedelta(seconds=0.5 + jitter), service)
        if service not in silenced:
            lines.append(line)
    return lines


class ClaimFlow:
    """Claims moving from validation to adjudication, with a short, variable delay."""

    def __init__(self, factory: LineFactory, rate: float = CLAIMS_PER_SECOND) -> None:
        self.factory = factory
        self.rate = rate
        # (due time, claim id, member), earliest first.
        self._pending: list[tuple[datetime, str, Member]] = []

    def second(self, start: datetime, adjudicating: bool = True) -> list[str]:
        """Claims validated in this second, and adjudications that fall due in it.

        With ``adjudicating`` False (a flow break) adjudications that fall due
        are dropped. Their lines are still built so the random stream, and so
        everything after the break, stays the same.
        """
        rng = self.factory.rng
        lines: list[str] = []
        for ts in spread_over_second(rng, start, lines_this_second(rng, self.rate)):
            claim_id, member = self.factory.claim_id(), self.factory.member()
            lines.append(self.factory.claim_validated(ts, claim_id, member))
            if rng.random() < ADJUDICATED_SHARE:
                delay = rng.triangular(*ADJUDICATION_DELAY_SECONDS)
                heapq.heappush(self._pending, (ts + timedelta(seconds=delay), claim_id, member))
        end = start + timedelta(seconds=1)
        while self._pending and self._pending[0][0] < end:
            due, claim_id, member = heapq.heappop(self._pending)
            line = self.factory.claim_adjudicated(due, claim_id, member)
            if adjudicating:
                lines.append(line)
        return sorted(lines)


def derived_rng(seed: int | None, stream: str) -> random.Random:
    """An independent random stream for one part of the traffic, reproducible from ``seed``."""
    return random.Random(None if seed is None else f"{seed}:{stream}")


class Traffic:
    """Background traffic, heartbeats and claim flows, with faults switched on and off.

    Each part draws from its own random stream, so injecting a fault changes
    only the lines that fault adds or removes. The background lines are
    exactly what :func:`normal_second` produces with ``random.Random(seed)``.
    """

    def __init__(
        self,
        seed: int | None = None,
        rate: float = DEFAULT_RATE,
        error_rate: float = DEFAULT_ERROR_RATE,
    ) -> None:
        self.rate = rate
        self.error_rate = error_rate
        self._background = LineFactory(random.Random(seed))
        self._heartbeats = LineFactory(derived_rng(seed, "heartbeats"))
        self._claims = ClaimFlow(LineFactory(derived_rng(seed, "claims")))
        self._faults = LineFactory(derived_rng(seed, "faults"))

    def second(self, start: datetime, elapsed: float, faults: Collection[str] = ()) -> list[str]:
        """Every line for the second beginning at ``start`` with ``faults`` active, sorted."""
        unknown = set(faults) - FAULTS.keys()
        if unknown:
            raise ValueError(f"unknown fault: {', '.join(sorted(unknown))}")
        lines = list(normal_second(self._background, start, elapsed, self.rate, self.error_rate))
        silenced = {SILENCED_SERVICE} if "heartbeat-stop" in faults else set()
        lines += heartbeat_second(self._heartbeats, start, int(elapsed), silenced)
        lines += self._claims.second(start, adjudicating="flow-break" not in faults)
        for kind in sorted(set(faults) & INCIDENTS.keys()):
            lines += incident_second(self._faults, kind, start, INCIDENTS[kind][1])
        return sorted(lines)  # lines start with their timestamp


@dataclass(frozen=True)
class ScheduledFault:
    """A fault active from ``start_s`` for ``duration_s`` seconds into a simulation."""

    kind: str
    start_s: int
    duration_s: int

    def active_at(self, second: int) -> bool:
        """Whether the fault is active during the given second."""
        return self.start_s <= second < self.start_s + self.duration_s


def simulate(
    start: datetime,
    duration_s: int,
    faults: Sequence[ScheduledFault] = (),
    *,
    seed: int | None = None,
    rate: float = DEFAULT_RATE,
    error_rate: float = DEFAULT_ERROR_RATE,
) -> list[str]:
    """Every line of ``duration_s`` seconds of traffic with scheduled faults, in order."""
    traffic = Traffic(seed, rate, error_rate)
    lines: list[str] = []
    for second in range(duration_s):
        active = {f.kind for f in faults if f.active_at(second)}
        lines += traffic.second(start + timedelta(seconds=second), float(second), active)
    return lines


def control_path(log_path: Path) -> Path:
    """The control file next to ``log_path`` that lists faults the generator must apply."""
    return log_path.with_name(log_path.name + ".faults.json")


def read_active_faults(path: Path, now: float) -> frozenset[str]:
    """Faults in the control file that have not expired at ``now`` (epoch seconds).

    A missing or half-written file means no faults: the generator must never
    stop because of it.
    """
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return frozenset()
    if not isinstance(entries, dict):
        return frozenset()
    return frozenset(
        kind
        for kind, until in entries.items()
        if kind in SUPPRESSIONS and isinstance(until, int | float) and until > now
    )


def set_fault(path: Path, kind: str, until: float | None) -> None:
    """Record ``kind`` as active until ``until`` (epoch seconds), or clear it with None."""
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
    partial.replace(path)  # atomic, so the generator never reads half a file


def hold_fault(path: Path, kind: str, duration: float) -> None:
    """Keep a suppression fault active for ``duration`` seconds, then clear it."""
    set_fault(path, kind, time.time() + duration)
    try:
        time.sleep(duration)
    finally:
        set_fault(path, kind, None)


SecondProducer = Callable[[datetime, float], Iterable[str]]


def write_forever(path: Path, produce_second: SecondProducer, duration: float | None) -> None:
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
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT, help="log file to append to")
    parser.add_argument("--rate", type=float, help="lines per second (default 40, or per incident)")
    parser.add_argument("--error-rate", type=float, default=DEFAULT_ERROR_RATE)
    parser.add_argument(
        "--incident",
        choices=sorted(FAULTS),
        help="inject a fault: write its lines, or signal the running generator to drop lines",
    )
    parser.add_argument("--duration", type=float, help="seconds to run (default: forever)")
    parser.add_argument("--seed", type=int, help="random seed for reproducible output")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    args = parse_args(sys.argv[1:] if argv is None else argv)
    factory = LineFactory(random.Random(args.seed))

    if args.incident in SUPPRESSIONS:
        duration = args.duration or 45.0
        control = control_path(args.out)
        print(
            f"injecting {args.incident} ({SUPPRESSIONS[args.incident]}) for {duration:.0f}s "
            f"via {control}; needs the normal-traffic generator running",
            flush=True,
        )
        with contextlib.suppress(KeyboardInterrupt):
            hold_fault(control, args.incident, duration)
        return 0

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
            lambda start, _elapsed: incident_second(factory, args.incident, start, rate),
            duration,
        )
        return 0

    rate = args.rate or DEFAULT_RATE
    traffic = Traffic(args.seed, rate, args.error_rate)
    control = control_path(args.out)
    print(
        f"writing ~{rate:.0f} lines/s of normal traffic, heartbeats and claim flows to "
        f"{args.out} (Ctrl+C to stop)",
        flush=True,
    )
    with contextlib.suppress(KeyboardInterrupt):
        write_forever(
            args.out,
            lambda start, elapsed: traffic.second(
                start, elapsed, read_active_faults(control, time.time())
            ),
            args.duration,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
