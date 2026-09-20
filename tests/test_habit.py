"""Habit cards: learn the mess, then notice when a night is not the mess.

The two things that must both be true, or the demo fails on stage:
a harvest-surge night must not look like an attack, and an attack must not
look like a harvest surge.
"""

from datetime import datetime, timedelta

import pytest

from nightkeep.habit import Habit, open_habit
from nightkeep.habit._features import circular_distance, clock_of, extract
from nightkeep.types import CREATED, DELETED, MODIFIED, RENAMED, Event, JobRun

IDENTITY = "python|jobs/nightly_export.py|abc123"
REAL = datetime(2026, 9, 22, 1, 30)


@pytest.fixture
def habit(tmp_path):
    return Habit(
        database=tmp_path / "habit.db",
        mad_multiplier=3.0,
        min_runs_before_scoring=3,
        minimum_spread_fraction=0.10,
    )


def run(
    *,
    day: int,
    created: int = 0,
    modified: int = 0,
    renamed: int = 0,
    deleted: int = 0,
    sim_hour: int = 1,
    sim_minute: int = 30,
    extension: str = ".csv",
    folder: str = "share/exports",
    job: str = "nightly_export",
    identity: str = IDENTITY,
    size: int = 1000,
) -> JobRun:
    """One job run, described by how many files of each kind it touched."""
    started = REAL + timedelta(days=day)
    events: list[Event] = []
    index = 0
    for kind, count in (
        (CREATED, created), (MODIFIED, modified),
        (RENAMED, renamed), (DELETED, deleted),
    ):
        for _ in range(count):
            index += 1
            events.append(
                Event(
                    path=f"{folder}/file_{kind}_{index}{extension}",
                    kind=kind,
                    at=started,
                    size=size,
                    old_path=f"{folder}/old_{index}.csv" if kind == RENAMED else None,
                )
            )
    return JobRun(
        job=job,
        identity=identity,
        started_at=started,
        finished_at=started + timedelta(seconds=40),
        events=tuple(events),
        sim_started_at=datetime(2026, 9, 1 + day, sim_hour, sim_minute),
        day_no=day,
    )


def teach(habit: Habit, runs: list[JobRun]) -> None:
    for one in runs:
        habit.learn(one)


# --- features --------------------------------------------------------------


def test_a_file_created_then_written_to_counts_once_as_created():
    """Watchdog fires several events for one write. A card counts files."""
    at = REAL
    job_run = JobRun(
        job="nightly_export",
        identity=IDENTITY,
        started_at=at,
        finished_at=at,
        events=(
            Event(path="share/exports/a.csv", kind=CREATED, at=at, size=10),
            Event(path="share/exports/a.csv", kind=MODIFIED, at=at, size=900),
            Event(path="share/exports/a.csv", kind=MODIFIED, at=at, size=1800),
        ),
    )
    features = extract(job_run)
    assert features.numbers["files_created"] == 1
    assert features.numbers["files_modified"] == 0
    assert features.numbers["bytes_written"] == 1800


def test_the_clock_reads_like_a_clock():
    assert clock_of(0) == "00:00"
    assert clock_of(1265) == "21:05"
    assert clock_of(1440) == "00:00"


def test_midnight_is_a_short_distance_from_late_evening():
    """The allotment job runs 23:15 to 00:45. Without this it looks insane."""
    eleven_fifteen = 23 * 60 + 15
    twelve_twenty = 20
    assert circular_distance(eleven_fifteen, twelve_twenty) == 65


# --- learning --------------------------------------------------------------


def test_a_job_seen_once_is_not_yet_judged(habit):
    habit.learn(run(day=1, created=1))
    result = habit.score(run(day=2, created=9999))
    assert result.value == 0.0
    assert result.is_first_sighting
    assert "not yet enough" in result.reasons[0]


def test_a_steady_job_on_a_steady_night_scores_zero(habit):
    teach(habit, [run(day=d, created=1, modified=2, size=1000) for d in range(1, 8)])
    result = habit.score(run(day=8, created=1, modified=2, size=1000))
    assert result.value == 0.0
    assert "within its usual range" in result.reasons[0]


def test_an_erratic_job_stays_within_its_own_erratic_range(habit):
    """Volumes wander by a third every night. That IS the habit."""
    volumes = [180, 240, 300, 220, 260, 200, 280]
    teach(habit, [run(day=d, created=v) for d, v in enumerate(volumes, start=1)])
    result = habit.score(run(day=8, created=255))
    assert result.value == 0.0


def test_a_harvest_surge_night_is_unusual_but_nowhere_near_certain(habit):
    """Legitimate, and it must not alarm. It may look odd; it may not be 1.0."""
    volumes = [180, 240, 300, 220, 260, 200, 280]
    teach(habit, [run(day=d, created=v, size=1000) for d, v in enumerate(volumes, start=1)])
    surge = habit.score(run(day=8, created=480, size=1000))
    assert 0.0 < surge.value < 1.0


