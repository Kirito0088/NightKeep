"""Process attribution: the watcher is never the writer; roots match robustly.

Every behavioral test here uses real subprocesses -- attribution is about
what psutil actually sees, and mocking psutil would prove nothing about
the command-line markers. The unit tests at the bottom pin the matching
helpers directly, including the Windows drive-letter folding that cannot
be exercised on Linux any other way.
"""

from __future__ import annotations

import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from nightkeep.watcher._processes import (
    ProcessPoll,
    _fold,
    _is_watcher_agent,
    _mentions_root,
)

_SLEEP = "import time; time.sleep(60)"


def _sleeper(*extra_args: str) -> subprocess.Popen:
    """A real process whose argv we fully control."""
    return subprocess.Popen(
        [sys.executable, "-c", _SLEEP, *extra_args],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _stop(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def _start_real_agent(root: Path) -> subprocess.Popen:
    """The actual watcher agent, argv and all -- not a fake."""
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "nightkeep.watcher",
            "--run",
            "--root",
            str(root),
            "--interval",
            "0.5",
            "--poll-seconds",
            "0.2",
            "--settle-seconds",
            "0.2",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    beat = root / "share" / ".watcher-heartbeat"
    deadline = time.monotonic() + 30
    while not beat.exists():
        assert proc.poll() is None, "the watcher agent died on startup"
        assert time.monotonic() < deadline, "no heartbeat from the agent"
        time.sleep(0.05)
    return proc


def _sighted_pids(poll: ProcessPoll) -> set[int]:
    return {sighting.pid for sighting in poll._sightings}


def test_watcher_agent_is_never_a_writer_candidate(tmp_path: Path):
    """The audit's bug: the agent's own argv mentions the root."""
    agent = _start_real_agent(tmp_path)
    sim = _sleeper("--root", str(tmp_path))
    try:
        poll = ProcessPoll(root=str(tmp_path), poll_seconds=0.1)
        poll.poll_once()
        pids = _sighted_pids(poll)
        assert sim.pid in pids, "the simulator must still be attributed"
        assert agent.pid not in pids, (
            "the watcher agent must never be a writer candidate")
    finally:
        _stop(sim)
        _stop(agent)


def test_attack_with_watcher_and_simulator_resolves_to_the_simulator(
    tmp_path: Path,
):
    """With both alive, the event's pid is the simulator's -- always."""
    agent = _start_real_agent(tmp_path)
    sim = _sleeper("--root", str(tmp_path))
    try:
        poll = ProcessPoll(root=str(tmp_path), poll_seconds=0.1)
        poll.poll_once()
        writer = poll.writer_at(datetime.now(timezone.utc))
        assert writer is not None
        assert writer.pid == sim.pid
    finally:
        _stop(sim)
        _stop(agent)


def test_simulator_process_is_attributed(tmp_path: Path):
    sim = _sleeper("--root", str(tmp_path))
    try:
        poll = ProcessPoll(root=str(tmp_path), poll_seconds=0.1)
        poll.poll_once()
        writer = poll.writer_at(datetime.now(timezone.utc))
        assert writer is not None and writer.pid == sim.pid
    finally:
        _stop(sim)


def test_legitimate_job_is_still_attributed(tmp_path: Path):
    """A normal job script with --root must keep working after the change."""
    script = tmp_path / "nightly_export.py"
    script.write_text("import time; time.sleep(60)\n", encoding="utf-8")
    job = subprocess.Popen(
        [sys.executable, str(script), "--root", str(tmp_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        poll = ProcessPoll(root=str(tmp_path), poll_seconds=0.1)
        poll.poll_once()
        writer = poll.writer_at(datetime.now(timezone.utc))
        assert writer is not None and writer.pid == job.pid
    finally:
        _stop(job)


def test_relative_root_spelling_is_attributed(
    tmp_path: Path, monkeypatch,
):
    """A caller launched with a relative --root no longer degrades to None."""
    root = tmp_path / "district"
    root.mkdir()
    monkeypatch.chdir(tmp_path)
    sim = _sleeper("--root", "district")
    try:
        poll = ProcessPoll(root="district", poll_seconds=0.1)
        poll.poll_once()
        writer = poll.writer_at(datetime.now(timezone.utc))
        assert writer is not None and writer.pid == sim.pid
    finally:
        _stop(sim)


def test_sibling_directory_is_not_attributed(tmp_path: Path):
    """.../district2 must never claim to be .../district."""
    root = tmp_path / "district"
    root.mkdir()
    other = _sleeper("--root", str(tmp_path / "district2"))
    try:
        poll = ProcessPoll(root=str(root), poll_seconds=0.1)
        poll.poll_once()
        assert other.pid not in _sighted_pids(poll)
    finally:
        _stop(other)


def test_watcher_markers_require_both_exact_elements():
    assert _is_watcher_agent(
        ("python", "-m", "nightkeep.watcher", "--run", "--root", "/x"))
    assert not _is_watcher_agent(("python", "-m", "nightkeep.watcher"))
    assert not _is_watcher_agent(("python", "--run", "--root", "/x"))
    # A folder that merely contains the text is not the agent.
    assert not _is_watcher_agent(
        ("python", "/data/nightkeep.watcher/log", "--root", "/x"))


def test_mixed_case_windows_drive_letter_matches():
    """Windows folding, pinned directly: untestable on Linux otherwise."""
    spellings = (_fold("C:\\Demo\\District", _nt=True),)
    assert _mentions_root(("c:/demo/district",), spellings, _nt=True)
    assert _mentions_root(
        ("C:\\DEMO\\DISTRICT\\share\\exports\\a.csv",), spellings, _nt=True)
    assert not _mentions_root(("c:/demo/district2",), spellings, _nt=True)
    assert not _mentions_root(("c:/other/district",), spellings, _nt=True)


def test_a_new_writer_is_not_blamed_on_the_last_job_that_exited(tmp_path: Path):
    """The newest sighting outlives its process until the next poll.

    Seen live on Windows: the last night job was sighted, exited, and the
    simulator's first events (before the next poll) were blamed on the dead
    job's pid, so the Judge tried to pause a process that no longer existed.
    A sighting whose process has exited must not name a new writer.
    """
    from nightkeep.watcher import Watcher

    (tmp_path / "share").mkdir()
    job = _sleeper("--root", str(tmp_path))
    # A background poll far in the future: only the start-up sweep and the
    # watcher's own fallback sweep can see anybody.
    watcher = Watcher(tmp_path, poll_seconds=600, settle_seconds=0.2).start()
    try:
        assert job.pid in _sighted_pids(watcher._poll)
        _stop(job)

        target = tmp_path / "share" / "records.csv"
        writer = subprocess.Popen(
            [sys.executable, "-c",
             "import sys, time; time.sleep(0.5); "
             "open(sys.argv[1], 'w').write('x'); time.sleep(60)",
             str(target), "--root", str(tmp_path)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.monotonic() + 20
            events = []
            while not events and time.monotonic() < deadline:
                time.sleep(0.1)
                events = [e for e in watcher.events_since(
                    datetime(2000, 1, 1, tzinfo=timezone.utc))
                    if e.path == "share/records.csv"]
            assert events, "the write was never seen"
            assert events[0].pid == writer.pid, (
                f"blamed on pid {events[0].pid}; the dead job was {job.pid}")
        finally:
            _stop(writer)
    finally:
        watcher.stop()
        _stop(job)
