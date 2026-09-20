"""F11: the Watcher agent, Vault S6 liveness, and the killer.

Covers the pieces the demo runner wires together:
- the watcher agent watches the folder AND writes the liveness heartbeat
  on schedule (one process: killing it is killing the agent)
- the Watcher ignores heartbeat writes (no events, no habit, no judge)
- Vault S6: healthy beat -> alive; stale/missing/corrupt -> silent
- the Vault's liveness monitor asks on its own clock every check interval
- the watcher-killer terminates only the marked agent for its demo root
- the killer cannot touch its parent, an unrelated process, or an agent
  for a different root
- the silence threshold genuinely gates detection (no faked instant S6)
- S6 + S7 combine to the vault-side verdict per the design-doc table

Real subprocesses and real timing throughout, with small intervals so the
suite stays fast. Marked slow like the other subprocess tests.
"""

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from nightkeep.simulator import _is_watcher_agent, guard_root, watcher_killer
from nightkeep.types import (
    CLEAN,
    HEARTBEAT_FILENAME,
    INCIDENT,
    NORMAL,
    SUSPECT,
    SUSPICIOUS,
)
from nightkeep.vault import Vault, combined_verdict
from nightkeep.watcher import Watcher
from nightkeep.watcher.__main__ import heartbeat_path, write_heartbeat

pytestmark = pytest.mark.slow

REPO_ROOT = Path(__file__).resolve().parent.parent
DEMO_DIR = REPO_ROOT / "demo"
PYTHON = sys.executable

INTERVAL = 0.2
THRESHOLD = 1.5


def _vault(tmp_path: Path, share: Path, silence: float = THRESHOLD,
           check_interval: float = 0.2) -> Vault:
    return Vault(
        tmp_path / "vault",
        share,
        suspect_entropy=7.0,
        suspect_changed_fraction=0.5,
        suspect_record_drop_fraction=0.02,
        restore_folder_name="restored",
        watcher_silence_seconds=silence,
        liveness_check_interval_seconds=check_interval,
    )


def _spawn_agent(root: Path, interval: float = INTERVAL) -> subprocess.Popen:
    """The watcher agent: watches the folder and heartbeats, one process."""
    proc = subprocess.Popen(
        [
            PYTHON,
            "-m",
            "nightkeep.watcher",
            "--run",
            "--root",
            str(root),
            "--interval",
            str(interval),
        ]
    )
    deadline = time.monotonic() + 30
    while not heartbeat_path(root).exists():
        assert proc.poll() is None, "watcher agent died on startup"
        assert time.monotonic() < deadline, "agent never wrote its first beat"
        time.sleep(0.05)
    return proc


