import asyncio
from typing import Any, cast

from fastapi import WebSocket

from app.api.ws import ConnectionManager


class FakeSocket:
    def __init__(self, fail: bool = False, delay: float = 0.0) -> None:
        self.sent: list[dict[str, Any]] = []
        self.fail = fail
        self.delay = delay

    async def accept(self) -> None:
        return None

    async def send_json(self, message: dict[str, Any]) -> None:
        await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("connection closed")
        self.sent.append(message)


async def connect(manager: ConnectionManager, socket: FakeSocket) -> None:
    await manager.connect(cast(WebSocket, socket))


async def test_broadcast_reaches_every_client() -> None:
    manager = ConnectionManager()
    first, second = FakeSocket(), FakeSocket()
    await connect(manager, first)
    await connect(manager, second)

    await manager.broadcast("stats", {"total": 1})

    assert first.sent == second.sent == [{"type": "stats", "data": {"total": 1}}]


async def test_failing_client_is_dropped_and_others_still_served() -> None:
    manager = ConnectionManager()
    healthy, broken = FakeSocket(), FakeSocket(fail=True)
    await connect(manager, healthy)
    await connect(manager, broken)

    await manager.broadcast("alert", {"id": "a1"})

    assert manager.client_count == 1
    assert healthy.sent == [{"type": "alert", "data": {"id": "a1"}}]


async def test_slow_client_is_dropped_after_timeout() -> None:
    manager = ConnectionManager(send_timeout=0.01)
    await connect(manager, FakeSocket(delay=1))

    await manager.broadcast("stats", {})

    assert manager.client_count == 0


async def test_broadcast_without_clients_is_a_no_op() -> None:
    await ConnectionManager().broadcast("stats", {})
