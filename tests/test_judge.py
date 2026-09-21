"""The verdict table, the tripwires, and the two rules judge is the keeper of.

The single most important test in this file is
`test_a_wild_habit_score_alone_never_reaches_incident`. Everything else in
Nightkeep can be rebuilt; if that one stops holding, the product is a thing
that pauses a district's PDS server because a job ran late.
"""

import ast
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from nightkeep.habit import Habit
from nightkeep.judge import Judge
from nightkeep.judge import _actions
from nightkeep.types import (
    CREATED,
    DELETED,
    INCIDENT,
    MODIFIED,
    NORMAL,
    ODD,
    RENAMED,
    SUSPICIOUS,
    Event,
    JobRun,
)

AT = datetime(2026, 9, 22, 3, 41, 12)
IDENTITY = "python|jobs/nightly_export.py|abc123"
TRAPS = ("share/exports/epos_day_end_20240101.csv",)
CSV = b"card_no,fps_id,quantity_kg\n110300512847,27030300145,20.000\n" * 40


@pytest.fixture
def root(tmp_path):
    for folder in ("data", "share/exports", "share/backups", "allocations",
                   "logs/_truth"):
        (tmp_path / folder).mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture
def habit(tmp_path):
    return Habit(tmp_path / "habit.db", 3.0, 3, 0.10)


@pytest.fixture
def judge(root, habit):
    made = Judge(
        root=root,
        habit=habit,
        odd_score=0.5,
        rename_burst=10,
        entropy_jump=1.5,
        entropy_floor=7.0,
        recovery_commands=("vssadmin delete shadows", "wbadmin delete catalog"),
        trap_files=TRAPS,
    )
    made.plant_traps()
    yield made
    made.undo()


def job_run(events=(), job="nightly_export", identity=IDENTITY, day=8):
    return JobRun(
        job=job,
        identity=identity,
        started_at=AT,
        finished_at=AT + timedelta(seconds=30),
        events=tuple(events),
        sim_started_at=AT,
        day_no=day,
    )


def teach_quiet_nights(habit, count=7, created=240):
    for day in range(1, count + 1):
        habit.learn(
            JobRun(
                job="nightly_export",
                identity=IDENTITY,
                started_at=AT - timedelta(days=count - day),
                finished_at=AT - timedelta(days=count - day) + timedelta(seconds=30),
                events=tuple(
                    Event(path=f"share/exports/e{day}_{n}.csv", kind=CREATED,
                          at=AT, size=1000, pid=999)
                    for n in range(created)
                ),
                sim_started_at=datetime(2026, 9, day, 1, 30),
                day_no=day,
            )
        )


# --- rule 1: the one that matters ------------------------------------------


def test_a_wild_habit_score_alone_never_reaches_incident(judge, habit, root):
    """Rule 1. A job that behaved like nothing it has ever done, with no
    tripwire anywhere, is ODD. It is never paused."""
    teach_quiet_nights(habit)
    events = [
        Event(path=f"share/exports/wild_{n}.csv", kind=CREATED, at=AT, size=9_000_000)
        for n in range(9000)
    ]
    verdict = judge.verdict(job_run(events))

    assert verdict.level == ODD
    assert not any(signal.is_tripwire for signal in verdict.signals)
    assert verdict.actions == ("noted it for review. Nothing was blocked",)


def test_nothing_in_judge_can_reach_incident_without_a_tripwire(judge, habit):
    """The table is the only route to INCIDENT, and Verdict itself refuses
    to be built without a tripwire. Belt and braces, on purpose."""
    teach_quiet_nights(habit)
    for score in (0.0, 0.5, 0.9, 1.0):
        assert judge._level(codes=set(), habit_score=_score(score)) in (NORMAL, ODD)


def _score(value):
    from nightkeep.types import HabitScore

    return HabitScore(value=value)


# --- rule 2: tripwires are never learned -----------------------------------


