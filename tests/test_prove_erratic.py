"""prove_erratic: the learning week, run end to end, read back from truth.

Covers ticket #5. The week is lived exactly as the demo lives it, jobs and
all, and everything is read the way the summary reads it: out of the jobs'
own ground-truth logs. Three weeks are run once each, at module scope,
because running one takes the better part of a minute.
"""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from nightkeep.__main__ import main
from nightkeep.config import District, Span, load_config
from nightkeep.mock_pds import prove_erratic

REPO_CONFIG = Path(__file__).resolve().parent.parent / "nightkeep" / "config.yaml"
REPO = load_config(REPO_CONFIG)

SEED = 20260922
OTHER_SEED = 31415926
# A small district and short days keep three whole weeks inside a test run.
# Neither changes what the jobs do, only how much and how fast.
DISTRICT = District(
    ration_cards=200,
    fps_count=10,
    members_per_card=Span(low=1, high=5),
    transactions_per_card_per_month=Span(low=0, high=2),
)
FAST_CLOCK = replace(REPO.clock, simulated_day_seconds=6)
JOBS = tuple(sorted(vars(REPO.jobs)))
SURGE_NIGHTS = set(REPO.harvest_surge.days)


def _week(tmp_path_factory, name: str, seed: int) -> dict:
    return prove_erratic.prove(
        seed=seed, district=DISTRICT, clock=FAST_CLOCK, jobs=REPO.jobs,
        harvest_surge=REPO.harvest_surge,
        out_dir=tmp_path_factory.mktemp(name) / "district",
    )


@pytest.fixture(scope="module")
def week(tmp_path_factory) -> dict:
    return _week(tmp_path_factory, "week", SEED)


@pytest.fixture(scope="module")
def week_again(tmp_path_factory) -> dict:
    return _week(tmp_path_factory, "week_again", SEED)


@pytest.fixture(scope="module")
def other_week(tmp_path_factory) -> dict:
    return _week(tmp_path_factory, "other_week", OTHER_SEED)


def _report_bytes(tmp_path_factory, name: str, seed: int) -> bytes:
    """Run a week and read back the report file prove() leaves behind."""
    out_dir = tmp_path_factory.mktemp(name) / "district"
    prove_erratic.prove(
        seed=seed, district=DISTRICT, clock=FAST_CLOCK, jobs=REPO.jobs,
        harvest_surge=REPO.harvest_surge, out_dir=out_dir,
    )
    return (out_dir / "reports" / prove_erratic.SUMMARY_NAME).read_bytes()


def _ordinary_night_swing(summary: dict) -> float:
    """How far the export's rows move, harvest surge nights left out.

    The surge doubles a night on purpose, so counting it would let a week of
    otherwise identical nights look erratic.
    """
    by_night = summary["jobs"]["nightly_export"]["rows"]["by_night"]
    counts = [
        rows for night, rows in by_night.items() if int(night) not in SURGE_NIGHTS
    ]
    return (max(counts) - min(counts)) / (sum(counts) / len(counts)) * 100


def _small_config(tmp_path: Path) -> Path:
    """The repo's own config.yaml, shrunk to a district a test can afford."""
    text = REPO_CONFIG.read_text(encoding="utf-8")
    path = tmp_path / "config.yaml"
    path.write_text(
        text.replace(f"ration_cards: {REPO.district.ration_cards}", "ration_cards: 200"),
        encoding="utf-8",
    )
    return path


def test_one_command_runs_the_week_and_leaves_a_summary(tmp_path, capsys):
    out_dir = tmp_path / "district"

    exit_code = main([
        str(_small_config(tmp_path)), "--prove-erratic",
        "--seed", str(SEED), "--out-dir", str(out_dir), "--day-seconds", "1",
    ])

    assert exit_code == 0
    summary = json.loads(
        (out_dir / "reports" / prove_erratic.SUMMARY_NAME).read_text(encoding="utf-8")
    )
    assert summary["seed"] == SEED
    assert summary["days"] == REPO.clock.learning_days
    assert set(summary["jobs"]) == set(JOBS)
    # The person running it sees the week without opening the JSON.
    printed = capsys.readouterr().out
    assert "nightly_export" in printed and "rows carried" in printed


