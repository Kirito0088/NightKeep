"""F-14: containment must not silence the Watcher's liveness heartbeat.

On INCIDENT, Judge locks ``share/`` read-only. The watcher agent rewrites
``share/.watcher-heartbeat`` atomically (temp file + os.replace); on
Windows, os.replace() against a read-only destination fails, the agent
exits, and the Vault then sees silence -- a manufactured S6 on top of a
real attack. ``make_read_only`` must therefore spare the heartbeat (and
its temp sibling) while still locking every real PDS file.

These tests use the real filesystem, the real ``write_heartbeat``, and a
real watcher agent subprocess. No heartbeat writer is mocked.
"""

import json
import stat
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import pytest

from nightkeep.habit import Habit
from nightkeep.judge import Judge
from nightkeep.judge import _actions
from nightkeep.types import (
    HEARTBEAT_FILENAME,
    INCIDENT,
    MODIFIED,
    Event,
    JobRun,
)
from nightkeep.watcher.__main__ import heartbeat_path, write_heartbeat

AT = datetime(2026, 9, 22, 3, 41, 12)
TRAPS = ("share/exports/epos_day_end_20240101.csv",)
REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def root(tmp_path):
    for folder in ("data", "share/exports", "share/backups"):
        (tmp_path / folder).mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture
def habit(tmp_path):
    return Habit(tmp_path / "habit.db", 3.0, 3, 0.10)


@pytest.fixture
def judge(root, habit):
    made = Judge(
        root=root,
        habit=habit,
        odd_score=0.5,
        rename_burst=10,
        entropy_jump=1.5,
        entropy_floor=7.0,
        recovery_commands=("vssadmin delete shadows", "wbadmin delete catalog"),
        trap_files=TRAPS,
    )
    made.plant_traps()
    yield made
    made.undo()


def trigger_incident(judge):
    """A trap file changed: S2 fires, INCIDENT needs no corroboration."""
    verdict = judge.verdict(
        JobRun(
            job="ransomware",
            identity="evil|update_helper.exe|deadbeef",
            started_at=AT,
            finished_at=AT,
            events=(Event(path=TRAPS[0], kind=MODIFIED, at=AT, size=1),),
            sim_started_at=AT,
            day_no=8,
        )
    )
    assert verdict.level == INCIDENT
    return verdict


def heartbeat_written_at(path: Path) -> datetime:
    return datetime.fromisoformat(json.loads(path.read_text())["written_at"])


# --- the exclusion itself -------------------------------------------------

def test_incident_still_locks_ordinary_files_in_share_and_data(judge, root):
    """The heartbeat exclusion must not weaken containment broadly."""
    victims = [
        root / "share/exports/epos_day_end_20240920.csv",
        root / "share/backups/db_backup_20240920.sqlite",
        root / "data/pds.db",
    ]
    for victim in victims:
        victim.write_bytes(b"ration card data" * 100)
    heartbeat = heartbeat_path(root)
    write_heartbeat(heartbeat)

    trigger_incident(judge)

    for victim in victims:
        assert _actions.is_read_only(victim), f"{victim} was not locked"
    # And the lock is real: the write bit is gone from the mode.
    for victim in victims:
        assert not victim.stat().st_mode & stat.S_IWRITE


def test_heartbeat_and_its_tmp_sibling_survive_containment(judge, root):
    heartbeat = heartbeat_path(root)
    write_heartbeat(heartbeat)
    tmp_sibling = heartbeat.with_name(heartbeat.name + ".tmp")
    tmp_sibling.write_text("partial atomic write", encoding="utf-8")

    trigger_incident(judge)

    for path in (heartbeat, tmp_sibling):
        assert not _actions.is_read_only(path), f"{path.name} was locked"
        assert path.stat().st_mode & stat.S_IWRITE


def test_real_write_heartbeat_succeeds_after_containment(judge, root):
    """The exact call the agent makes, after the exact lock Judge applies."""
    heartbeat = heartbeat_path(root)
    write_heartbeat(heartbeat)
    before = heartbeat_written_at(heartbeat)

    trigger_incident(judge)
    write_heartbeat(heartbeat)  # must not raise

    assert heartbeat_written_at(heartbeat) > before


# --- the real agent, end to end --------------------------------------------

def test_real_watcher_agent_survives_incident(judge, root):
    """Alive is not enough: the heartbeat must keep moving after INCIDENT.

    Proves the agent is still functioning, not merely a process that has
    not been reaped yet.
    """
    proc = subprocess.Popen(
        [sys.executable, "-m", "nightkeep.watcher", "--run",
         "--root", str(root), "--interval", "0.5"],
        cwd=REPO_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        heartbeat = heartbeat_path(root)
        deadline = time.time() + 15
        while time.time() < deadline:
            if heartbeat.exists():
                try:
                    before = heartbeat_written_at(heartbeat)
                    break
                except (json.JSONDecodeError, KeyError, ValueError):
                    pass
            time.sleep(0.1)
        else:
            pytest.fail("watcher agent never wrote its first heartbeat")

        trigger_incident(judge)

        # Several heartbeat intervals pass under containment.
        time.sleep(2.5)

        assert proc.poll() is None, "watcher agent died after containment"
        after = heartbeat_written_at(heartbeat)
        assert after > before, (
            "watcher process is alive but its heartbeat stopped moving"
        )
        # The file the live agent keeps replacing was never locked.
        assert not _actions.is_read_only(heartbeat)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
