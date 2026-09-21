"""EventLog.read_all() must survive a torn trailing write.

The watcher agent (a separate process) appends JSON lines while the live
loop polls the log. If the reader catches the final line mid-write --
present but not yet newline-terminated, possibly torn mid-record -- the
old code let json.JSONDecodeError escape and crash the live attack loop.

The intended design is narrow: only the final *unterminated* line is
treated as possibly-in-flight. Complete (newline-terminated) lines that
are malformed still fail loudly.
"""

import json
from datetime import datetime, timezone

import pytest

from nightkeep.demo_run import _EventCursor
from nightkeep.types import MODIFIED, Event
from nightkeep.watcher._log import EventLog

AT = datetime(2026, 9, 22, 3, 41, 12, tzinfo=timezone.utc)


def _log(tmp_path):
    return EventLog(tmp_path / "watcher.jsonl")


def _event(path, n=0):
    return Event(path=path, kind=MODIFIED, at=AT, size=100 + n)


def _write_raw(log, text):
    """Bypass append(): write bytes exactly as given, like a writer
    caught mid-record would leave them."""
    with log.path.open("a", encoding="utf-8") as handle:
        handle.write(text)


def _record_line(path):
    return (
        json.dumps(
            {
                "path": path,
                "kind": MODIFIED,
                "at": AT.isoformat(),
                "pid": 4242,
                "process": "simulator",
                "old_path": None,
                "size": 321,
            }
        )
    )


def test_complete_records_parse_normally(tmp_path):
    log = _log(tmp_path)
    for name in ("share/a.csv", "share/b.csv"):
        log.append(_event(name))
    events = log.read_all()
    assert [e.path for e in events] == ["share/a.csv", "share/b.csv"]
    assert all(isinstance(e.at, datetime) for e in events)
    assert [e.size for e in events] == [100, 100]


def test_partial_trailing_line_does_not_crash(tmp_path):
    log = _log(tmp_path)
    log.append(_event("share/a.csv"))
    log.append(_event("share/b.csv"))
    # In-flight write: a torn prefix with no trailing newline.
    _write_raw(log, _record_line("share/c.csv")[:40])

    events = log.read_all()  # must not raise

    # Valid earlier records remain available; the partial line is not
    # fabricated into a fake event.
    assert [e.path for e in events] == ["share/a.csv", "share/b.csv"]


def test_partial_line_completed_later_becomes_readable(tmp_path):
    log = _log(tmp_path)
    log.append(_event("share/a.csv"))
    full = _record_line("share/b.csv")
    cut = len(full) // 2
    _write_raw(log, full[:cut])
    assert [e.path for e in log.read_all()] == ["share/a.csv"]

    # The writer's in-flight write lands before the next poll.
    _write_raw(log, full[cut:] + "\n")
    events = log.read_all()
    assert [e.path for e in events] == ["share/a.csv", "share/b.csv"]
    assert events[1].pid == 4242
    assert events[1].size == 321


def test_malformed_complete_line_fails_loudly(tmp_path):
    """A newline-terminated line that is not valid JSON is genuine
    corruption, not an in-flight write: it must raise, not be hidden."""
    log = _log(tmp_path)
    log.append(_event("share/a.csv"))
    _write_raw(log, "this is not json at all\n")

    with pytest.raises(json.JSONDecodeError):
        log.read_all()


def test_malformed_non_final_line_fails_loudly(tmp_path):
    log = _log(tmp_path)
    _write_raw(log, "{broken}\n")
    log.append(_event("share/a.csv"))

    with pytest.raises(json.JSONDecodeError):
        log.read_all()


def test_cursor_survives_torn_write_across_polls(tmp_path):
    """End to end through the live loop's cursor: a torn write is
    skipped on one poll and picked up exactly once when it completes."""
    log = _log(tmp_path)
    cursor = _EventCursor(log)
    log.append(_event("share/a.csv"))
    assert [e.path for e in cursor.drain()] == ["share/a.csv"]

    full = _record_line("share/b.csv")
    cut = len(full) // 2
    _write_raw(log, full[:cut])
    assert cursor.drain() == []  # no crash, no fake event

    _write_raw(log, full[cut:] + "\n")
    drained = cursor.drain()
    assert [e.path for e in drained] == ["share/b.csv"]
    assert cursor.drain() == []  # exactly once


def test_empty_and_whitespace_only_files(tmp_path):
    log = _log(tmp_path)
    assert log.read_all() == ()
    _write_raw(log, "\n")
    assert log.read_all() == ()
    _write_raw(log, "   ")
    assert log.read_all() == ()
