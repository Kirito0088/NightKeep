"""One simulated day: the shop day, then the jobs due that night.

Every random choice for a day is drawn up front, in a fixed order, from a
random.Random seeded by (seed, day_no). A day therefore replays exactly on
its own, whichever days ran before it, and on whatever machine.

There are two such streams: day_rng decides what the jobs do, timeline_rng
how long they take. Keeping them apart means a run length can be retuned
without re-rolling a single one of the night's other decisions.
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


def timeline_rng(seed: int, day_no: int) -> random.Random:
    """The stream tonight's run lengths are drawn from.

    Kept apart from day_rng so that how long a job takes cannot shift what it
    does: the two are independent facts about the night, and giving each its
    own stream means tuning one never silently re-rolls the other.
    """
    return random.Random(f"{seed}/timeline/{day_no}")


def draw_transaction_count(
    rng: random.Random, export: NightlyExport, surge_multiplier: float = 1.0
) -> int:
    """How many ePoS transactions the district's shops record today.

    The midpoint of rows_per_run, moved by up to volume_variation either way,
    and kept inside rows_per_run. surge_multiplier scales the result after
    that clamp, so the harvest surge can legitimately exceed rows_per_run.
    The export later carries exactly these.
    """
    span = export.rows_per_run
    midpoint = (span.low + span.high) / 2
    count = round(midpoint * (1 + rng.uniform(-export.volume_variation, export.volume_variation)))
    count = min(max(count, span.low), span.high)
    return round(count * surge_multiplier)


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

def _bat_command(path: Path, arguments: list) -> str:
    # cmd.exe re-parses everything after /c with its own tokenizer, which
    # does NOT understand the backslash-escaped quotes (\") that
    # subprocess.list2cmdline produces when a list element contains quotes.
    # A /c argument built as a list element therefore arrives at cmd.exe
    # mangled, and cmd tries to run the whole quoted string as one command
    # ("'\"D:\\...\\job.bat --root ...\"' is not recognized...").
    # So the command travels as ONE pre-built string (subprocess passes a
    # string to CreateProcess verbatim, with no list2cmdline step), using
    # the cmd.exe /c "..." idiom: cmd strips the outer quote pair itself
    # (its "old behavior" rule), leaving the individually quoted pieces
    # from list2cmdline intact so spaced script/district paths survive.
    inner = subprocess.list2cmdline([str(path), *map(str, arguments)])
    return f'cmd.exe /c "{inner}"'


# Job identity is executable + script path + hash (SOLUTION_DESIGN.md), so
# the two script-language jobs run through their real interpreters rather
# than being reduced to Python for convenience.
_INTERPRETERS = {
    ".py": lambda path, arguments: [sys.executable, "-I", str(path), *arguments],
    ".bat": lambda path, arguments: _bat_command(path, arguments),
    ".vbs": lambda path, arguments: ["cscript.exe", "//nologo", str(path), *arguments],
}


def _job_path(job: str) -> Path:
    matches = [
        _JOBS_DIR / f"{job}{suffix}" for suffix in _INTERPRETERS
        if (_JOBS_DIR / f"{job}{suffix}").exists()
    ]
    if not matches:
        raise FileNotFoundError(f"no job script found for {job!r} in {_JOBS_DIR}")
    if len(matches) > 1:
        # Job identity is executable + script path + hash: two scripts for
        # the same job name would make that identity ambiguous.
        raise FileNotFoundError(f"more than one job script found for {job!r}: {matches}")
    return matches[0]


def launch(job: str, district_dir: Path, day_no: int, sim_start: datetime,
           sim_end: datetime, *arguments: str) -> None:
    """Run one job as a real subprocess and wait for it to finish.

    A .py job runs under -I (isolated mode), which keeps this repository off
    its import path, so a job that tried to import Nightkeep would fail
    here, not just in a test. The job writes its own ground-truth line. The
    scheduler never does.

    Both simulated times are handed in already decided, so no job has to ask
    the wall clock what time it is. Real time is left to pace the run; it
    never reaches the ground truth.
    """
    path = _job_path(job)
    script_arguments = [
        "--root", str(district_dir),
        "--day", str(day_no),
        "--sim-start", sim_start.isoformat(),
        "--sim-end", sim_end.isoformat(),
        *arguments,
    ]
    command = _INTERPRETERS[path.suffix](path, script_arguments)
    subprocess.run(command, check=True)
