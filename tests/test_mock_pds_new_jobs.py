"""The four remaining erratic jobs and the harvest surge. Covers ticket #4.

Same approach as test_mock_pds_day.py: everything is observed through the
database, the files on disk and the jobs' own ground-truth logs, never by
re-running the scheduler's own draws.
"""

import json
import zipfile
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

from nightkeep.config import Clock, District, Jobs, Span, load_config
from nightkeep.mock_pds import build_district, run_day
from nightkeep.mock_pds import conventions as c

REPO_CONFIG = Path(__file__).resolve().parent.parent / "nightkeep" / "config.yaml"
REPO = load_config(REPO_CONFIG)

SEED = 20260922
DISTRICT = District(
    ration_cards=200,
    fps_count=10,
    members_per_card=Span(low=1, high=5),
    transactions_per_card_per_month=Span(low=0, high=2),
)
# Short days keep the suite fast, but not so short that six real jobs'
# subprocess overhead drifts a job past its own window once scaled up.
FAST_CLOCK = replace(REPO.clock, simulated_day_seconds=6)
NETWORK_UP = replace(
    REPO.jobs,
    nightly_export=replace(REPO.jobs.nightly_export, network_down_probability=0.0),
)
# Day 1 is 27 Sept 2026, a Sunday. Day 2, 28 Sept, is a Monday.
DAY_ONE = date(2026, 9, 27)


def _district(tmp_path: Path, name: str = "district") -> Path:
    return build_district(SEED, DISTRICT, tmp_path / name)


def _run(
    district_dir: Path, day_no: int, jobs: Jobs = NETWORK_UP, clock: Clock = FAST_CLOCK,
    harvest_surge_override: bool | None = None,
):
    run_day(
        day_no, seed=SEED, clock=clock, jobs=jobs, harvest_surge=REPO.harvest_surge,
        district_dir=district_dir, harvest_surge_override=harvest_surge_override,
    )


TRUTH_FIELDS = {
    "job", "day", "sim_start", "sim_end", "skipped", "created", "modified",
    "renamed", "deleted", "bytes_written", "extensions",
}


def _truth(district_dir: Path, job: str) -> list[dict]:
    log = district_dir / "logs" / "_truth" / f"{job}.jsonl"
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


# --- allocation_gen ---------------------------------------------------------


NO_DOUBLE_RUN = replace(
    NETWORK_UP, allocation_gen=replace(REPO.jobs.allocation_gen, double_run_probability=0.0)
)


def test_allocation_gen_writes_tmp_files_named_after_real_shops(tmp_path):
    district_dir = _district(tmp_path)
    _run(district_dir, 2, jobs=NO_DOUBLE_RUN)  # 28 Sept: a top-up night, not the 1st

    [line] = _truth(district_dir, "allocation_gen")
    assert set(line) == TRUTH_FIELDS
    assert line["skipped"] is None
    assert line["modified"] == line["renamed"] == line["deleted"] == []
    span = REPO.jobs.allocation_gen.files_on_a_top_up
    assert span.low <= len(line["created"]) <= min(span.high, DISTRICT.fps_count)
    assert line["extensions"] == [".tmp"]
    for name in line["created"]:
        path = district_dir / name
        assert path.parent == district_dir / "share" / "allocations"
        assert path.suffix == ".tmp"
        assert path.read_text(encoding="utf-8").startswith("fps_id=")


def test_allocation_gen_big_run_lands_on_the_month_start_day(tmp_path):
    district_dir = _district(tmp_path)
    _run(district_dir, 5, jobs=NO_DOUBLE_RUN)  # 1 Oct, config.yaml's month_start_day

    [line] = _truth(district_dir, "allocation_gen")
    # The test district only has 10 shops, so the requested 50-file run
    # is naturally capped at one file per real shop.
    assert len(line["created"]) == DISTRICT.fps_count


def test_allocation_gen_sometimes_runs_twice_the_vendor_bug(tmp_path):
    always_double = replace(
        REPO.jobs,
        nightly_export=NETWORK_UP.nightly_export,
        allocation_gen=replace(REPO.jobs.allocation_gen, double_run_probability=1.0),
    )
    district_dir = _district(tmp_path)
    _run(district_dir, 2, jobs=always_double)

    lines = _truth(district_dir, "allocation_gen")
    assert len(lines) == 2
    assert lines[0]["day"] == lines[1]["day"] == 2
    # The second pass finds the files the first pass just wrote.
    assert lines[0]["created"] != []
    assert lines[1]["modified"] == lines[0]["created"]
    assert lines[1]["created"] == []


# --- archive_old --------------------------------------------------------


def _seed_old_exports(district_dir: Path, count: int, size_bytes: int) -> None:
    exports = district_dir / "share" / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    for day in range(count):
        name = f"epos_day_end_202609{10 + day:02d}.csv"
        (exports / name).write_bytes(b"x" * size_bytes)


def test_archive_old_skips_below_its_size_threshold(tmp_path):
    district_dir = _district(tmp_path)
    _seed_old_exports(district_dir, 3, 100)
    seeded = {p.name for p in (district_dir / "share" / "exports").iterdir()}

    _run(district_dir, 2)

    [line] = _truth(district_dir, "archive_old")
    assert line["skipped"] is not None
    assert line["created"] == line["deleted"] == []
    # Nothing seeded was touched. (The night's own real export, written by
    # nightly_export, may also be sitting alongside them.)
    remaining = {p.name for p in (district_dir / "share" / "exports").iterdir()}
    assert seeded <= remaining


