"""The console wires itself to a demo runtime created after startup.

Regression test: create_console_app used to return an unwired app when the
demo output did not exist yet, so after the showcase demo created
demo/demo_run the post-demo screens still showed fallback data. Now the
runtime factory is installed even when the runtime is absent at startup:
each request rebuilds from disk, and once the demo creates the runtime
the screens pick it up without a Flask restart. Before the demo exists
the screens stay calm and honest: no fabricated incident.
"""

import csv
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from nightkeep.config import District, Span, load_config
from nightkeep.console.__main__ import create_console_app
from nightkeep.habit import Habit, JobRun
from nightkeep.mock_pds import build_district
from nightkeep.types import MODIFIED, Event
from nightkeep.vault import Vault

SMALL = District(
    ration_cards=200,
    fps_count=10,
    members_per_card=Span(low=1, high=5),
    transactions_per_card_per_month=Span(low=0, high=2),
)
DAY = datetime(2026, 9, 20, 2, 14, tzinfo=timezone.utc)


def _share_with_backup(district_dir: Path) -> Path:
    """A district share with one CSV and one db backup, enough for a pull."""
    share = district_dir / "share"
    exports = share / "exports"
    backups = share / "backups"
    exports.mkdir(parents=True, exist_ok=True)
    backups.mkdir(parents=True, exist_ok=True)
    with (exports / "epos_day_end_20260920.csv").open(
        "w", encoding="utf-8", newline=""
    ) as fh:
        writer = csv.writer(fh)
        writer.writerow(["card_no", "date", "qty_kg"])
        writer.writerow(["110300512847", "2026-09-20", "5.000"])
    backup = backups / "district-backup-2026-09-20.db"
    conn = sqlite3.connect(backup)
    try:
        conn.execute("CREATE TABLE cards (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO cards (name) VALUES ('a')")
        conn.commit()
    finally:
        conn.close()
    return share


def _teach(district_dir: Path) -> None:
    habit = Habit(district_dir / "data" / "habit.db", 3.0, 3, 0.10)
    for day in range(1, 8):
        start = DAY - timedelta(days=8 - day)
        habit.learn(
            JobRun(
                job="nightly_export",
                identity="nightly_export|nightly_export.py|abc123",
                started_at=start,
                finished_at=start + timedelta(seconds=30),
                events=(
                    Event(
                        path="share/exports/epos_day_end.csv",
                        kind=MODIFIED,
                        at=start,
                        size=9_000,
                    ),
                ),
                day_no=day,
            )
        )


def _create_demo_runtime(district_dir: Path, vault_dir: Path) -> None:
    """Create the on-disk state a showcase demo run leaves behind."""
    build_district(20260922, SMALL, district_dir)
    share = _share_with_backup(district_dir)
    vault = Vault(
        vault_dir,
        share,
        suspect_entropy=7.0,
        suspect_changed_fraction=0.5,
        suspect_record_drop_fraction=0.02,
        restore_folder_name="restored",
    )
    vault.pull(taken_at=DAY)
    _teach(district_dir)
    reports = district_dir / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "demo_run.json").write_text(
        json.dumps(
            {
                "attack": {
                    "level": "INCIDENT",
                    "signals": ["S3", "S4", "S5"],
                    "reasons": ["files scrambled in place"],
                    "actions": ["paused the program that was changing files"],
                }
            }
        ),
        encoding="utf-8",
    )


def test_console_wires_itself_to_a_runtime_created_after_startup(tmp_path):
    district_dir = tmp_path / "demo_run" / "district"
    vault_dir = tmp_path / "demo_run" / "vault"
    assert not district_dir.exists()
    assert not vault_dir.exists()

    config = load_config(Path("nightkeep/config.yaml"))
    app = create_console_app(
        config, district_dir=district_dir, vault_dir=vault_dir
    )
    client = app.test_client()

    # 1. Before the demo exists: calm, honest screens, no fabricated incident.
    alert = client.get("/alert").get_data(as_text=True)
    assert "STATUS: ALL CLEAR" in alert
    assert "ATTACK STOPPED" not in alert

    restore = client.get("/restore").get_data(as_text=True)
    assert "No clean copy yet" in restore

    locked = client.get("/locked").get_data(as_text=True)
    assert "DEMONSTRATION DRILL" in locked

    safety = client.get("/safety").get_data(as_text=True)
    # Honest calm state: no fabricated clean point before the demo runs.
    assert "No clean copy yet" in safety
    assert "Day 9, 01:20" not in safety

    it_view = client.get("/it-view").get_data(as_text=True)
    assert "IT diagnostics are unavailable" in it_view

    popup = client.get("/server-alert").get_data(as_text=True)
    assert "Unusual activity was detected on the office computer." in popup

    # 2. The showcase demo creates the runtime on disk.
    _create_demo_runtime(district_dir, vault_dir)

    # 3. The same Flask app now serves the real runtime: no restart.
    alert = client.get("/alert").get_data(as_text=True)
    assert "STATUS: ATTACK STOPPED" in alert
    assert "STATUS: ALL CLEAR" not in alert

    restore = client.get("/restore").get_data(as_text=True)
    assert "No clean copy yet" not in restore

    locked = client.get("/locked").get_data(as_text=True)
    assert "SYSTEM NOTICE" in locked
    assert "DEMONSTRATION DRILL" not in locked

    safety = client.get("/safety").get_data(as_text=True)
    assert "Day 9, 01:20" not in safety

    it_view = client.get("/it-view").get_data(as_text=True)
    assert "IT diagnostics are unavailable" not in it_view
    assert "INCIDENT" in it_view

    popup = client.get("/server-alert").get_data(as_text=True)
    assert "It was paused." in popup


def test_console_without_config_still_shows_calm_screens():
    app = create_console_app()
    client = app.test_client()

    alert = client.get("/alert").get_data(as_text=True)
    assert "STATUS: ALL CLEAR" in alert
    assert client.get("/restore").status_code == 200
