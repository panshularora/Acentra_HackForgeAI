import asyncio
from pathlib import Path

import pytest

from app.ingest.tailer import FileTailer


def append(path: Path, text: str) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)


@pytest.fixture
def log_file(tmp_path: Path) -> Path:
    path = tmp_path / "app.log"
    path.write_text("")
    return path


def test_reads_appended_lines(log_file: Path) -> None:
    tailer = FileTailer(log_file, from_start=True)
    append(log_file, "one\ntwo\n")

    assert tailer.read_lines() == ["one", "two"]
    append(log_file, "three\n")
    assert tailer.read_lines() == ["three"]
    assert tailer.read_lines() == []


def test_starts_at_end_of_existing_file_by_default(log_file: Path) -> None:
    append(log_file, "old history\n")
    tailer = FileTailer(log_file)

    assert tailer.read_lines() == []
    append(log_file, "fresh\n")
    assert tailer.read_lines() == ["fresh"]


def test_from_start_reads_existing_content(log_file: Path) -> None:
    append(log_file, "old history\n")

    assert FileTailer(log_file, from_start=True).read_lines() == ["old history"]


def test_partial_line_is_held_until_newline(log_file: Path) -> None:
    tailer = FileTailer(log_file, from_start=True)
    append(log_file, "2026-09-28T13:00:00Z ERROR claim-")

    assert tailer.read_lines() == []
    append(log_file, "adjudication msg=timeout\nnext")
    assert tailer.read_lines() == ["2026-09-28T13:00:00Z ERROR claim-adjudication msg=timeout"]


def test_offset_tracks_bytes_read(log_file: Path) -> None:
    tailer = FileTailer(log_file, from_start=True)
    append(log_file, "abc\n")
    tailer.read_lines()

    assert tailer.offset == 4


def test_truncation_restarts_from_beginning(log_file: Path) -> None:
    tailer = FileTailer(log_file, from_start=True)
    append(log_file, "a long first line\nanother line\n")
    tailer.read_lines()

    log_file.write_text("")  # truncate in place, same inode
    append(log_file, "after\n")

    assert tailer.read_lines() == ["after"]
    assert tailer.offset == len("after\n")


def test_rotation_drains_old_file_then_follows_new_one(log_file: Path) -> None:
    tailer = FileTailer(log_file, from_start=True)
    append(log_file, "before rotation\n")
    assert tailer.read_lines() == ["before rotation"]

    append(log_file, "last words\n")
    log_file.rename(log_file.with_suffix(".log.1"))
    log_file.write_text("new file\n")

    assert tailer.read_lines() == ["last words", "new file"]
    append(log_file, "more\n")
    assert tailer.read_lines() == ["more"]


def test_waits_for_missing_file(tmp_path: Path) -> None:
    path = tmp_path / "later.log"
    tailer = FileTailer(path)

    assert tailer.read_lines() == []
    path.write_text("first\n")
    assert tailer.read_lines() == ["first"]


def test_invalid_utf8_is_replaced_not_raised(log_file: Path) -> None:
    tailer = FileTailer(log_file, from_start=True)
    with log_file.open("ab") as handle:
        handle.write(b"bad \xff byte\n")

    assert tailer.read_lines() == ["bad \ufffd byte"]


async def test_follow_yields_batches_as_the_file_grows(log_file: Path) -> None:
    tailer = FileTailer(log_file, poll_interval=0.01, from_start=True)
    stream = tailer.follow()

    append(log_file, "x\n")
    first = await asyncio.wait_for(anext(stream), timeout=1)
    append(log_file, "y\nz\n")
    second = await asyncio.wait_for(anext(stream), timeout=1)
    await stream.aclose()

    assert first == ["x"]
    assert second == ["y", "z"]
