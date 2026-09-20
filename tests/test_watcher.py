"""The watcher: does it see what happened, and does it stay out of the truth.

These tests write real files and run a real subprocess, because the thing
under test is watchdog and psutil doing their actual jobs. They are marked
slow where they have to wait for the filesystem.
"""

import subprocess
import sys
import time
from datetime import datetime, timezone

import pytest

from nightkeep.types import CREATED, DELETED, MODIFIED, RENAMED
from nightkeep.watcher import Watcher
from nightkeep.watcher._log import LOG_NAME, EventLog
from nightkeep.watcher._processes import ProcessPoll, Sighting


def settle(watcher: Watcher, expected: int, timeout: float = 8.0) -> list:
    """Wait until at least `expected` events have landed, then return them."""
    deadline = time.monotonic() + timeout
    start = datetime(1970, 1, 1, tzinfo=timezone.utc)
    while time.monotonic() < deadline:
        events = watcher.events_since(start)
        if len(events) >= expected:
            time.sleep(0.2)
            return watcher.events_since(start)
        time.sleep(0.05)
    return watcher.events_since(start)


@pytest.fixture
def root(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "share" / "exports").mkdir(parents=True)
    (tmp_path / "logs" / "_truth").mkdir(parents=True)
    return tmp_path


@pytest.mark.slow
def test_it_sees_a_file_created_and_says_where(root):
    with Watcher(root, poll_seconds=0.2) as watcher:
        (root / "share" / "exports" / "epos_day_end_20260922.csv").write_text("a,b\n")
        events = settle(watcher, 1)

    paths = {event.path for event in events}
    assert "share/exports/epos_day_end_20260922.csv" in paths
    assert {event.kind for event in events} <= {CREATED, MODIFIED}


@pytest.mark.slow
def test_it_sees_a_rename_and_keeps_the_old_name(root):
    original = root / "share" / "exports" / "quota.csv"
    original.write_text("a,b\n")
    time.sleep(0.3)

    with Watcher(root, poll_seconds=0.2) as watcher:
        original.rename(original.with_suffix(".locked"))
        events = settle(watcher, 1)

    renames = [event for event in events if event.kind == RENAMED]
    assert renames, f"no rename seen, got {[e.kind for e in events]}"
    assert renames[0].path.endswith(".locked")
    assert renames[0].old_path == "share/exports/quota.csv"


@pytest.mark.slow
def test_it_sees_a_delete(root):
    doomed = root / "share" / "exports" / "old.csv"
    doomed.write_text("x\n")
    time.sleep(0.3)

    with Watcher(root, poll_seconds=0.2) as watcher:
        doomed.unlink()
        events = settle(watcher, 1)

    assert any(event.kind == DELETED for event in events)


@pytest.mark.slow
def test_it_never_records_anything_under_the_truth_folder(root):
    """Rule: nothing under watcher/ may see logs/_truth/.

    Not even as a filename. A job writes its truth line while the watcher is
    running, and the watcher must come back with nothing.
    """
    with Watcher(root, poll_seconds=0.2) as watcher:
        (root / "logs" / "_truth" / "nightly_export.jsonl").write_text('{"job": "x"}\n')
        (root / "share" / "exports" / "real.csv").write_text("a\n")
        events = settle(watcher, 1)

    assert not any("_truth" in event.path for event in events)
    assert any(event.path == "share/exports/real.csv" for event in events)


@pytest.mark.slow
def test_it_does_not_watch_its_own_log(root):
    """The log lives inside the watched folder, so this would never end."""
    with Watcher(root, poll_seconds=0.2) as watcher:
        (root / "share" / "exports" / "one.csv").write_text("a\n")
        settle(watcher, 1)
        events = watcher.events_since(datetime(1970, 1, 1, tzinfo=timezone.utc))

    assert not any(LOG_NAME in event.path for event in events)


@pytest.mark.slow
def test_it_attributes_a_file_to_the_process_that_wrote_it(root):
    """A real subprocess, pointed at the root, writing a real file."""
    script = root / "writer.py"
    # chr(10) rather than an escape: this source is written into another
    # file and run by another interpreter, and one layer of escaping is
    # already one too many.
    # The child script is written with chr(10) rather than an escape:
    # this source passes through two interpreters, and one layer of
    # escaping is already one too many.
    script.write_text(
        "import sys, pathlib, time\n"
        "root = pathlib.Path(sys.argv[sys.argv.index('--root') + 1])\n"
        # A real job takes seconds, not microseconds. Holding here is
        # what makes this a test of attribution rather than of luck.
        "time.sleep(0.6)\n"
        "(root / 'share' / 'exports' / 'written_by_job.csv')"
        ".write_text('a,b' + chr(10))\n"
        "time.sleep(0.3)\n"
    )

    with Watcher(root, poll_seconds=0.2) as watcher:
        subprocess.run(
            [sys.executable, str(script), "--root", str(root)], check=True
        )
        events = settle(watcher, 1)

    written = [e for e in events if e.path.endswith("written_by_job.csv")]
    assert written, "the file the subprocess wrote was never seen"
    assert written[0].pid is not None
    assert written[0].process is not None


def test_events_since_is_inclusive_of_its_own_moment(root):
    watcher = Watcher(root, poll_seconds=5)
    moment = datetime.now(timezone.utc)
    watcher._events.append(
        __import__("nightkeep.types", fromlist=["Event"]).Event(
            path="share/exports/a.csv", kind=CREATED, at=moment
        )
    )
    assert len(watcher.events_since(moment)) == 1


def test_a_watcher_that_never_started_is_not_alive(root):
    assert not Watcher(root).is_alive()


def test_the_log_round_trips_an_event(root, tmp_path):
    from nightkeep.types import Event

    log = EventLog(tmp_path / "logs" / LOG_NAME)
    written = Event(
        path="share/exports/a.csv",
        kind=MODIFIED,
        at=datetime(2026, 9, 22, 3, 41, 12, tzinfo=timezone.utc),
        pid=4242,
        process="python.exe",
        size=1234,
    )
    log.append(written)
    assert log.read_all() == (written,)


def test_the_log_only_ever_appends(root, tmp_path):
    from nightkeep.types import Event

    log = EventLog(tmp_path / "logs" / LOG_NAME)
    at = datetime(2026, 9, 22, 3, 41, 12, tzinfo=timezone.utc)
    for index in range(3):
        log.append(Event(path=f"a{index}.csv", kind=CREATED, at=at))
    assert [event.path for event in log.read_all()] == ["a0.csv", "a1.csv", "a2.csv"]


def test_the_poll_returns_nothing_rather_than_guessing_a_writer():
    """An unattributed event is honest. A wrong pid is not."""
    poll = ProcessPoll(root="c:/nowhere", poll_seconds=1)
    assert poll.writer_at(datetime.now(timezone.utc)) is None


def test_the_poll_picks_the_last_process_seen_before_the_moment():
    poll = ProcessPoll(root="c:/demo", poll_seconds=1)
    earlier = datetime(2026, 9, 22, 3, 0, tzinfo=timezone.utc)
    later = datetime(2026, 9, 22, 4, 0, tzinfo=timezone.utc)
    poll._sightings = [
        Sighting(at=earlier, pid=1, name="cscript.exe"),
        Sighting(at=later, pid=2, name="python.exe"),
    ]
    poll._times = [earlier, later]

    at_half_past_three = datetime(2026, 9, 22, 3, 30, tzinfo=timezone.utc)
    assert poll.writer_at(at_half_past_three).pid == 1
    assert poll.writer_at(datetime(2026, 9, 22, 5, 0, tzinfo=timezone.utc)).pid == 2
