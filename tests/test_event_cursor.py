"""The live loop's event cursor: exactly-once consumption of the watcher's log.

The cursor is what lets the demo judge cumulative attack windows without
double-counting events, and without letting pre-attack day-job events leak
into a live window.
"""

from datetime import datetime, timezone

from nightkeep.demo_run import _EventCursor, _is_judgeable
from nightkeep.types import HEARTBEAT_FILENAME, MODIFIED, Event
from nightkeep.watcher._log import EventLog

AT = datetime(2026, 9, 22, 3, 41, 12, tzinfo=timezone.utc)


def _log(tmp_path):
    return EventLog(tmp_path / "watcher.jsonl")


def _event(path, n=0):
    return Event(path=path, kind=MODIFIED, at=AT, size=100 + n)


def test_drain_yields_each_event_exactly_once(tmp_path):
    log = _log(tmp_path)
    cursor = _EventCursor(log)

    log.append(_event("share/a.csv", 1))
    log.append(_event("share/b.csv", 2))
    first = cursor.drain()
    assert [e.path for e in first] == ["share/a.csv", "share/b.csv"]

    # Nothing new: the second drain is empty, not a repeat.
    assert cursor.drain() == []

    log.append(_event("share/c.csv", 3))
    second = cursor.drain()
    assert [e.path for e in second] == ["share/c.csv"]
    assert cursor.drain() == []


def test_rewind_to_end_skips_pre_attack_events(tmp_path):
    log = _log(tmp_path)
    cursor = _EventCursor(log)

    log.append(_event("share/day_job.csv", 1))
    cursor.rewind_to_end()

    log.append(_event("share/attack_1.csv", 2))
    drained = cursor.drain()
    assert [e.path for e in drained] == ["share/attack_1.csv"]


def test_drain_is_oldest_first(tmp_path):
    log = _log(tmp_path)
    cursor = _EventCursor(log)
    for n in range(5):
        log.append(_event(f"share/f{n}.csv", n))
    assert [e.path for e in cursor.drain()] == [f"share/f{n}.csv" for n in range(5)]


def test_is_judgeable_excludes_bookkeeping():
    assert not _is_judgeable(_event(f"share/{HEARTBEAT_FILENAME}"))
    assert not _is_judgeable(_event(f"share/{HEARTBEAT_FILENAME}.tmp"))
    assert not _is_judgeable(_event("logs/watcher.jsonl"))
    assert not _is_judgeable(_event("logs/_truth/nightly_export.jsonl"))
    assert _is_judgeable(_event("share/exports/e.csv"))
    assert _is_judgeable(_event("share/exports/e.csv.locked"))
