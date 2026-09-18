"""One simulated day: the shop day, then the jobs due that night.

Every random choice for a day is drawn up front, in a fixed order, from one
random.Random seeded by (seed, day_no). A day therefore replays exactly on
its own, whichever days ran before it.
"""

import random
import sqlite3
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

from nightkeep.config import NightlyExport
from nightkeep.mock_pds import _generate
from nightkeep.mock_pds import conventions as c


def day_rng(seed: int, day_no: int) -> random.Random:
    # A str seed is hashed with SHA-512, so it is stable across processes.
    return random.Random(f"{seed}/day/{day_no}")


def draw_transaction_count(rng: random.Random, export: NightlyExport) -> int:
    """How many ePoS transactions the district's shops record today.

    The midpoint of rows_per_run, moved by up to volume_variation either way,
    and kept inside rows_per_run. The export later carries exactly these.
    """
    span = export.rows_per_run
    midpoint = (span.low + span.high) / 2
    count = round(midpoint * (1 + rng.uniform(-export.volume_variation, export.volume_variation)))
    return min(max(count, span.low), span.high)


def land_transactions(
    rng: random.Random, db_path: Path, day: date, count: int
) -> None:
    """PDS application activity, not a job: the shops' day of ePoS issues.

    Only Active cards draw grain, each at its own fair price shop.
    """
    conn = sqlite3.connect(db_path)
    try:
        cards = conn.execute(
            "SELECT c.card_no, c.fps_id, c.scheme, COUNT(m.member_id) "
            "FROM cards c JOIN members m ON m.card_no = c.card_no "
            "WHERE c.status = 'Active' "
            "GROUP BY c.card_no ORDER BY c.card_no"
        ).fetchall()
        allotment_month = day.strftime("%Y-%m")
        rows = []
        for _ in range(count):
            card_no, fps_id, scheme, members = rng.choice(cards)
            entitlement = c.entitlement_kg(scheme, members)
            rows.append(
                _generate.draw_transaction(
                    rng, card_no, fps_id, entitlement, day, allotment_month
                )
            )
        _generate.insert_transactions(conn, rows)
        conn.commit()
    finally:
        conn.close()


_JOBS_DIR = Path(__file__).resolve().parent / "jobs"


def launch(job: str, district_dir: Path, day_no: int, sim_start: datetime,
           scale: float, *arguments: str) -> None:
    """Run one job as a real subprocess and wait for it to finish.

    -I (isolated mode) keeps this repository off the job's import path, so a
    job that tried to import Nightkeep would fail here, not just in a test.
    The job writes its own ground-truth line. The scheduler never does.
    """
    subprocess.run(
        [
            sys.executable, "-I", str(_JOBS_DIR / f"{job}.py"),
            "--root", str(district_dir),
            "--day", str(day_no),
            "--sim-start", sim_start.isoformat(),
            "--scale", repr(scale),
            *arguments,
        ],
        check=True,
    )