def test_no_signal_reads_a_habit_card():
    """Rule 2, read off the syntax tree of the signals module.

    `_signals.py` may not import habit, and may not call anything named
    score. Every number it judges on arrives as an argument from config.
    """
    tree = ast.parse(Path("nightkeep/judge/_signals.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert "habit" not in node.module, f"_signals imports {node.module}"
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "habit" not in alias.name
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr != "score", "_signals called a habit score"


def test_a_tripwire_fires_on_the_very_first_night_with_no_card_at_all(judge, root):
    """Live from minute one. No learning has happened; the trap still fires."""
    trap = root / TRAPS[0]
    trap.write_bytes(b"tampered")
    verdict = judge.verdict(
        job_run([Event(path=TRAPS[0], kind=MODIFIED, at=AT, size=8)])
    )
    assert verdict.level == INCIDENT
    assert verdict.signals[0].code == "S2"


# --- the verdict table -----------------------------------------------------


def test_a_quiet_night_is_normal(judge, habit):
    teach_quiet_nights(habit)
    events = [
        Event(path=f"share/exports/e_{n}.csv", kind=CREATED, at=AT, size=1000)
        for n in range(240)
    ]
    assert judge.verdict(job_run(events)).level == NORMAL


def test_a_trap_file_touched_is_an_incident_on_its_own(judge, root):
    (root / TRAPS[0]).write_bytes(b"x")
    verdict = judge.verdict(
        job_run([Event(path=TRAPS[0], kind=MODIFIED, at=AT, size=1)])
    )
    assert verdict.level == INCIDENT


def test_a_trap_file_renamed_is_an_incident(judge, root):
    verdict = judge.verdict(
        job_run([
            Event(path="share/exports/epos_day_end_20240101.csv.locked",
                  kind=RENAMED, at=AT, old_path=TRAPS[0], size=1)
        ])
    )
    assert verdict.level == INCIDENT
    assert "decoy" in verdict.reasons[0]


def test_a_trap_file_deleted_is_an_incident(judge):
    verdict = judge.verdict(
        job_run([Event(path=TRAPS[0], kind=DELETED, at=AT)])
    )
    assert verdict.level == INCIDENT


def test_a_mass_rename_alone_is_suspicious_not_an_incident(judge, habit):
    """One fixed signal without an unusual habit. Alert, do not pause.

    fix_dat renames thirty files every night it runs, so a night where it
    renames thirty files is not unusual for it. The only thing out of place
    is the extension, and S4 alone does not earn a pause.
    """
    identity = "cscript|jobs/fix_dat.vbs|v1"
    for day in range(1, 8):
        habit.learn(
            JobRun(job="fix_dat", identity=identity,
                   started_at=AT, finished_at=AT,
                   events=tuple(
                       Event(path=f"allocations/q{n}.dat", kind=RENAMED, at=AT,
                             old_path=f"allocations/q{n}.tmp", size=100)
                       for n in range(30)
                   ),
                   sim_started_at=AT, day_no=day)
        )
    events = [
        Event(path=f"allocations/q{n}.locked", kind=RENAMED, at=AT,
              old_path=f"allocations/q{n}.tmp", size=100)
        for n in range(30)
    ]
    verdict = judge.verdict(job_run(events, job="fix_dat", identity=identity))
    assert verdict.level == SUSPICIOUS
    assert {s.code for s in verdict.signals} == {"S4"}


def test_a_mass_rename_on_an_unusual_night_is_an_incident(judge, habit, root):
    teach_quiet_nights(habit)
    events = []
    for n in range(4000):
        events.append(
            Event(path=f"data/card_{n}.csv.locked", kind=RENAMED, at=AT,
                  old_path=f"data/card_{n}.csv", size=900, pid=4242)
        )
    verdict = judge.verdict(job_run(events))
    assert verdict.level == INCIDENT
    assert "S4" in {s.code for s in verdict.signals}


def test_a_few_renames_are_not_a_burst(judge, habit):
    """Three renames is a job having a strange night, not a rename burst.

    The night is still ODD, and it should be: the export job renamed files
    it has never renamed and created nothing. What must not happen is S4
    firing, because three is not ten, and so nothing is paused.
    """
    teach_quiet_nights(habit)
    events = [
        Event(path=f"share/exports/e{n}.locked", kind=RENAMED, at=AT,
              old_path=f"share/exports/e{n}.csv", size=10)
        for n in range(3)
    ]
    verdict = judge.verdict(job_run(events))
    assert "S4" not in {s.code for s in verdict.signals}
    assert verdict.level != INCIDENT
    assert verdict.actions == ("noted it for review. Nothing was blocked",)


def test_a_rename_to_a_known_extension_never_fires_s4(judge, habit):
    """fix_dat renames .tmp to .dat every few nights. It must stay quiet."""
    teach_quiet_nights(habit)
    for day in range(1, 5):
        habit.learn(
            JobRun(job="fix_dat", identity="cscript|jobs/fix_dat.vbs|v1",
                   started_at=AT, finished_at=AT,
                   events=tuple(
                       Event(path=f"allocations/q{n}.dat", kind=RENAMED, at=AT,
                             old_path=f"allocations/q{n}.tmp", size=100)
                       for n in range(30)
                   ),
                   sim_started_at=AT, day_no=day)
        )
    events = [
        Event(path=f"allocations/q{n}.dat", kind=RENAMED, at=AT,
              old_path=f"allocations/q{n}.tmp", size=100)
        for n in range(30)
    ]
    verdict = judge.verdict(
        job_run(events, job="fix_dat", identity="cscript|jobs/fix_dat.vbs|v1")
    )
    assert "S4" not in {s.code for s in verdict.signals}


def test_recovery_killing_text_alone_is_suspicious(judge, habit, root):
    teach_quiet_nights(habit)
    note = root / "share" / "exports" / "readme.txt"
    note.write_text("run vssadmin delete shadows /all /quiet to finish")
    verdict = judge.verdict(
        job_run([Event(path="share/exports/readme.txt", kind=CREATED, at=AT,
                       size=note.stat().st_size)])
    )
    assert verdict.level == SUSPICIOUS
    assert {s.code for s in verdict.signals} == {"S5"}


def test_recovery_killing_text_with_another_ransom_signal_is_an_incident(
    judge, habit, root
):
    teach_quiet_nights(habit)
    note = root / "share" / "exports" / "readme.txt"
    note.write_text("wbadmin delete catalog -quiet")
    events = [
        Event(path="share/exports/readme.txt", kind=CREATED, at=AT,
              size=note.stat().st_size)
    ]
    events += [
        Event(path=f"data/c{n}.csv.locked", kind=RENAMED, at=AT,
              old_path=f"data/c{n}.csv", size=10)
        for n in range(12)
    ]
    verdict = judge.verdict(job_run(events))
    assert verdict.level == INCIDENT
    assert {"S4", "S5"} <= {s.code for s in verdict.signals}


@pytest.mark.slow
def test_scrambling_existing_files_on_an_unusual_night_is_an_incident(
    judge, habit, root
):
    teach_quiet_nights(habit)
    events = []
    for n in range(300):
        path = root / "share" / "exports" / f"real_{n}.csv"
        path.write_bytes(os.urandom(6000))
        events.append(
            Event(path=f"share/exports/real_{n}.csv", kind=MODIFIED, at=AT,
                  size=6000, pid=4242)
        )
    # Nightkeep saw these files readable before tonight.
    for n in range(300):
        judge._baseline.remember(f"share/exports/real_{n}.csv", 4.2, AT)

    verdict = judge.verdict(job_run(events))
    assert verdict.level == INCIDENT
    assert "S3" in {s.code for s in verdict.signals}


def test_the_archive_job_writing_a_fresh_zip_stays_normal(judge, habit, root):
    """The trap this whole design exists to avoid: a ZIP is noise on purpose."""
    teach_quiet_nights(habit)
    events = []
    for n in range(20):
        path = root / "share" / "exports" / f"archive_{n}.zip"
        path.write_bytes(b"PK\x03\x04" + os.urandom(5000))
        events.append(
            Event(path=f"share/exports/archive_{n}.zip", kind=CREATED, at=AT,
                  size=5004)
        )
    verdict = judge.verdict(job_run(events))
    assert "S3" not in {s.code for s in verdict.signals}
    assert verdict.level in (NORMAL, ODD)


# --- reversible actions -----------------------------------------------------


def test_an_incident_locks_the_records_folder_and_can_unlock_it(judge, root):
    records = root / "data" / "district.db"
    records.write_bytes(b"SQLite format 3\x00" + b"\x00" * 100)

    (root / TRAPS[0]).write_bytes(b"x")
    verdict = judge.verdict(
        job_run([Event(path=TRAPS[0], kind=MODIFIED, at=AT, size=1)])
    )

    assert verdict.level == INCIDENT
    assert _actions.is_read_only(records)
    assert any("locked the records folder" in action for action in verdict.actions)

    undone = judge.undo()
    assert not _actions.is_read_only(records)
    assert any("unlocked" in line for line in undone)


def test_undo_is_safe_to_call_twice(judge, root):
    (root / "data" / "district.db").write_bytes(b"x")
    (root / TRAPS[0]).write_bytes(b"x")
    judge.verdict(job_run([Event(path=TRAPS[0], kind=MODIFIED, at=AT, size=1)]))
    judge.undo()
    assert judge.undo() == []


def test_judge_suspends_but_never_kills():
    """Reversible by construction. No kill, no terminate, anywhere."""
    for file in sorted(Path("nightkeep/judge").rglob("*.py")):
        tree = ast.parse(file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in ("kill", "terminate"), (
                    f"{file} calls {node.func.attr}()"
                )


# --- the baseline only learns from quiet nights ----------------------------


def test_an_incident_never_updates_what_normal_looks_like(judge, habit, root):
    teach_quiet_nights(habit)
    path = root / "share" / "exports" / "e.csv"
    path.write_bytes(os.urandom(6000))
    (root / TRAPS[0]).write_bytes(b"x")

    before = judge._baseline.count()
    judge.verdict(
        job_run([
            Event(path=TRAPS[0], kind=MODIFIED, at=AT, size=1),
            Event(path="share/exports/e.csv", kind=MODIFIED, at=AT, size=6000),
        ])
    )
    assert judge._baseline.count() == before


def test_a_quiet_night_does_update_what_normal_looks_like(judge, habit, root):
    teach_quiet_nights(habit)
    path = root / "share" / "exports" / "e.csv"
    path.write_bytes(CSV)
    judge.verdict(
        job_run([Event(path="share/exports/e.csv", kind=MODIFIED, at=AT,
                       size=len(CSV))])
    )
    assert judge._baseline.knows("share/exports/e.csv")


def test_a_window_verdict_never_updates_what_normal_looks_like(judge, habit, root):
    """Live attack windows are judged with an explicit event slice. Even when
    the slice looks NORMAL, it must not teach the baseline: a slice is never
    "a quiet night". Without this, early attack windows would fold scrambled
    entropy into "normal" and blunt S3 for the rest of the attack."""
    teach_quiet_nights(habit)
    path = root / "share" / "exports" / "e.csv"
    path.write_bytes(CSV)
    judge.verdict(
        job_run([Event(path="share/exports/e.csv", kind=MODIFIED, at=AT,
                       size=len(CSV))])
    )
    clean_entropy = judge._baseline.entropy_of("share/exports/e.csv")
    assert clean_entropy is not None

    # New content, slightly different entropy but far from the S3 tripwire:
    # exactly what an early live attack window looks like.
    path.write_bytes(CSV + b"extra,row,1.5\n")
    window = [Event(path="share/exports/e.csv", kind=MODIFIED, at=AT,
                    size=path.stat().st_size)]
    verdict = judge.verdict(job_run(), events=window)
    assert verdict.level in (NORMAL, ODD)
    assert judge._baseline.entropy_of("share/exports/e.csv") == clean_entropy


# --- the truth logs --------------------------------------------------------


def test_judge_never_opens_the_truth_log(judge, habit, root):
    teach_quiet_nights(habit)
    truth = root / "logs" / "_truth" / "nightly_export.jsonl"
    truth.write_text('{"job": "nightly_export", "created": ["secret"]}\n')

    verdict = judge.verdict(
        job_run([
            Event(path="logs/_truth/nightly_export.jsonl", kind=MODIFIED, at=AT,
                  size=truth.stat().st_size)
        ])
    )
    # Nothing was read, so nothing can have been judged from it.
    assert not judge._baseline.knows("logs/_truth/nightly_export.jsonl")
    assert verdict.level in (NORMAL, ODD)
