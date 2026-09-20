"""run_day(day_no, ...): one simulated day on the Thane district PDS server.

Covers ticket #3. Everything is observed the way anyone else would observe
it: through the database, the files on disk and the jobs' own ground-truth
logs. Expected values come from the ticket and config.yaml's documented
ranges, never from re-running the scheduler's own draws.
"""

import csv
import json
import sqlite3
import time as wall
from dataclasses import replace
from datetime import date, datetime, time, timedelta
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
# subprocess overhead (measured up to ~1s) drifts a job past its own window
# once scaled up. The pacing test uses its own length.
FAST_CLOCK = replace(REPO.clock, simulated_day_seconds=6)
NETWORK_UP = replace(
    REPO.jobs,
    nightly_export=replace(REPO.jobs.nightly_export, network_down_probability=0.0),
)
NETWORK_DOWN = replace(
    REPO.jobs,
    nightly_export=replace(REPO.jobs.nightly_export, network_down_probability=1.0),
)
# The clean-up put out of reach, for the tests that read exports back off disk
# days later. archive_old legitimately zips and deletes them once the folder
# crosses its threshold, which is a few nights' worth.
NO_CLEAN_UP = replace(
    NETWORK_UP,
    archive_old=replace(NETWORK_UP.archive_old, size_threshold_kb=1_000_000),
)
# Day 1 is the day after the district was built (SIMULATED_TODAY, 26 Sept).
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


def test_the_month_starts_on_a_learning_day_that_is_not_a_harvest_day():
    # The allotment job's big run on the 1st must be seen while learning, and
    # not on a surge day, or the habit cards learn the two tangled together.
    learning = range(1, REPO.clock.learning_days + 1)
    month_starts = [
        day_no for day_no in learning
        if (c.SIMULATED_TODAY + timedelta(days=day_no)).day
        == REPO.jobs.allocation_gen.month_start_day
    ]

    assert month_starts == [5]
    assert not set(month_starts) & set(REPO.harvest_surge.days)


def test_a_day_takes_about_one_simulated_day_of_real_time(tmp_path):
    district_dir = _district(tmp_path)
    clock = replace(REPO.clock, simulated_day_seconds=6)

    started = wall.monotonic()
    _run(district_dir, 1, clock=clock)
    elapsed = wall.monotonic() - started

    assert 6.0 <= elapsed < 9.0


def _transactions_on(district_dir: Path, day: date) -> list[tuple]:
    conn = sqlite3.connect(district_dir / "data" / "district.db")
    try:
        return conn.execute(
            "SELECT t.occurred_at, t.allotment_month, t.fps_id, c.fps_id "
            "FROM transactions t JOIN cards c ON c.card_no = t.card_no "
            "WHERE substr(t.occurred_at, 1, 10) = ?",
            (day.isoformat(),),
        ).fetchall()
    finally:
        conn.close()


def test_the_days_transactions_land_in_shop_hours_at_the_cards_own_shop(tmp_path):
    district_dir = _district(tmp_path)
    assert _transactions_on(district_dir, DAY_ONE) == []

    _run(district_dir, 1)

    rows = _transactions_on(district_dir, DAY_ONE)
    rows_per_run = REPO.jobs.nightly_export.rows_per_run
    assert rows_per_run.low <= len(rows) <= rows_per_run.high
    for occurred_at, allotment_month, fps_id, card_fps_id in rows:
        # ePoS counters are open 09:00 to 18:00.
        assert time(9, 0) <= datetime.fromisoformat(occurred_at).time() < time(18, 0)
        assert allotment_month == "2026-09"
        assert fps_id == card_fps_id


TRUTH_FIELDS = {
    "job", "day", "sim_start", "sim_end", "skipped", "created", "modified",
    "renamed", "deleted", "bytes_written", "extensions",
}
# The export carries a row count of its own, so the week's summary can report
# how far its volume moves without re-deriving it from the database.
EXPORT_FIELDS = TRUTH_FIELDS | {"rows"}


def _truth(district_dir: Path, job: str) -> list[dict]:
    log = district_dir / "logs" / "_truth" / f"{job}.jsonl"
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def _csv_rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_the_day_end_export_writes_the_days_transactions_in_its_window(tmp_path):
    district_dir = _district(tmp_path)
    _run(district_dir, 1)

    [line] = _truth(district_dir, "nightly_export")
    assert set(line) == EXPORT_FIELDS
    assert line["job"] == "nightly_export" and line["day"] == 1
    assert line["skipped"] is None

    started = datetime.fromisoformat(line["sim_start"])
    # The night after 27 Sept, between 01:00 and 02:30 (config.yaml).
    assert started.date() == DAY_ONE + timedelta(days=1)
    assert time(1, 0) <= started.time() <= time(2, 30)
    assert datetime.fromisoformat(line["sim_end"]) >= started

    [created] = line["created"]
    export = district_dir / created
    assert export.parent == district_dir / "share" / "exports"
    assert export.suffix == ".csv"
    assert line["modified"] == line["renamed"] == line["deleted"] == []
    assert line["extensions"] == [".csv"]
    assert line["bytes_written"] == export.stat().st_size

    rows = _csv_rows(export)
    assert len(rows) == len(_transactions_on(district_dir, DAY_ONE))
    for row in rows:
        assert row["occurred_at"].startswith(DAY_ONE.isoformat())
        assert len(row["card_no"]) == 12
        assert len(row["quantity_kg"].split(".")[1]) == 3


