"""The live session engine: the district PDS server while the console runs.

Fast tests pin the office's job lock and halt, and the rails the engine
must keep. One slow test runs the real engine as its own process through
the whole manual story: learn, attack on command, contain with the lock
held, restore reported, lock released, clean stop.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psutil
import pytest

from nightkeep import live
from nightkeep import live_protocol as lp
from nightkeep.judge._actions import is_read_only
from nightkeep.mock_pds import _day
from nightkeep.simulator import DEMO_DIR

PACKAGE = Path(__file__).resolve().parent.parent / "nightkeep"
AT = datetime(2026, 9, 23, 1, 30, tzinfo=timezone.utc)


# --- the office: one job at a time, and a halt that holds -------------------


@pytest.fixture
def office(monkeypatch):
    calls = []
    release = threading.Event()

    def fake_launch(job, district_dir, day_no, sim_start, sim_end, *arguments):
        calls.append(job)
        release.wait(timeout=5)

    monkeypatch.setattr(_day, "launch", fake_launch)
    made = live._Office()
    made.start()
    yield made, calls, release
    made.stop()


def test_office_records_each_job_window(office):
    made, calls, release = office
    release.set()
    _day.launch("nightly_export", Path("."), 8, AT, AT)
    assert calls == ["nightly_export"]
    runs = made.take_settled(0.0)
    assert [(run.job, run.day_no) for run in runs] == [("nightly_export", 8)]
    assert made.take_settled(0.0) == []


def test_halt_waits_for_the_running_job_then_refuses_the_next(office):
    made, calls, release = office
    job = threading.Thread(
        target=_day.launch, args=("db_backup", Path("."), 8, AT, AT)
    )
    job.start()
    while made.running is None:
        time.sleep(0.01)

    halted = threading.Event()
    halter = threading.Thread(target=lambda: (made.halt(), halted.set()))
    halter.start()
    time.sleep(0.2)
    assert not halted.is_set(), "halt must wait for the running job"

    release.set()
    job.join(timeout=5)
    halter.join(timeout=5)
    assert halted.is_set()

    with pytest.raises(live._Halted):
        _day.launch("fix_dat", Path("."), 8, AT, AT)
    assert calls == ["db_backup"]


def test_office_stop_puts_the_real_launch_back(monkeypatch):
    original = _day.launch
    made = live._Office()
    made.start()
    assert _day.launch != original
    made.stop()
    assert _day.launch == original


# --- rails -------------------------------------------------------------------


def test_the_live_session_never_names_the_truth_folder():
    """The engine and the files it shares with the console have no reason
    to know where the ground truth is, so they never name it at all."""
    for source in (PACKAGE / "live.py", PACKAGE / "live_protocol.py"):
        assert "_truth" not in source.read_text(encoding="utf-8"), source


def test_session_bookkeeping_sits_outside_the_district():
    """The simulator walks the district and the Judge locks district/data
    and district/share: the session's own files must be out of reach."""
    paths = lp.SessionPaths(Path("demo") / "live")
    for path in (paths.status, paths.report, paths.control, paths.log):
        assert paths.district not in path.parents


def test_protocol_reads_a_missing_or_torn_file_as_empty(tmp_path):
    assert lp.read_json(tmp_path / "nope.json") == {}
    torn = tmp_path / "torn.json"
    torn.write_text('{"phase": "lea', encoding="utf-8")
    assert lp.read_json(torn) == {}
    lp.write_json(torn, {"phase": "learning"})
    assert lp.read_json(torn) == {"phase": "learning"}


# --- the whole manual story, as a real process --------------------------------


def _status(paths: lp.SessionPaths) -> dict:
    return lp.read_json(paths.status)


def _wait_for(paths, predicate, timeout, what):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = _status(paths)
        if status and predicate(status):
            return status
        time.sleep(0.5)
    raise AssertionError(f"timed out waiting for {what}: {_status(paths)}")


@pytest.mark.slow
def test_live_engine_learns_catches_holds_and_releases():
    root = (DEMO_DIR / ".live-tests" / uuid.uuid4().hex).resolve()
    paths = lp.SessionPaths(root)
    paths.engine.mkdir(parents=True)
    lp.write_json(paths.control, lp.empty_control())
    log = open(paths.log, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "nightkeep", "--live-engine",
         "--out-dir", str(root), "--day-seconds", "8"],
        stdout=log, stderr=subprocess.STDOUT,
    )
    try:
        ready = _wait_for(
            paths, lambda s: s.get("attack_readiness") == lp.ATTACK_READY,
            180, "the first clean copy",
        )
        assert ready["phase"] == lp.LEARNING
        assert ready["vault"]["clean_point"]

        control = lp.empty_control()
        control["attack"] = {"id": 1, "variant": "fast"}
        lp.write_json(paths.control, control)
        contained = _wait_for(
            paths, lambda s: s.get("phase") in (lp.CONTAINED, lp.FAILED),
            180, "containment",
        )
        assert contained["phase"] == lp.CONTAINED, contained
        assert contained["attack"]["level"] == "INCIDENT"
        assert contained["lock_held"] is True
        assert contained["attack_readiness"] == lp.ATTACK_ALREADY_RAN
        report = lp.read_json(paths.report)
        assert report["attack"]["snapshot_health"] == "SUSPECT"
        assert report["attack"]["clean_pin_held"] is True
        assert report["attack"]["simulator_process_gone"] is True
        if report["attack"]["simulator_alive_before_containment"]:
            # Caught mid-attack: the Judge must have paused the simulator
            # itself, not a night job that had already exited.
            assert any(action.startswith("paused")
                       for action in report["attack"]["actions"]), report["attack"]
            assert report["attack"]["simulator_stopped_after_containment"] is True
        assert any(
            is_read_only(path)
            for path in (paths.district / "share").rglob("*") if path.is_file()
        )

        control["restored"] = {"id": 1, "ok": True, "snapshot_id": "x",
                               "records_verified": 5000,
                               "records_expected": 5000}
        lp.write_json(paths.control, control)
        recovered = _wait_for(
            paths, lambda s: s.get("phase") == lp.RECOVERED, 60, "the release",
        )
        assert recovered["lock_held"] is False
        assert not any(
            is_read_only(path)
            for path in (paths.district / "share").rglob("*") if path.is_file()
        )

        control["stop"] = True
        lp.write_json(paths.control, control)
        assert proc.wait(timeout=60) == 0
        assert _status(paths)["phase"] == lp.STOPPED
    finally:
        if proc.poll() is None:
            for child in psutil.Process(proc.pid).children(recursive=True):
                child.kill()
            proc.kill()
        log.close()
