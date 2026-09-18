"""The fake district PDS server: data, jobs, clock, hidden ground truth.

Public interface:
    build_district(seed, district, out_dir)
    run_day(day_no, out_dir, seed, config)

Hides 5,000 ration cards, 6 erratic jobs, their randomness, the simulated
clock and the hidden truth log. Nothing outside this package and tests/ may
read logs/_truth/.
"""

import shutil
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from nightkeep.config import Config, District
from nightkeep.mock_pds import _generate
from nightkeep.mock_pds._schema import create_schema
from nightkeep.mock_pds.clock import SimulatedClock
from nightkeep.mock_pds.conventions import SIMULATED_TODAY
from nightkeep.mock_pds.scheduler import DEFAULT_JOBS_DIR, Scheduler
from nightkeep.types import JobRun

_SIBLING_FOLDERS = ("exports", "allocations", "reports", "archive", "logs", "jobs")


def build_district(seed: int, district: District, out_dir: Path) -> Path:
    """Build a fresh Thane district database and its folder layout.

    Creates out_dir/data/district.db, plus the exports, allocations,
    reports, archive, logs and jobs folders the nightly jobs will later
    write into. Copies standalone job scripts into out_dir/jobs/.
    The same seed always reproduces the same district. Returns out_dir.
    """
    out_dir = Path(out_dir)
    data_dir = out_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    for folder in _SIBLING_FOLDERS:
        (out_dir / folder).mkdir(parents=True, exist_ok=True)

    # Deploy job scripts to out_dir/jobs
    jobs_target_dir = out_dir / "jobs"
    if DEFAULT_JOBS_DIR.is_dir():
        for script in DEFAULT_JOBS_DIR.glob("*.py"):
            shutil.copy2(script, jobs_target_dir / script.name)

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
    day_no: int,
    out_dir: Path,
    seed: int = 20260922,
    config: Config | None = None,
    sim_date: date | None = None,
) -> list[JobRun]:
    """Simulate one day of district PDS operations and execute scheduled jobs.

    Hides the simulated clock advancement and erratic job executions.
    Returns the structured list of JobRun records produced during the day.
    """
    out_dir = Path(out_dir)
    if sim_date is None:
        # 10 days total: day 1 is 9 days before SIMULATED_TODAY
        sim_date = SIMULATED_TODAY - timedelta(days=10 - day_no)

    start_dt = datetime.combine(sim_date, datetime.min.time())
    clock = SimulatedClock(start_dt)
    jobs_dir = out_dir / "jobs" if (out_dir / "jobs").is_dir() else DEFAULT_JOBS_DIR
    scheduler = Scheduler(
        clock=clock,
        out_dir=out_dir,
        seed=seed,
        config=config,
        jobs_dir=jobs_dir,
    )

    return scheduler.run_day(day_no, sim_date=sim_date)
