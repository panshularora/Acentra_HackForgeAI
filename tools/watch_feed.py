"""Print the live WebSocket feed in a terminal.

Handy for checking the backend without the dashboard, and for the demo::

    python tools/watch_feed.py                      # ws://localhost:8000/ws
    python tools/watch_feed.py --url ws://host:8000/ws --count 20
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import sys
from typing import Any

import websockets


def describe(message: dict[str, Any]) -> str:
    """One readable line per feed message."""
    data = message["data"]
    if message["type"] == "stats":
        score = "warming up" if data["score"] is None else f"score {data['score']:6.2f}"
        severity = data["severity"] or "-"
        return (
            f"stats {data['ts']}  rate {data['error_rate']:.2%} "
            f"({data['errors']}/{data['total']})  {score}  {severity}"
        )
    delivery = data["delivery"]
    return (
        f"ALERT {data['id']} {data['status']:<8} {data['severity']:<8} "
        f"score {data['score']:.1f}  {data['summary']}  "
        f"[sns {delivery['sns']['status']} {delivery['sns']['message_id'] or ''}, "
        f"cloudwatch {delivery['cloudwatch']['status']}]"
    )


async def watch(url: str, count: int | None, raw: bool) -> None:
    """Connect and print messages until ``count`` have arrived (or forever)."""
    async with websockets.connect(url) as socket:
        received = 0
        async for frame in socket:
            message = json.loads(frame)
            print(json.dumps(message) if raw else describe(message), flush=True)
            received += 1
            if count is not None and received >= count:
                return


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(description="Print the ClaimsWatch live feed.")
    parser.add_argument("--url", default="ws://localhost:8000/ws")
    parser.add_argument("--count", type=int, help="exit after this many messages")
    parser.add_argument("--raw", action="store_true", help="print raw JSON messages")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(watch(args.url, args.count, args.raw))
    return 0


if __name__ == "__main__":
    sys.exit(main())