def test_the_export_skips_a_network_down_night_and_says_so(tmp_path):
    district_dir = _district(tmp_path)
    _run(district_dir, 1, jobs=NETWORK_DOWN)

    [line] = _truth(district_dir, "nightly_export")
    assert line["skipped"] == "network down"
    assert line["created"] == line["modified"] == []
    assert line["bytes_written"] == 0
    assert list((district_dir / "share" / "exports").iterdir()) == []


def test_the_export_row_count_moves_with_each_days_transactions(tmp_path):
    district_dir = _district(tmp_path)
    for day_no in (1, 2, 3):
        _run(district_dir, day_no, jobs=NO_CLEAN_UP)

    counts = []
    for day_no, line in enumerate(_truth(district_dir, "nightly_export"), start=1):
        assert line["day"] == day_no
        business_day = DAY_ONE + timedelta(days=day_no - 1)
        rows = _csv_rows(district_dir / line["created"][0])
        assert len(rows) == len(_transactions_on(district_dir, business_day))
        counts.append(len(rows))

    # 180 to 320 rows, roughly a third either side of 250 (config.yaml).
    assert all(180 <= count <= 320 for count in counts)
    assert len(set(counts)) > 1


def test_the_safe_copy_follows_the_export_even_on_a_network_down_night(tmp_path):
    # Slow enough that neither job overruns into the other's slot. At 1 s a
    # day, a 0.15 s job takes four simulated hours.
    clock = replace(REPO.clock, simulated_day_seconds=10)
    district_dir = _district(tmp_path)
    _run(district_dir, 1, jobs=NETWORK_UP, clock=clock)
    _run(district_dir, 2, jobs=NETWORK_DOWN, clock=clock)

    exports = _truth(district_dir, "nightly_export")
    backups = _truth(district_dir, "db_backup")
    assert [line["day"] for line in backups] == [1, 2]
    for export, backup in zip(exports, backups):
        assert set(backup) == TRUTH_FIELDS
        gap = datetime.fromisoformat(backup["sim_start"]) - datetime.fromisoformat(export["sim_start"])
        # 10 to 45 minutes after the export starts (config.yaml).
        assert timedelta(minutes=10) <= gap <= timedelta(minutes=45)


def test_the_safe_copy_is_a_readable_database_that_grows_through_the_month(tmp_path):
    district_dir = _district(tmp_path)
    _run(district_dir, 1)
    _run(district_dir, 2)

    sizes = []
    for line in _truth(district_dir, "db_backup"):
        assert line["skipped"] is None
        [created] = line["created"]
        copy = district_dir / created
        # ADR-0007: in the share, where the Vault pulls it from.
        assert copy.parent == district_dir / "share" / "backups"
        assert line["extensions"] == [".db"]
        assert line["bytes_written"] == copy.stat().st_size
        conn = sqlite3.connect(copy)
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 200
        conn.close()
        sizes.append(line["bytes_written"])

    assert sizes[1] > sizes[0]


def test_the_safe_copy_never_overlaps_the_export_and_reports_when_it_really_began(tmp_path):
    # The safe copy may not start before the export has finished, and its
    # truth line must say when it really began. Both times come from the
    # seed, so this holds at any day length rather than only at one that
    # happens to make the export overrun in real time.
    district_dir = _district(tmp_path)
    _run(district_dir, 1)

    [export] = _truth(district_dir, "nightly_export")
    [backup] = _truth(district_dir, "db_backup")
    assert datetime.fromisoformat(backup["sim_start"]) >= datetime.fromisoformat(export["sim_end"])


def test_the_same_seed_replays_the_same_day(tmp_path):
    first = _district(tmp_path, "first")
    second = _district(tmp_path, "second")
    for district_dir in (first, second):
        _run(district_dir, 1)
        _run(district_dir, 2)

    for job in ("nightly_export", "db_backup"):
        for a, b in zip(_truth(first, job), _truth(second, job), strict=True):
            # The whole truth line, timing included. Run lengths are drawn
            # from the seed, not measured, so two replays agree on the clock
            # as exactly as they agree on what each job did.
            assert a == b
            for name in a["created"]:
                assert (first / name).read_bytes() == (second / name).read_bytes()

    [a] = _truth(first, "nightly_export")[:1]
    [b] = _truth(second, "nightly_export")[:1]
    # The export's own start is drawn from the seed, and never runs late.
    assert a["sim_start"] == b["sim_start"]