def test_archive_old_zips_and_deletes_only_its_own_pattern(tmp_path):
    tiny_threshold = replace(
        REPO.jobs, archive_old=replace(REPO.jobs.archive_old, size_threshold_mb=0)
    )
    district_dir = _district(tmp_path)
    _seed_old_exports(district_dir, 5, 100)
    exports = district_dir / "share" / "exports"
    # A trap-file stand-in: archive_old must never touch it (ticket's rail
    # against attack 10, SOLUTION_DESIGN.md).
    (exports / "trap_do_not_touch.csv").write_bytes(b"trap")

    _run(district_dir, 2, jobs=tiny_threshold)

    [line] = _truth(district_dir, "archive_old")
    assert line["skipped"] is None
    assert (exports / "trap_do_not_touch.csv").exists()
    remaining = {p.name for p in exports.iterdir()} - {"trap_do_not_touch.csv"}
    assert all(name.startswith("epos_day_end_") for name in remaining)

    [created] = line["created"]
    zip_path = district_dir / created
    assert zip_path.parent == district_dir / "archive"
    with zipfile.ZipFile(zip_path) as archive:
        assert all(name.startswith("epos_day_end_") for name in archive.namelist())
    for deleted in line["deleted"]:
        assert not (district_dir / deleted).exists()
        assert deleted.startswith("share/exports/epos_day_end_")


# --- fix_dat -------------------------------------------------------------


def test_fix_dat_renames_tmp_to_dat_only_on_a_night_it_runs(tmp_path):
    always_run = replace(REPO.jobs, fix_dat=replace(REPO.jobs.fix_dat, run_probability=1.0))
    district_dir = _district(tmp_path)
    _run(district_dir, 2, jobs=always_run)  # allocation_gen writes .tmp files first

    allocation_lines = _truth(district_dir, "allocation_gen")
    fix_lines = _truth(district_dir, "fix_dat")
    assert set(fix_lines[0]) == TRUTH_FIELDS
    assert fix_lines[0]["skipped"] is None
    assert sorted(fix_lines[0]["renamed"]) == sorted(
        name.removesuffix(".tmp") + ".dat" for name in allocation_lines[0]["created"]
    )
    for name in fix_lines[0]["renamed"]:
        path = district_dir / name
        assert path.suffix == ".dat"
        assert path.read_text(encoding="utf-8")  # still valid, readable text


def test_fix_dat_skips_a_night_it_does_not_run(tmp_path):
    never_run = replace(REPO.jobs, fix_dat=replace(REPO.jobs.fix_dat, run_probability=0.0))
    district_dir = _district(tmp_path)
    _run(district_dir, 2, jobs=never_run)

    [line] = _truth(district_dir, "fix_dat")
    assert line["skipped"] is not None
    assert line["renamed"] == line["modified"] == []


# --- operator_activity -----------------------------------------------------


def _ekyc_statuses(district_dir: Path) -> dict[int, str]:
    import sqlite3

    conn = sqlite3.connect(district_dir / "data" / "district.db")
    try:
        return dict(conn.execute("SELECT member_id, ekyc_status FROM members"))
    finally:
        conn.close()


def test_operator_activity_edits_records_on_a_weekday(tmp_path):
    district_dir = _district(tmp_path)
    before = _ekyc_statuses(district_dir)

    _run(district_dir, 2)  # 28 Sept, a Monday

    [line] = _truth(district_dir, "operator_activity")
    assert line["skipped"] is None
    assert line["modified"] == ["data/district.db"]
    assert line["extensions"] == [".db"]
    after = _ekyc_statuses(district_dir)
    assert before != after


def test_operator_activity_skips_sundays(tmp_path):
    district_dir = _district(tmp_path)
    before = _ekyc_statuses(district_dir)

    _run(district_dir, 1)  # 27 Sept, a Sunday

    [line] = _truth(district_dir, "operator_activity")
    assert line["skipped"] == "Sunday, office closed"
    assert line["modified"] == []
    assert _ekyc_statuses(district_dir) == before


# --- harvest surge -----------------------------------------------------


def _transactions_on(district_dir: Path, day: date) -> int:
    import sqlite3

    conn = sqlite3.connect(district_dir / "data" / "district.db")
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE substr(occurred_at, 1, 10) = ?",
            (day.isoformat(),),
        ).fetchone()[0]
    finally:
        conn.close()


def test_the_harvest_surge_doubles_the_days_transaction_volume(tmp_path):
    plain = _district(tmp_path, "plain")
    surged = _district(tmp_path, "surged")
    _run(plain, 2, harvest_surge_override=False)
    _run(surged, 2, harvest_surge_override=True)

    plain_count = _transactions_on(plain, DAY_ONE + timedelta(days=1))
    surged_count = _transactions_on(surged, DAY_ONE + timedelta(days=1))
    assert surged_count == round(plain_count * REPO.harvest_surge.multiplier)


def test_the_configured_surge_days_apply_without_an_override(tmp_path):
    district_dir = _district(tmp_path)
    _run(district_dir, REPO.harvest_surge.days[0])

    rows_per_run = REPO.jobs.nightly_export.rows_per_run
    business_day = DAY_ONE + timedelta(days=REPO.harvest_surge.days[0] - 1)
    assert _transactions_on(district_dir, business_day) > rows_per_run.high


# --- every job writes its own line, every day -------------------------------


def test_every_job_writes_exactly_one_truth_line_a_day(tmp_path):
    district_dir = _district(tmp_path)
    _run(district_dir, 2)

    for job in ("archive_old", "fix_dat", "operator_activity"):
        lines = _truth(district_dir, job)
        assert len(lines) == 1
        assert set(lines[0]) == TRUTH_FIELDS
        assert lines[0]["day"] == 2
