"""F11 end to end: the watcher-killer demo path.

Runs the real demo runner with variant="watcher-killer": the watcher
agent runs as its own process (watching + heartbeating), the killer
terminates that agent, and the Vault detects the silence by its own
clock after the configured threshold.

The Windows-only day loop (cscript.exe/cmd.exe jobs) is stubbed out like
in test_demo_run.py: it cannot run on Linux and is irrelevant to the S6
path. Marked slow: real filesystem, subprocesses, watcher and real
timing, like the smoke run this mirrors.
"""

import shutil
import sqlite3
from pathlib import Path

import pytest

from nightkeep import demo_run
from nightkeep.config import load_config
from nightkeep.types import NORMAL, SUSPICIOUS

pytestmark = pytest.mark.slow

REPO_ROOT = Path(__file__).resolve().parent.parent
DEMO_DIR = REPO_ROOT / "demo"


def _stub_run_day(day_no, *, seed, clock, jobs, harvest_surge, district_dir,
                  harvest_surge_override=None):
    """Stand in for the Windows-only day loop. Mimics the one output the
    vault path depends on: the db_backup job's database backup in
    share/backups. Written once, so later pulls see no changes -- like
    quiet real days -- keeping every pre-attack snapshot CLEAN."""
    backups = Path(district_dir) / "share" / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    db = backups / "district-backup-2026-09-20.db"
    if not db.exists():
        with sqlite3.connect(db) as conn:
            conn.execute(
                "CREATE TABLE cards (id INTEGER PRIMARY KEY, name TEXT)"
            )
            conn.executemany(
                "INSERT INTO cards (name) VALUES (?)",
                [(f"card {n}",) for n in range(5000)],
            )


def test_demo_runner_detects_the_killed_watcher_as_s6(
    monkeypatch, tmp_path
):
    monkeypatch.setattr("nightkeep.mock_pds.run_day", _stub_run_day)

    # The safe simulator refuses to run outside the repo's demo folder.
    out_dir = DEMO_DIR / "test_demo_run_watcher_killer"
    try:
        config = load_config(REPO_ROOT / "nightkeep" / "config.yaml")
        report = demo_run.run_demo(config, out_dir, variant="watcher-killer")
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)

    assert report["passed"] is True

    liveness = report["watcher_liveness"]
    # The agent was beating before the attack...
    assert liveness["before_attack"]["alive"] is True
    # ...the killer terminated exactly that agent process...
    assert liveness["agent_terminated"] is True
    # ...and the Vault called S6 after the configured silence.
    assert liveness["after_attack"]["alive"] is False
    assert "S6" in liveness["after_attack"]["reason"]
    assert (liveness["silence_threshold_seconds"]
            == config.watcher.silence_threshold_seconds)
    # Design-doc S6 values, still tunable in config.
    assert liveness["heartbeat_interval_seconds"] == 10
    assert liveness["silence_threshold_seconds"] == 30
    assert (liveness["liveness_check_interval_seconds"]
            == config.watcher.liveness_check_interval_seconds)
    # The Vault's own monitor asked on its clock during the run.
    assert liveness["vault_liveness_checks"] >= 1

    # The point of F11: the server-side Judge saw no attack at all
    # (NORMAL -- no files were touched), while the Vault still raised
    # the alarm from the silence. The data itself stayed CLEAN, and S6
    # alone is the vault-side SUSPICIOUS call.
    assert report["attack"]["level"] == NORMAL
    assert report["attack"]["snapshot_health"] == "CLEAN"
    assert liveness["vault_side_verdict"] == SUSPICIOUS

    # The existing guarantees still hold: the post-kill pull is CLEAN so
    # it honestly becomes the new pin (the kill changed no data), and the
    # restore verifies every record.
    assert report["checks"]["clean_pin_covers_untouched_data"] is True
    restore = report["restore"]
    assert restore["ok"] is True
    assert restore["records_verified"] == restore["records_expected"] == 5000