def test_a_ransomware_night_looks_nothing_like_the_card(habit):
    volumes = [180, 240, 300, 220, 260, 200, 280]
    teach(habit, [run(day=d, created=v) for d, v in enumerate(volumes, start=1)])
    attack = habit.score(
        run(day=8, renamed=4812, modified=4812, sim_hour=3, sim_minute=41,
            extension=".locked", folder="data")
    )
    assert attack.value >= 0.5


def test_the_reasons_are_plain_numbers_a_clerk_could_read(habit):
    teach(habit, [run(day=d, created=240) for d in range(1, 8)])
    result = habit.score(run(day=8, created=4812))
    joined = " ".join(result.reasons)
    assert "4,812" in joined
    assert "usually" in joined
    for jargon in ("MAD", "median", "z-score", "sigma", "entropy"):
        assert jargon not in joined


def test_a_late_start_is_reported_as_a_time_not_a_number(habit):
    teach(habit, [run(day=d, created=240, sim_hour=1, sim_minute=30) for d in range(1, 8)])
    result = habit.score(run(day=8, created=240, sim_hour=4, sim_minute=40))
    joined = " ".join(result.reasons)
    assert "04:40" in joined
    assert "01:30" in joined


def test_an_unseen_file_type_is_called_out_by_name(habit):
    teach(habit, [run(day=d, created=240, extension=".csv") for d in range(1, 8)])
    result = habit.score(run(day=8, created=240, extension=".locked"))
    assert any(".locked" in reason for reason in result.reasons)


def test_a_job_whose_script_changed_starts_a_new_card(habit):
    """A vendor silently editing a script is exactly what we want to notice."""
    teach(habit, [run(day=d, created=240) for d in range(1, 8)])
    result = habit.score(run(day=8, created=240, identity="python|jobs/nightly_export.py|CHANGED"))
    assert result.value == 1.0
    assert result.is_first_sighting
    assert "changed" in result.reasons[0]


def test_a_job_that_never_varies_does_not_alarm_on_its_next_identical_run(habit):
    """A MAD of zero would otherwise make every single night an alarm."""
    teach(habit, [run(day=d, created=50, size=1000) for d in range(1, 8)])
    assert habit.score(run(day=8, created=50, size=1000)).value == 0.0
    assert habit.score(run(day=9, created=51, size=1000)).value == 0.0


def test_the_median_does_not_drift_toward_one_surge_night(habit):
    """Why median and not mean: one surge must not become the new normal."""
    teach(habit, [run(day=d, created=240) for d in range(1, 7)])
    habit.learn(run(day=7, created=5000))
    still_normal = habit.score(run(day=8, created=245))
    assert still_normal.value == 0.0


# --- what judge and the console ask for ------------------------------------


def test_it_remembers_every_extension_any_job_has_produced(habit):
    habit.learn(run(day=1, created=2, extension=".csv"))
    habit.learn(run(day=2, created=2, extension=".zip", job="archive_old",
                    identity="cmd|jobs/archive_old.bat|z9"))
    assert habit.seen_extensions() == frozenset({".csv", ".zip"})
    assert ".locked" not in habit.seen_extensions()


def test_it_can_hand_the_console_a_card_to_show_beside_the_truth(habit):
    teach(habit, [run(day=d, created=240, modified=1) for d in range(1, 8)])
    cards = habit.cards()
    assert "nightly_export" in cards
    centre, spread = cards["nightly_export"]["files_created"]
    assert centre == 240
    assert spread > 0


def test_open_habit_puts_the_database_beside_the_district(tmp_path):
    habit = open_habit(tmp_path, 3.0, 3, 0.10)
    habit.learn(run(day=1, created=1))
    assert (tmp_path / "data" / "habit.db").exists()


# --- rule 1 ----------------------------------------------------------------


def test_habit_cannot_pause_lock_or_delete_anything():
    """Rule 1, read off the module's own syntax tree.

    The learned score never pauses, locks or deletes anything on its own.
    The durable proof is not that `habit` chooses not to, but that it has no
    way to: it imports nothing that could reach a process or a permission,
    and calls nothing that could. Prose in a docstring is not evidence, so
    this reads the AST rather than the text.
    """
    import ast
    from pathlib import Path

    CANNOT_IMPORT = {"psutil", "subprocess", "shutil", "os", "ctypes", "signal"}
    CANNOT_CALL = {
        "suspend", "resume", "kill", "terminate", "chmod", "chown",
        "rmtree", "unlink", "remove", "rmdir", "system", "popen", "run",
    }

    for file in sorted(Path("nightkeep/habit").rglob("*.py")):
        tree = ast.parse(file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    assert root not in CANNOT_IMPORT, f"{file} imports {alias.name}"
            elif isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".")[0]
                assert root not in CANNOT_IMPORT, f"{file} imports from {node.module}"
            elif isinstance(node, ast.Call):
                called = node.func
                name = (
                    called.attr if isinstance(called, ast.Attribute)
                    else called.id if isinstance(called, ast.Name)
                    else None
                )
                assert name not in CANNOT_CALL, f"{file} calls {name}()"
