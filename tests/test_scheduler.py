"""Tests for Feature 2: Simulated Clock, Scheduler, and First Two Night Tasks."""

import ast
import json
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytest

from nightkeep.config import District, Span
from nightkeep.mock_pds import build_district, run_day
from nightkeep.mock_pds.clock import SimulatedClock
from nightkeep.mock_pds.scheduler import DEFAULT_JOBS_DIR, Scheduler
from nightkeep.types import JobRun

DISTRICT = District(
    ration_cards=50,
    fps_count=10,
    members_per_card=Span(low=1, high=3),
    transactions_per_card_per_month=Span(low=1, high=2),
)


# --- 1. Clock Tests ---------------------------------------------------

def test_simulated_clock_advancement():
    start = datetime(2026, 9, 13, 0, 0, 0)
    clock = SimulatedClock(start)

    assert clock.now() == start
    assert clock.current_time == start

    # Advance by 2 hours
    clock.advance(timedelta(hours=2))
    assert clock.now() == datetime(2026, 9, 13, 2, 0, 0)

    # Advance to target
    target = datetime(2026, 9, 13, 5, 30, 0)
    clock.advance_to(target)
    assert clock.now() == target

    # Backward movement is rejected
    with pytest.raises(ValueError):
        clock.advance(timedelta(minutes=-1))

    with pytest.raises(ValueError):
        clock.advance_to(datetime(2026, 9, 13, 4, 0, 0))


def test_clock_from_date():
    clock = SimulatedClock.from_date(date(2026, 9, 22), time(1, 30))
    assert clock.now() == datetime(2026, 9, 22, 1, 30, 0)


# --- 2. Safety Rail Tests: Jobs have zero Nightkeep imports -----------