def _stop(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


# -- the watcher agent ----------------------------------------------------


def test_watcher_agent_heartbeats_on_schedule(tmp_path):
    root = tmp_path / "root"
    (root / "share").mkdir(parents=True)
    proc = _spawn_agent(root)
    try:
        first = json.loads(heartbeat_path(root).read_text(encoding="utf-8"))
        assert first["pid"] == proc.pid
        time.sleep(INTERVAL * 3)
        second = json.loads(heartbeat_path(root).read_text(encoding="utf-8"))
        # A later stamp proves periodic updates, not a one-off write.
        assert second["written_at"] > first["written_at"]
    finally:
        _stop(proc)


def test_watcher_agent_is_the_thing_that_watches(tmp_path):
    """The killed process is the agent, not a heartbeat sidecar: while it
    runs it records real file events in its log, and its own heartbeat
    writes never pollute that log."""
    from nightkeep.watcher import event_log_for

    root = tmp_path / "root"
    share = root / "share"
    share.mkdir(parents=True)
    proc = _spawn_agent(root)
    try:
        start = datetime.now(timezone.utc)
        (share / "evidence.txt").write_text("the agent should see this")
        deadline = time.monotonic() + 10
        seen = []
        while time.monotonic() < deadline:
            seen = [
                e for e in event_log_for(root).read_all()
                if e.at >= start and "evidence.txt" in e.path
            ]
            if seen:
                break
            time.sleep(0.2)
        assert seen, "the agent recorded no event for the new file"
        heartbeat_events = [
            e for e in event_log_for(root).read_all()
            if HEARTBEAT_FILENAME in e.path
        ]
        assert heartbeat_events == []
    finally:
        _stop(proc)


def test_watcher_agent_refuses_a_non_positive_interval():
    done = subprocess.run(
        [PYTHON, "-m", "nightkeep.watcher", "--run",
         "--root", "/tmp", "--interval", "0"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert done.returncode == 2


# -- the watcher ignores its own heartbeat ---------------------------------


def test_watcher_ignores_heartbeat_writes(tmp_path):
    root = tmp_path / "root"
    share = root / "share"
    share.mkdir(parents=True)
    watcher = Watcher(root, poll_seconds=1, settle_seconds=0.1).start()
    try:
        start = datetime.now(timezone.utc)
        for _ in range(4):
            write_heartbeat(heartbeat_path(root))
            time.sleep(0.3)
        events = watcher.events_between(
            start, datetime.now(timezone.utc) + timedelta(seconds=1)
        )
        heartbeat_events = [
            e for e in events if HEARTBEAT_FILENAME in e.path
        ]
        assert heartbeat_events == []
    finally:
        watcher.stop()


# -- vault S6 ---------------------------------------------------------------


def test_healthy_heartbeat_is_alive(tmp_path):
    share = tmp_path / "share"
    share.mkdir()
    write_heartbeat(heartbeat_path(tmp_path))
    liveness = _vault(tmp_path, share).check_watcher_liveness()
    assert liveness.alive is True
    assert liveness.last_seen is not None
    assert "S6" not in liveness.reason


def test_stale_heartbeat_is_s6(tmp_path):
    share = tmp_path / "share"
    share.mkdir()
    stale = {
        "written_at": (datetime.now(timezone.utc)
                       - timedelta(seconds=THRESHOLD * 10)).isoformat(),
        "pid": 1234,
    }
    heartbeat_path(tmp_path).write_text(json.dumps(stale), encoding="utf-8")
    liveness = _vault(tmp_path, share).check_watcher_liveness()
    assert liveness.alive is False
    assert "S6" in liveness.reason


def test_missing_heartbeat_is_s6(tmp_path):
    share = tmp_path / "share"
    share.mkdir()
    liveness = _vault(tmp_path, share).check_watcher_liveness()
    assert liveness.alive is False
    assert "S6" in liveness.reason


def test_corrupt_heartbeat_is_s6(tmp_path):
    share = tmp_path / "share"
    share.mkdir()
    heartbeat_path(tmp_path).write_text("not json at all", encoding="utf-8")
    liveness = _vault(tmp_path, share).check_watcher_liveness()
    assert liveness.alive is False
    assert "S6" in liveness.reason


def test_silence_is_detected_after_the_threshold_not_before(tmp_path):
    """The threshold genuinely gates S6: right after the kill the watcher
    still reads alive; only once the silence outlasts the threshold does
    the Vault call it. Nothing is faked."""
    root = DEMO_DIR / "test_silence_timing"
    root.mkdir(parents=True, exist_ok=True)
    (root / "share").mkdir(exist_ok=True)
    agent = _spawn_agent(root)
    vault = _vault(tmp_path, root / "share")
    try:
        assert vault.check_watcher_liveness().alive is True
        report = watcher_killer(root)
        assert report.killed_pids == (agent.pid,)
        agent.wait(timeout=10)
        # Just killed: the last beat is seconds old, under the threshold.
        assert vault.check_watcher_liveness().alive is True
        time.sleep(THRESHOLD + 1.0)
        liveness = vault.check_watcher_liveness()
        assert liveness.alive is False
        assert "S6" in liveness.reason
    finally:
        _stop(agent)
        shutil.rmtree(root, ignore_errors=True)


# -- the vault asks on its own clock ------------------------------------------


def test_vault_liveness_monitor_checks_periodically(tmp_path):
    """The design doc's "the Vault checks every 10 s": the monitor asks on
    its own interval, records the latest answer, and reports alive/silent
    transitions through the on-change hook."""
    share = tmp_path / "share"
    share.mkdir()
    vault = _vault(tmp_path, share, silence=THRESHOLD, check_interval=0.2)
    transitions = []
    vault.start_liveness_monitor(on_change=transitions.append)
    try:
        # No heartbeat yet: the monitor's own checks call it silent.
        deadline = time.monotonic() + 5
        while vault.last_liveness is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert vault.last_liveness is not None
        assert vault.last_liveness.alive is False
        assert vault.liveness_check_count >= 1

        # A fresh beat flips it to alive, and the hook sees the change.
        write_heartbeat(heartbeat_path(tmp_path))
        deadline = time.monotonic() + 5
        while not transitions and time.monotonic() < deadline:
            time.sleep(0.05)
        assert vault.last_liveness.alive is True
        assert [t.alive for t in transitions] == [True]

        # Starting twice does not start a second monitor.
        before = vault.liveness_check_count
        vault.start_liveness_monitor()
        time.sleep(0.5)
        assert vault.liveness_check_count - before < 10
    finally:
        vault.stop_liveness_monitor()
    # Stopped: no more checks accumulate.
    frozen = vault.liveness_check_count
    time.sleep(0.5)
    assert vault.liveness_check_count == frozen
    # Stopping twice is safe.
    vault.stop_liveness_monitor()


def test_vault_rejects_a_non_positive_check_interval(tmp_path):
    from nightkeep.vault import VaultError

    share = tmp_path / "share"
    share.mkdir()
    with pytest.raises(VaultError):
        _vault(tmp_path, share, check_interval=0)


# -- the killer only kills what is marked ------------------------------------


def test_killer_matches_marker_plus_exact_root():
    root = "/repo/demo/district"
    assert _is_watcher_agent(
        ["python", "-m", "nightkeep.watcher", "--run",
         "--root", root, "--interval", "10"],
        root,
    )
    # Missing the flag: not an agent.
    assert not _is_watcher_agent(
        ["python", "-m", "nightkeep.watcher", "--root", root], root
    )
    # A different module: not an agent.
    assert not _is_watcher_agent(
        ["python", "-m", "nightkeep.simulator", "--run",
         "--root", root],
        root,
    )
    # A sibling root is not this root: substring must not match.
    assert not _is_watcher_agent(
        ["python", "-m", "nightkeep.watcher", "--run",
         "--root", root + "2", "--interval", "10"],
        root,
    )
    # A different root entirely: not this agent.
    assert not _is_watcher_agent(
        ["python", "-m", "nightkeep.watcher", "--run",
         "--root", "/somewhere/else", "--interval", "10"],
        root,
    )


def test_killer_terminates_only_the_marked_agent_for_its_root():
    target_root = DEMO_DIR / "test_killer_target"
    other_root = DEMO_DIR / "test_killer_other"
    for root in (target_root, other_root):
        root.mkdir(parents=True, exist_ok=True)
        (root / "share").mkdir(exist_ok=True)
    target = _spawn_agent(target_root)
    other = _spawn_agent(other_root)
    bystander = subprocess.Popen(["sleep", "30"])
    try:
        report = watcher_killer(target_root)
        assert report.variant == "watcher-killer"
        assert report.killed_pids == (target.pid,)
        assert target.wait(timeout=10) is not None
        # The other root's agent, the bystander and this test process
        # are all untouched.
        assert other.poll() is None
        assert bystander.poll() is None
        assert os.getpid() not in report.killed_pids
    finally:
        _stop(target)
        _stop(other)
        _stop(bystander)
        shutil.rmtree(target_root, ignore_errors=True)
        shutil.rmtree(other_root, ignore_errors=True)


def test_killer_with_no_agent_kills_nothing():
    root = DEMO_DIR / "test_killer_empty"
    root.mkdir(parents=True, exist_ok=True)
    try:
        report = watcher_killer(root)
        assert report.killed_pids == ()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_killer_stays_inside_the_demo_boundary(tmp_path):
    with pytest.raises(Exception):
        watcher_killer(tmp_path / "outside-demo")
    # guard_root is what enforces it; the killer never skips that call.
    assert guard_root(DEMO_DIR).is_dir()


# -- S6 + S7 combine per the design-doc table ---------------------------------


def test_combined_verdict_follows_the_design_doc_table():
    from nightkeep.types import WatcherLiveness

    now = datetime.now(timezone.utc)
    alive = WatcherLiveness(True, now, now, "checked in")
    silent = WatcherLiveness(False, now, now, "S6: silent")

    assert combined_verdict(silent, SUSPECT) == INCIDENT
    assert combined_verdict(silent, CLEAN) == SUSPICIOUS
    assert combined_verdict(alive, SUSPECT) == SUSPICIOUS
    assert combined_verdict(alive, CLEAN) == NORMAL
