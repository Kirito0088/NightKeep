"""Deterministic job scheduler and execution harness for mock PDS.

Schedules and executes nightly PDS jobs on the simulated clock.
Captures filesystem attribution and produces JobRun records without
evaluating whether activity is malicious (that belongs to habit/judge).
"""

import hashlib
import os
import random
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable

from nightkeep.config import Config
from nightkeep.mock_pds.clock import SimulatedClock
from nightkeep.types import JobRun

# Default jobs location inside mock_pds package
DEFAULT_JOBS_DIR = Path(__file__).resolve().parent / "jobs"


def _hash_file(path: Path) -> str:
    """Compute SHA-256 of a script file."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _snapshot_dir(root: Path) -> dict[str, tuple[int, int]]:
    """Map relative file paths to (mtime_ns, size_bytes)."""
    snapshot = {}
    if not root.exists():
        return snapshot
    for p in root.rglob("*"):
        # Skip hidden logs/_truth/ from external observation
        if "_truth" in p.parts:
            continue
        if p.is_file():
            try:
                st = p.stat()
                rel = str(p.relative_to(root))
                snapshot[rel] = (st.st_mtime_ns, st.st_size)
            except OSError:
                pass
    return snapshot


@dataclass(frozen=True)
class ScheduledJob:
    """A planned job run at a specific simulated time."""

    job_name: str
    scheduled_time: datetime
    script_path: Path
    arguments: tuple[str, ...]
    details: dict[str, Any]


class Scheduler:
    """Deterministic scheduler driving simulated jobs on the PDS server."""

    def __init__(
        self,
        clock: SimulatedClock,
        out_dir: Path,
        seed: int = 20260922,
        config: Config | None = None,
        jobs_dir: Path | None = None,
    ) -> None:
        self._clock = clock
        self._out_dir = Path(out_dir)
        self._seed = seed
        self._config = config
        self._jobs_dir = Path(jobs_dir) if jobs_dir else DEFAULT_JOBS_DIR
        self._history: list[JobRun] = []
        self._scheduled_queue: list[ScheduledJob] = []

    @property
    def clock(self) -> SimulatedClock:
        return self._clock

    @property
    def history(self) -> tuple[JobRun, ...]:
        return tuple(self._history)

    def schedule_day(self, day_no: int, sim_date: date) -> list[ScheduledJob]:
        """Compute the deterministic job schedule for a given day."""
        rng = random.Random(self._seed + day_no * 1000)
        jobs: list[ScheduledJob] = []

        db_path = self._out_dir / "data" / "district.db"
        truth_dir = self._out_dir / "logs" / "_truth"

        # 1. Schedule nightly_export
        # Window: 01:00 to 02:30 (90 minutes)
        export_script = self._jobs_dir / "nightly_export.py"
        export_offset_min = rng.randint(0, 90)
        export_time = datetime.combine(sim_date, time(1, 0)) + timedelta(minutes=export_offset_min)

        # Volume variation: base 240 +/- 30%
        base_rows = 240
        if self._config:
            base_rows = rng.randint(
                self._config.jobs.nightly_export.rows_per_run.low,
                self._config.jobs.nightly_export.rows_per_run.high,
            )
            var = self._config.jobs.nightly_export.volume_variation
            row_count = int(base_rows * (1.0 + rng.uniform(-var, var)))
            network_down_prob = self._config.jobs.nightly_export.network_down_probability
        else:
            row_count = int(base_rows * (1.0 + rng.uniform(-0.30, 0.30)))
            network_down_prob = 0.12

        is_network_down = rng.random() < network_down_prob

        export_args = [
            "--db-path", str(db_path),
            "--out-dir", str(self._out_dir),
            "--truth-log", str(truth_dir / "nightly_export.jsonl"),
            "--sim-date", sim_date.isoformat(),
            "--sim-time", export_time.strftime("%H:%M"),
            "--seed", str(rng.randint(1, 1000000)),
            "--row-count", str(max(1, row_count)),
        ]
        if is_network_down:
            export_args.append("--network-down")

        jobs.append(
            ScheduledJob(
                job_name="nightly_export",
                scheduled_time=export_time,
                script_path=export_script,
                arguments=tuple(export_args),
                details={"row_count": row_count, "network_down": is_network_down},
            )
        )

        # 2. Schedule allocation_gen
        # Window: 23:15 to 00:45
        # Can be scheduled before or after midnight. For clarity within the day run,
        # we schedule it at 23:15 + offset (up to 90 min).
        alloc_script = self._jobs_dir / "allocation_gen.py"
        alloc_offset_min = rng.randint(0, 90)
        alloc_time = datetime.combine(sim_date, time(23, 15)) + timedelta(minutes=alloc_offset_min)

        is_month_start = (day_no == 1)
        if self._config:
            topup_count = rng.randint(
                self._config.jobs.allocation_gen.files_on_a_top_up.low,
                self._config.jobs.allocation_gen.files_on_a_top_up.high,
            )
            double_run_prob = self._config.jobs.allocation_gen.double_run_probability
        else:
            topup_count = rng.randint(3, 12)
            double_run_prob = 0.15

        alloc_args = [
            "--db-path", str(db_path),
            "--out-dir", str(self._out_dir),
            "--truth-log", str(truth_dir / "allocation_gen.jsonl"),
            "--sim-date", sim_date.isoformat(),
            "--sim-time", alloc_time.strftime("%H:%M"),
            "--seed", str(rng.randint(1, 1000000)),
            "--shop-count", str(50 if is_month_start else topup_count),
        ]
        if is_month_start:
            alloc_args.append("--is-month-start")

        jobs.append(
            ScheduledJob(
                job_name="allocation_gen",
                scheduled_time=alloc_time,
                script_path=alloc_script,
                arguments=tuple(alloc_args),
                details={"is_month_start": is_month_start, "shop_count": 50 if is_month_start else topup_count},
            )
        )

        # Handle vendor double-run bug
        if rng.random() < double_run_prob:
            second_time = alloc_time + timedelta(minutes=rng.randint(5, 20))
            jobs.append(
                ScheduledJob(
                    job_name="allocation_gen",
                    scheduled_time=second_time,
                    script_path=alloc_script,
                    arguments=tuple(alloc_args),
                    details={"is_month_start": is_month_start, "double_run": True},
                )
            )

        jobs.sort(key=lambda j: j.scheduled_time)
        return jobs

    def execute_job(self, scheduled: ScheduledJob) -> JobRun:
        """Run a scheduled job, advance the clock, and record file activity."""
        # Advance clock to start time if not already there
        if self._clock.current_time < scheduled.scheduled_time:
            self._clock.advance_to(scheduled.scheduled_time)

        start_time = self._clock.current_time
        script_sha = _hash_file(scheduled.script_path) if scheduled.script_path.is_file() else ""

        # Snapshot before
        before_state = _snapshot_dir(self._out_dir)

        # Execute as subprocess (zero imports from Nightkeep)
        cmd = (sys.executable, str(scheduled.script_path), *scheduled.arguments)
        proc = subprocess.run(
            cmd,
            cwd=str(self._out_dir),
            capture_output=True,
            text=True,
        )

        # Advance clock by simulated run duration (e.g. 3 minutes)
        simulated_duration = timedelta(minutes=3)
        self._clock.advance(simulated_duration)
        end_time = self._clock.current_time

        # Snapshot after
        after_state = _snapshot_dir(self._out_dir)

        created = tuple(sorted(p for p in after_state if p not in before_state))
        modified = tuple(
            sorted(
                p for p in after_state
                if p in before_state and after_state[p] != before_state[p]
            )
        )
        deleted = tuple(sorted(p for p in before_state if p not in after_state))

        touched_folders = tuple(
            sorted(
                {str(Path(p).parent) for p in (*created, *modified, *deleted) if str(Path(p).parent) != "."}
            )
        )

        bytes_written = sum(after_state[p][1] for p in (*created, *modified) if p in after_state)
        extensions = tuple(
            sorted({Path(p).suffix.lower() for p in (*created, *modified) if Path(p).suffix})
        )

        run = JobRun(
            job_name=scheduled.job_name,
            command=cmd,
            script_path=str(scheduled.script_path),
            script_sha256=script_sha,
            start_time=start_time,
            end_time=end_time,
            exit_code=proc.returncode,
            files_created=created,
            files_modified=modified,
            files_deleted=deleted,
            folders_touched=touched_folders,
            bytes_written=bytes_written,
            extensions=extensions,
            details=scheduled.details,
        )

        self._history.append(run)
        return run

    def run_day(self, day_no: int, sim_date: date | None = None) -> list[JobRun]:
        """Run all jobs scheduled for day_no."""
        if sim_date is None:
            # Anchor relative to clock
            sim_date = self._clock.current_time.date()

        scheduled_jobs = self.schedule_day(day_no, sim_date)
        day_runs: list[JobRun] = []
        for job in scheduled_jobs:
            run = self.execute_job(job)
            day_runs.append(run)

        # Advance to end of the day if needed
        end_of_day = datetime.combine(sim_date + timedelta(days=1), time(0, 0))
        if self._clock.current_time < end_of_day:
            self._clock.advance_to(end_of_day)

        return day_runs