def test_jobs_have_zero_nightkeep_imports():
    for script_path in DEFAULT_JOBS_DIR.glob("*.py"):
        tree = ast.parse(script_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("nightkeep"), (
                        f"{script_path.name} must have zero imports from nightkeep"
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    assert not node.module.startswith("nightkeep"), (
                        f"{script_path.name} must have zero imports from nightkeep"
                    )


def test_no_aadhaar_no_in_job_scripts():
    for script_path in DEFAULT_JOBS_DIR.glob("*.py"):
        tree = ast.parse(script_path.read_text(encoding="utf-8"))
        names = {
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name)
        } | {
            node.arg
            for node in ast.walk(tree)
            if isinstance(node, ast.arg)
        }
        assert "aadhaar_no" not in names, f"{script_path.name} contains forbidden name aadhaar_no"


# --- 3. First Two Jobs: Standalone Subprocess Execution ---------------

def test_build_district_deploys_jobs_and_folders(tmp_path):
    out_dir = build_district(20260922, DISTRICT, tmp_path / "district")
    assert (out_dir / "jobs" / "nightly_export.py").is_file()
    assert (out_dir / "jobs" / "allocation_gen.py").is_file()
    assert (out_dir / "exports").is_dir()
    assert (out_dir / "allocations").is_dir()
    assert (out_dir / "logs").is_dir()


def test_nightly_export_creates_csv_and_truth_log(tmp_path):
    out_dir = build_district(20260922, DISTRICT, tmp_path / "district")
    clock = SimulatedClock(datetime(2026, 9, 13, 1, 0, 0))
    # seed=20260922 produces a normal run (network_down=False)
    scheduler = Scheduler(clock, out_dir=out_dir, seed=20260922)

    jobs = scheduler.schedule_day(day_no=1, sim_date=date(2026, 9, 13))
    export_job = next(j for j in jobs if j.job_name == "nightly_export")
    assert export_job.details["network_down"] is False

    run = scheduler.execute_job(export_job)

    assert run.exit_code == 0
    assert run.job_name == "nightly_export"
    assert run.script_sha256 != ""
    assert any("exports" in f for f in run.files_created)

    # Verify CSV file content
    csv_files = list((out_dir / "exports").glob("*.csv"))
    assert len(csv_files) == 1
    content = csv_files[0].read_text(encoding="utf-8")
    assert "transaction_id,card_no,fps_id" in content

    # Verify truth log
    truth_file = out_dir / "logs" / "_truth" / "nightly_export.jsonl"
    assert truth_file.is_file()
    lines = truth_file.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["job"] == "nightly_export"
    assert record["status"] == "SUCCESS"
    assert record["rows_exported"] > 0


def test_nightly_export_network_down(tmp_path):
    out_dir = build_district(42, DISTRICT, tmp_path / "district")
    clock = SimulatedClock(datetime(2026, 9, 13, 1, 0, 0))
    # seed=42 produces network_down=True on day 1
    scheduler = Scheduler(clock, out_dir=out_dir, seed=42)

    jobs = scheduler.schedule_day(day_no=1, sim_date=date(2026, 9, 13))
    export_job = next(j for j in jobs if j.job_name == "nightly_export")
    assert export_job.details["network_down"] is True

    run = scheduler.execute_job(export_job)

    assert run.exit_code == 0
    # No CSV files written in exports
    csv_files = list((out_dir / "exports").glob("*.csv"))
    assert len(csv_files) == 0

    # Truth log records network down
    truth_file = out_dir / "logs" / "_truth" / "nightly_export.jsonl"
    assert truth_file.is_file()
    record = json.loads(truth_file.read_text(encoding="utf-8").strip().split("\n")[0])
    assert record["status"] == "SKIPPED_NETWORK_DOWN"
    assert record["rows_exported"] == 0


def test_allocation_gen_month_start_vs_topup(tmp_path):
    out_dir = build_district(20260922, DISTRICT, tmp_path / "district")
    clock = SimulatedClock(datetime(2026, 9, 13, 23, 0, 0))
    scheduler = Scheduler(clock, out_dir=out_dir, seed=42)

    # Day 1 is month start (generates for all shops in DISTRICT: 10 shops)
    day1_jobs = scheduler.schedule_day(day_no=1, sim_date=date(2026, 9, 1))
    alloc_job_day1 = next(j for j in day1_jobs if j.job_name == "allocation_gen")
    run_day1 = scheduler.execute_job(alloc_job_day1)

    assert run_day1.exit_code == 0
    alloc_files_day1 = list((out_dir / "allocations").glob("*.csv"))
    assert len(alloc_files_day1) == 10  # 10 shops in test DISTRICT

    # Truth log check
    truth_file = out_dir / "logs" / "_truth" / "allocation_gen.jsonl"
    assert truth_file.is_file()
    record1 = json.loads(truth_file.read_text(encoding="utf-8").strip().split("\n")[0])
    assert record1["is_month_start"] is True
    assert record1["shops_allocated"] == 10


# --- 4. Scheduler Determinism & Repeatability -------------------------

def test_scheduler_run_day_is_deterministic(tmp_path):
    out_dir_a = build_district(42, DISTRICT, tmp_path / "a")
    out_dir_b = build_district(42, DISTRICT, tmp_path / "b")

    runs_a = run_day(day_no=2, out_dir=out_dir_a, seed=12345, sim_date=date(2026, 9, 14))
    runs_b = run_day(day_no=2, out_dir=out_dir_b, seed=12345, sim_date=date(2026, 9, 14))

    assert len(runs_a) == len(runs_b)
    for r_a, r_b in zip(runs_a, runs_b):
        assert r_a.job_name == r_b.job_name
        assert r_a.start_time == r_b.start_time
        assert r_a.exit_code == r_b.exit_code
        assert r_a.files_created == r_b.files_created
        assert r_a.bytes_written == r_b.bytes_written
        assert r_a.script_sha256 == r_b.script_sha256


def test_scheduler_different_days_produce_variation(tmp_path):
    out_dir = build_district(42, DISTRICT, tmp_path / "district")

    runs_day1 = run_day(day_no=1, out_dir=out_dir, seed=42, sim_date=date(2026, 9, 13))
    runs_day2 = run_day(day_no=2, out_dir=out_dir, seed=42, sim_date=date(2026, 9, 14))

    # Times and volumes should vary
    time1 = runs_day1[0].start_time.time()
    time2 = runs_day2[0].start_time.time()
    assert time1 != time2 or runs_day1[0].bytes_written != runs_day2[0].bytes_written


def test_run_day_advances_simulated_time_without_wall_clock_sleep(tmp_path):
    out_dir = build_district(42, DISTRICT, tmp_path / "district")

    start_real = datetime.now()
    runs = run_day(day_no=1, out_dir=out_dir, seed=42, sim_date=date(2026, 9, 13))
    elapsed_real_seconds = (datetime.now() - start_real).total_seconds()

    # An entire 24h simulated day executes in less than 5 seconds of real time
    assert elapsed_real_seconds < 5.0
    assert len(runs) >= 2
