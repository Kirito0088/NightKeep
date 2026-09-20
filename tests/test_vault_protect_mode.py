"""F11 review: after S6 is detected, the Vault itself responds.

Proves the documented behavior is real, not computed on demand:
- healthy watcher -> killed watcher -> the Vault's own monitor detects
  S6 -> the Vault records SUSPICIOUS, enters Protect mode, and raises
  the alert (state hook + durable alert log)
- S6 + a SUSPECT snapshot -> INCIDENT
- Protect mode holds the last clean point: a CLEAN pull taken while
  protection is active stays CLEAN (Snapshot.health is data-only) but
  does not advance the pin; the pin stays on the pre-S6 snapshot.
- Snapshot.health stays strictly about the data throughout: S6 never
  rewrites it.

Real watcher-agent subprocesses and real timing, with small intervals so
the suite stays fast. Marked slow like the other subprocess tests.
"""

import csv
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from nightkeep.types import (
    CLEAN,
    HEARTBEAT_FILENAME,
    INCIDENT,
    NORMAL,
    SUSPECT,
    SUSPICIOUS,
)
from nightkeep.vault import Vault, combined_verdict
from nightkeep.watcher.__main__ import heartbeat_path, write_heartbeat

pytestmark = pytest.mark.slow

PYTHON = sys.executable
INTERVAL = 0.1  # vault liveness check cadence
SILENCE = 0.6  # S6 threshold
BEAT = 0.2  # agent heartbeat cadence


def _vault(tmp_path: Path, share: Path) -> Vault:
    return Vault(
        tmp_path / "vault",
        share,
        suspect_entropy=7.0,
        suspect_changed_fraction=0.5,
        suspect_record_drop_fraction=0.02,
        restore_folder_name="restored",
        watcher_silence_seconds=SILENCE,
        liveness_check_interval_seconds=INTERVAL,
    )


def _share_with_csv(root: Path) -> Path:
    share = root / "share"
    exports = share / "exports"
    backups = share / "backups"
    exports.mkdir(parents=True)
    backups.mkdir(parents=True)
    with (exports / "epos_day_end_20260920.csv").open(
        "w", encoding="utf-8", newline=""
    ) as fh:
        writer = csv.writer(fh)
        writer.writerow(["card_no", "date", "qty_kg"])
        writer.writerow(["110300512847", "2026-09-20", "5.000"])
    # The S7 health check expects a database backup with a cards table;
    # without one every non-baseline pull is SUSPECT for data reasons.
    with sqlite3.connect(backups / "district-backup-2026-09-20.db") as conn:
        conn.execute("CREATE TABLE cards (id INTEGER PRIMARY KEY, name TEXT)")
        conn.executemany(
            "INSERT INTO cards (name) VALUES (?)",
            [(f"card {n}",) for n in range(120)],
        )
    return share


