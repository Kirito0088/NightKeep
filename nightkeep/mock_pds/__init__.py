"""The fake district PDS server: data, jobs, clock, hidden ground truth.

Public interface:
    build_district(seed, district, out_dir)
    run_day(day_no, *, seed, clock, jobs, harvest_surge, district_dir,
            harvest_surge_override=None)

Hides 5,000 ration cards, 6 erratic jobs, their randomness, the simulated
clock and the hidden truth log. Nothing outside this package and tests/ may
read logs/_truth/.

prove_erratic.py sits alongside these two as a script the entrypoint runs,
not as a third function for other modules to call. It lives here because it
reads the truth logs. See docs/adr/0009-prove-erratic-lives-with-mock-pds.md.
"""

import sqlite3
from pathlib import Path

from nightkeep.config import Clock, District, HarvestSurge, Jobs
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
    day_no: int, *, seed: int, clock: Clock, jobs: Jobs,
    harvest_surge: HarvestSurge, district_dir: Path,
    harvest_surge_override: bool | None = None,
) -> None:
    """Live one simulated day on the district built at district_dir.

    Takes clock.simulated_day_seconds of real time. Returns nothing on
    purpose: what happened is on disk, and what the jobs really did is in
    their own ground-truth logs, which only mock_pds and tests/ may read.

    harvest_surge_override, when not None, overrides whether day_no counts
    as a surge day, ignoring harvest_surge.days for this call only: the
    hook a later demo control uses to flip the surge on live, per MVP.md's
    "switch on harvest surge" legit surprise.
    """
    district_dir = Path(district_dir)
    rng = _day.day_rng(seed, day_no)
    day = DayClock(day_no, clock.day_starts_at, clock.simulated_day_seconds)
    export = jobs.nightly_export
    is_surge_day = (
        day_no in harvest_surge.days if harvest_surge_override is None
        else harvest_surge_override
    )
    surge_multiplier = harvest_surge.multiplier if is_surge_day else 1.0

    # Every draw for the day, up front and in a fixed order.
    transaction_count = _day.draw_transaction_count(rng, export, surge_multiplier)
    export_start = day.draw_start(rng, export.start_window)
    network_down = rng.random() < export.network_down_probability
    # The safe copy has no window of its own. It follows the export, so its
    # start drifts with the export's, network down or not.
    backup_start = export_start + day.draw_delay(
        rng, jobs.db_backup.delay_after_export_minutes
    )

    operator = jobs.operator_activity
    operator_edits = rng.randint(operator.edits_per_day.low, operator.edits_per_day.high)
    operator_edit_seed = rng.randint(0, 2**31 - 1)
    operator_start = day.draw_start(rng, operator.start_window)
    is_sunday = operator.skip_sundays and day.date.weekday() == 6

    allocation = jobs.allocation_gen
    is_month_start = day.date.day == allocation.month_start_day
    allocation_span = (
        allocation.files_on_month_start if is_month_start
        else allocation.files_on_a_top_up
    )
    allocation_files = rng.randint(allocation_span.low, allocation_span.high)
    allocation_start = day.draw_start(rng, allocation.start_window)
    allocation_double_run = rng.random() < allocation.double_run_probability

    fix_dat = jobs.fix_dat
    fix_dat_start = day.draw_start(rng, fix_dat.start_window)
    fix_dat_should_run = rng.random() < fix_dat.run_probability

    archive = jobs.archive_old
    archive_start = day.draw_start(rng, archive.start_window)
    archive_files = rng.randint(
        archive.files_zipped_per_run.low, archive.files_zipped_per_run.high
    )

    launched = day.wait_until(operator_start)
    _day.launch(
        "operator_activity", district_dir, day_no, launched, day.scale,
        "--edits", str(operator_edits), "--edit-seed", str(operator_edit_seed),
        *(["--sunday"] if is_sunday else []),
    )

    day.wait_until(day.at(conventions.SHOP_CLOSES))
    _day.land_transactions(
        rng, district_dir / "data" / "district.db", day.date, transaction_count
    )

    launched = day.wait_until(allocation_start)
    allocation_args = (
        "--business-date", day.date.isoformat(), "--files", str(allocation_files),
    )
    _day.launch(
        "allocation_gen", district_dir, day_no, launched, day.scale,
        *allocation_args,
    )
    if allocation_double_run:
        _day.launch(
            "allocation_gen", district_dir, day_no, launched, day.scale,
            *allocation_args,
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

    launched = day.wait_until(fix_dat_start)
    _day.launch(
        "fix_dat", district_dir, day_no, launched, day.scale,
        *(["--run"] if fix_dat_should_run else []),
    )

    launched = day.wait_until(archive_start)
    _day.launch(
        "archive_old", district_dir, day_no, launched, day.scale,
        "--files", str(archive_files),
        "--threshold-mb", str(archive.size_threshold_mb),
    )

    day.wait_until(day.end)
