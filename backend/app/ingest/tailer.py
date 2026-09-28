"""Follow a growing log file, like ``tail -F``.

The tailer polls the file rather than using inotify so it behaves the same on
Linux, macOS and inside Docker bind mounts. On each poll it:

* reads whatever was appended since the last offset;
* holds back a trailing partial line until its newline arrives, so a writer
  flushing half a line never produces a broken event;
* detects truncation (the file is now shorter than our offset) and restarts
  from the beginning;
* detects rotation (the path now points at a different inode), drains what is
  left of the old file, then switches to the new one from its start.

A missing file is not an error; the tailer waits for it to appear and then
reads it from the start.
"""

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import BinaryIO

READ_CHUNK_BYTES = 1 << 16


class FileTailer:
    """Incrementally reads complete lines appended to ``path``."""

    def __init__(self, path: Path, poll_interval: float = 0.25, from_start: bool = False) -> None:
        self.path = path
        self.poll_interval = poll_interval
        self._from_start = from_start
        self._handle: BinaryIO | None = None
        self._inode: int | None = None
        self._offset = 0
        self._partial = b""

    @property
    def offset(self) -> int:
        """Byte offset of the next unread byte in the current file."""
        return self._offset

    def read_lines(self) -> list[str]:
        """Return all complete lines available right now (possibly none)."""
        stat = self._stat()
        if stat is None:
            # Anything written to a file created after we started is new.
            self._from_start = True
            return []
        if self._handle is None:
            self._open(stat, seek_to_end=not self._from_start)
            self._from_start = True  # later reopens (rotation) always start at 0
            return self._drain()

        if stat.st_ino != self._inode:
            lines = self._drain()
            self._close()
            self._open(stat, seek_to_end=False)
            return lines + self._drain()

        if stat.st_size < self._offset:
            self._restart_after_truncation()
        return self._drain()

    async def follow(self) -> AsyncIterator[list[str]]:
        """Yield batches of new lines forever, polling every ``poll_interval`` seconds."""
        try:
            while True:
                lines = self.read_lines()
                if lines:
                    yield lines
                await asyncio.sleep(self.poll_interval)
        finally:
            self._close()

    def close(self) -> None:
        """Release the file handle."""
        self._close()

    def _stat(self) -> os.stat_result | None:
        try:
            return self.path.stat()
        except FileNotFoundError:
            return None

    def _open(self, stat: os.stat_result, seek_to_end: bool) -> None:
        self._handle = self.path.open("rb")
        self._inode = stat.st_ino
        self._partial = b""
        self._offset = self._handle.seek(0, os.SEEK_END) if seek_to_end else 0

    def _close(self) -> None:
        if self._handle is not None:
            self._handle.close()
        self._handle = None

    def _restart_after_truncation(self) -> None:
        assert self._handle is not None
        self._handle.seek(0)
        self._offset = 0
        self._partial = b""

    def _drain(self) -> list[str]:
        """Read to EOF and split into complete lines, keeping any partial tail."""
        assert self._handle is not None
        chunks = []
        while chunk := self._handle.read(READ_CHUNK_BYTES):
            chunks.append(chunk)
        if not chunks:
            return []
        data = b"".join(chunks)
        self._offset += len(data)
        *complete, self._partial = (self._partial + data).split(b"\n")
        return [line.decode("utf-8", errors="replace").rstrip("\r") for line in complete]