def _spawn_agent(root: Path) -> subprocess.Popen:
    """The real watcher agent: heartbeats on its own schedule."""
    proc = subprocess.Popen(
        [
            PYTHON,
            "-m",
            "nightkeep.watcher",
            "--run",
            "--root",
            str(root),
            "--interval",
            str(BEAT),
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


def _wait_for(predicate, timeout: float = 15.0, what: str = "condition"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for: {what}")


def _scramble(share: Path) -> None:
    target = share / "exports" / "epos_day_end_20260920.csv"
    target.write_bytes(os.urandom(6000))  # scrambled: random, header broken


# -- S6 alone -> SUSPICIOUS + Protect mode ----------------------------------


def test_killed_watcher_drives_vault_to_suspicious_and_protect_mode(tmp_path):
    root = tmp_path / "demo"
    share = _share_with_csv(root)
    vault = _vault(tmp_path, share)

    baseline = vault.pull()
    assert baseline.health == CLEAN
    assert vault.vault_verdict == NORMAL
    assert vault.protect_mode is False

    agent = _spawn_agent(root)
    try:
        events = []
        vault.start_liveness_monitor(on_state_change=events.append)
        try:
            _wait_for(
                lambda: (
                    vault.last_liveness is not None
                    and vault.last_liveness.alive
                ),
                what="monitor to see the healthy watcher",
            )
            assert vault.vault_verdict == NORMAL
            assert vault.protect_mode is False

            # The kill: the watcher agent dies, the heartbeats stop.
            _stop(agent)

            _wait_for(
                lambda: (
                    vault.vault_verdict == SUSPICIOUS
                    and vault.protect_mode
                ),
                what="vault to record S6 as SUSPICIOUS + protect mode",
            )
            assert vault.last_liveness is not None
            assert vault.last_liveness.alive is False
            assert "S6" in vault.last_liveness.reason

            # The documented response fired exactly once.
            assert len(events) == 1
            state = events[0]
            assert state.verdict == SUSPICIOUS
            assert state.previous_verdict == NORMAL
            assert state.protect_mode is True
            assert state.watcher_alive is False
            assert state.snapshot_health == CLEAN

            logged = vault.alerts()
            assert len(logged) == 1
            assert logged[0]["verdict"] == SUSPICIOUS
            assert logged[0]["previous_verdict"] == NORMAL
            assert logged[0]["protect_mode"] is True
            assert "S6" in logged[0]["liveness_reason"]

            # S6 says nothing about the data: an unchanged pull is still
            # CLEAN, but Protect mode holds the clean point -- the pin
            # stays on the pre-S6 snapshot, the verdict stays put, and
            # nothing re-alerts.
            again = vault.pull(
                taken_at=baseline.taken_at + timedelta(days=1)
            )
            assert again.health == CLEAN
            assert again.is_clean_point is False
            pinned = [s for s in vault.snapshots() if s.is_clean_point]
            assert [s.snapshot_id for s in pinned] == [
                baseline.snapshot_id
            ]
            assert vault.vault_verdict == SUSPICIOUS
            assert vault.protect_mode is True
            assert len(events) == 1
            assert len(vault.alerts()) == 1
        finally:
            vault.stop_liveness_monitor()
    finally:
        _stop(agent)


# -- Protect mode holds the clean point ------------------------------------


def test_protect_mode_holds_clean_point_on_clean_pull(tmp_path):
    # The design doc's "hold the last clean point": once the Vault
    # enters Protect mode, a later unchanged CLEAN pull must not
    # advance the pin. The snapshot itself stays CLEAN -- S6 says
    # nothing about the data -- only the pin is held, until
    # protection is cleared.
    root = tmp_path / "demo"
    share = _share_with_csv(root)
    vault = _vault(tmp_path, share)

    baseline = vault.pull()
    assert baseline.health == CLEAN
    assert baseline.is_clean_point is True

    # S6 without a subprocess: a heartbeat stale enough that the
    # monitor reads it as silence.
    stale = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    (share / HEARTBEAT_FILENAME).write_text(
        json.dumps({"written_at": stale, "pid": 99999}), encoding="utf-8"
    )
    events = []
    vault.start_liveness_monitor(on_state_change=events.append)
    try:
        _wait_for(
            lambda: vault.vault_verdict == SUSPICIOUS and vault.protect_mode,
            what="stale heartbeat to raise SUSPICIOUS + protect mode",
        )

        # The data is untouched, so the pull is still CLEAN -- but the
        # pin must stay on the pre-S6 snapshot.
        again = vault.pull(taken_at=baseline.taken_at + timedelta(days=1))
        assert again.health == CLEAN
        assert again.is_clean_point is False
        pinned = [s for s in vault.snapshots() if s.is_clean_point]
        assert [s.snapshot_id for s in pinned] == [baseline.snapshot_id]

        # The verdict never moved and nothing re-alerted.
        assert vault.vault_verdict == SUSPICIOUS
        assert vault.protect_mode is True
        assert len(events) == 1
        assert len(vault.alerts()) == 1
    finally:
        vault.stop_liveness_monitor()


# -- S6 + S7 -> INCIDENT -----------------------------------------------------


def test_s6_with_suspect_snapshot_is_incident(tmp_path):
    root = tmp_path / "demo"
    share = _share_with_csv(root)
    vault = _vault(tmp_path, share)

    clean = vault.pull()
    assert clean.health == CLEAN

    agent = _spawn_agent(root)
    try:
        events = []
        vault.start_liveness_monitor(on_state_change=events.append)
        try:
            _wait_for(
                lambda: (
                    vault.last_liveness is not None
                    and vault.last_liveness.alive
                ),
                what="monitor to see the healthy watcher",
            )

            # S7: the data is scrambled. The snapshot says SUSPECT for
            # data reasons only; the Vault's own call is SUSPICIOUS +
            # Protect mode while the watcher is still alive.
            _scramble(share)
            bad = vault.pull(taken_at=clean.taken_at + timedelta(days=1))
            assert bad.health == SUSPECT
            assert bad.is_clean_point is False
            _wait_for(
                lambda: (
                    vault.vault_verdict == SUSPICIOUS
                    and vault.protect_mode
                ),
                what="S7 alone to raise SUSPICIOUS + protect mode",
            )
            assert vault.last_liveness is not None
            assert vault.last_liveness.alive is True

            # Now S6 joins S7: kill the watcher -> INCIDENT.
            _stop(agent)
            _wait_for(
                lambda: vault.vault_verdict == INCIDENT,
                what="S6 + S7 to become INCIDENT",
            )
            assert vault.protect_mode is True
            assert [e.verdict for e in events] == [SUSPICIOUS, INCIDENT]
            incident = events[1]
            assert incident.previous_verdict == SUSPICIOUS
            assert incident.protect_mode is True
            assert incident.watcher_alive is False
            assert incident.snapshot_health == SUSPECT
            logged = vault.alerts()
            assert [a["verdict"] for a in logged] == [
                SUSPICIOUS,
                INCIDENT,
            ]
            assert "S6" in logged[1]["liveness_reason"]
        finally:
            vault.stop_liveness_monitor()
    finally:
        _stop(agent)


# -- heartbeat machinery must not pollute the data health check ------------


def test_leftover_heartbeat_tmp_does_not_poison_pull(tmp_path):
    # The agent writes the heartbeat atomically (temp file, then rename).
    # If the agent dies mid-write -- exactly the S6 scenario -- the temp
    # file can be left behind in the share. It is a signal, not backup
    # data, so the next pull must still be CLEAN instead of SUSPECT for a
    # "new file type" that was never data.
    root = tmp_path / "demo"
    share = _share_with_csv(root)
    vault = _vault(tmp_path, share)

    baseline = vault.pull()
    assert baseline.health == CLEAN

    (share / (HEARTBEAT_FILENAME + ".tmp")).write_text(
        '{"written_at": "2026-09-21T00:00:00+00:00", "pid": 1}',
        encoding="utf-8",
    )
    again = vault.pull(taken_at=baseline.taken_at + timedelta(days=1))
    assert again.health == CLEAN
    assert again.is_clean_point is True


# -- the composition rule at the edges --------------------------------------


def test_combined_verdict_with_no_liveness_evidence_yet():
    # Before the monitor's first check there is no S6 evidence: only the
    # snapshot's health can speak.
    assert combined_verdict(None, CLEAN) == NORMAL
    assert combined_verdict(None, SUSPECT) == SUSPICIOUS


def test_fresh_vault_reads_existing_snapshot_health(tmp_path):
    # A Vault constructed against a store that already holds a SUSPECT
    # snapshot starts from the S7 witness on disk.
    root = tmp_path / "demo"
    share = _share_with_csv(root)
    vault = _vault(tmp_path, share)
    vault.pull()
    _scramble(share)
    bad = vault.pull()
    assert bad.health == SUSPECT

    vault2 = _vault(tmp_path, share)
    assert vault2.vault_state.snapshot_health == SUSPECT

    write_heartbeat(share / HEARTBEAT_FILENAME)  # watcher alive
    events = []
    vault2.start_liveness_monitor(on_state_change=events.append)
    try:
        _wait_for(
            lambda: vault2.vault_verdict == SUSPICIOUS,
            what="fresh vault to call SUSPICIOUS from the on-disk S7",
        )
    finally:
        vault2.stop_liveness_monitor()
    assert len(events) == 1
    assert events[0].watcher_alive is True
    assert events[0].snapshot_health == SUSPECT