def test_the_week_is_the_seven_learning_days(week):
    assert week["days"] == 7
    for job in JOBS:
        entry = week["jobs"][job]
        assert entry["nights_ran"] + entry["nights_skipped"] == 7


def test_every_job_reports_what_the_ticket_asks_for(week):
    for job in JOBS:
        entry = week["jobs"][job]
        assert entry["start_time"]["spread_minutes"] >= 0
        assert isinstance(entry["extensions"], list)
        for kind in ("created", "modified", "renamed", "deleted"):
            assert set(entry["files"][kind]) == {"low", "high", "spread"}
        assert set(entry["bytes_written"]) == {"low", "high", "spread"}


def test_the_old_file_clean_up_runs_on_some_nights_and_not_others(week):
    # The rhythm is the point: the exports pile up, the clean-up zips them and
    # deletes the originals, the folder drops back under the line, and the job
    # goes quiet until they pile up again.
    archive_old = week["jobs"]["archive_old"]

    assert 0 < archive_old["nights_ran"] < 7
    assert archive_old["nights_skipped"] > 0
    assert archive_old["skipped_because"] == ["below size threshold"]


def test_the_day_end_exports_row_count_moves_by_roughly_a_third(week):
    rows = week["jobs"]["nightly_export"]["rows"]

    # Counted by the export itself, not re-derived from the database.
    assert rows["low"] >= 1
    # config.yaml draws each night within 30 percent either side of the
    # midpoint, so an ordinary week's nights should span about a third of one.
    assert _ordinary_night_swing(week) >= 33


def test_the_undocumented_script_runs_on_some_nights_and_not_others(week):
    fix_dat = week["jobs"]["fix_dat"]

    assert 0 < fix_dat["nights_ran"] < 7
    assert fix_dat["nights_skipped"] > 0


def test_no_job_starts_at_the_same_time_every_night(week):
    for job in JOBS:
        assert week["jobs"][job]["start_time"]["spread_minutes"] > 0


def test_the_same_seed_reproduces_the_same_week(week, week_again):
    # The whole summary, start times included, with nothing left out. Run
    # lengths are seeded rather than measured, so an overrun shoves the next
    # job by the same amount on every machine and the clock in the truth log
    # is the seed's business alone.
    assert week == week_again


def test_the_same_seed_writes_a_byte_for_byte_identical_report(
    tmp_path_factory,
):
    # The file itself, not just the dict: the summary is a deliverable, and
    # two runs of one seed must hand a judge the same bytes.
    first = _report_bytes(tmp_path_factory, "report_once", SEED)
    second = _report_bytes(tmp_path_factory, "report_twice", SEED)

    assert first == second


def test_a_different_seed_gives_a_different_but_equally_messy_week(week, other_week):
    assert other_week != week

    for job in JOBS:
        assert other_week["jobs"][job]["start_time"]["spread_minutes"] > 0
    assert _ordinary_night_swing(other_week) >= 33
    assert 0 < other_week["jobs"]["fix_dat"]["nights_ran"] < 7
    assert other_week["jobs"]["allocation_gen"]["files"]["created"]["spread"] > 0


def test_it_leaves_a_folder_it_did_not_build_alone(tmp_path):
    somewhere_else = tmp_path / "not_a_district"
    somewhere_else.mkdir()
    (somewhere_else / "important.txt").write_text("keep me", encoding="utf-8")

    exit_code = main(["--prove-erratic", "--out-dir", str(somewhere_else)])

    assert exit_code == 1
    assert (somewhere_else / "important.txt").read_text(encoding="utf-8") == "keep me"
