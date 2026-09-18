"""The fake district PDS server: data, jobs, clock, hidden ground truth.

Public interface:
    build_district(seed, district, out_dir)
    run_day(day_no, *, seed, clock, jobs, district_dir)

Hides 5,000 ration cards, 6 erratic jobs, their randomness, the simulated
clock and the hidden truth log. Nothing outside this package and tests/ may
read logs/_truth/.
"""

import sqlite3
from pathlib import Path

from nightkeep.config import Clock, District, Jobs
from nightkeep.mock_pds import _day, _generate, conventions
from nightkeep.mock_pds._clock import DayClock
from nightkeep.mock_pds._schema import create_schema

_SIBLING_FOLDERS = ("reports", "archive", "logs")
# ADR-0007: the one folder the PDS server shares, read-only, with the Vault.
# The live database in data/ is never inside it.
_SHARED_FOLDERS = ("exports", "allocations", "backups")


def build_district(seed: int, district: District, out_dir: Path) -> Path:
    """Build a fresh Thane district database and its folder layout.

    Creates out_dir/data/district.db, the reports, archive and logs
    folders, and share/ with its exports, allocations and backups folders:
    the one folder the Vault pulls from (ADR-0007). The nightly jobs write
    into these. The same seed always reproduces the same district. Returns
    out_dir.
    """
    out_dir = Path(out_dir)
    data_dir = out_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    for folder in _SIBLING_FOLDERS:
        (out_dir / folder).mkdir(parents=True, exist_ok=True)
    for folder in _SHARED_FOLDERS:
        (out_dir / "share" / folder).mkdir(parents=True, exist_ok=True)

    db_path = data_dir / "district.db"
    db_path.unlink(missing_ok=True)

    conn = sqlite3.connect(db_path)
    try:
        create_schema(conn)
        _generate.generate(conn, seed, district)
    finally:
        conn.close()

    return out_dir


def run_day(
    day_no: int, *, seed: int, clock: Clock, jobs: Jobs, district_dir: Path
) -> None:
    """Live one simulated day on the district built at district_dir.

    Takes clock.simulated_day_seconds of real time. Returns nothing on
    purpose: what happened is on disk, and what the jobs really did is in
    their own ground-truth logs, which only mock_pds and tests/ may read.
    """
    district_dir = Path(district_dir)
    rng = _day.day_rng(seed, day_no)
    day = DayClock(day_no, clock.day_starts_at, clock.simulated_day_seconds)
    export = jobs.nightly_export

    # Every draw for the day, up front and in a fixed order.
    transaction_count = _day.draw_transaction_count(rng, export)
    export_start = day.draw_start(rng, export.start_window)
    network_down = rng.random() < export.network_down_probability
    # The safe copy has no window of its own. It follows the export, so its
    # start drifts with the export's, network down or not.
    backup_start = export_start + day.draw_delay(
        rng, jobs.db_backup.delay_after_export_minutes
    )

    day.wait_until(day.at(conventions.SHOP_CLOSES))
    _day.land_transactions(
        rng, district_dir / "data" / "district.db", day.date, transaction_count
    )

    launched = day.wait_until(export_start)
    _day.launch(
        "nightly_export", district_dir, day_no, launched, day.scale,
        "--business-date", day.date.isoformat(),
        *(["--network-down"] if network_down else []),
    )

    # Jobs never overlap: launch returns once the export has exited, and a
    # late export pushes the safe copy late rather than running alongside it,
    # and the safe copy is told the time it really started.
    launched = day.wait_until(backup_start)
    _day.launch(
        "db_backup", district_dir, day_no, launched, day.scale,
        "--business-date", day.date.isoformat(),
    )

    day.wait_until(day.end)
