"""WebSocket fan-out to dashboard clients.

Every message has the shape ``{"type": "stats" | "alert", "data": {...}}``.
Clients only listen. A client that has gone away, or is too slow to accept a
message within ``send_timeout`` seconds, is dropped so it cannot stall the
pipeline for everyone else.
"""

import asyncio
import logging
from typing import Any, Literal

from fastapi import WebSocket

logger = logging.getLogger(__name__)

MessageType = Literal["stats", "alert"]


class ConnectionManager:
    """Tracks connected WebSocket clients and broadcasts to all of them."""

    def __init__(self, send_timeout: float = 2.0) -> None:
        self._clients: set[WebSocket] = set()
        self._send_timeout = send_timeout

    @property
    def client_count(self) -> int:
        """Number of connected clients."""
        return len(self._clients)

    async def connect(self, websocket: WebSocket) -> None:
        """Accept and register a new client."""
        await websocket.accept()
        self._clients.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        """Forget a client (safe to call more than once)."""
        self._clients.discard(websocket)

    async def broadcast(self, message_type: MessageType, data: dict[str, Any]) -> None:
        """Send one message to every client, dropping any that fail."""
        if not self._clients:
            return
        message = {"type": message_type, "data": data}
        clients = list(self._clients)
        results = await asyncio.gather(
            *(self._send(client, message) for client in clients), return_exceptions=True
        )
        for client, result in zip(clients, results, strict=True):
            if isinstance(result, BaseException):
                logger.info("dropping websocket client: %r", result)
                self.disconnect(client)

    async def _send(self, websocket: WebSocket, message: dict[str, Any]) -> None:
        await asyncio.wait_for(websocket.send_json(message), timeout=self._send_timeout)
