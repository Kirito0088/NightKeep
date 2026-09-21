"""The whole demo, once, end to end, writing the numbers down as it goes.

A deliverable, not a module in the architecture table, the same standing
prove_erratic.py has. The entrypoint runs it:

    python -m nightkeep --demo --variant fast

It lives one seeded run of the story the pitch tells, using the real
modules and nothing faked:

1. It builds the Thane district and starts the Watcher over it.
2. It lives the learning days, and folds each night into the Habit Cards.
3. It lives the guard days, and asks the Judge for a verdict each night.
   Zero INCIDENT verdicts here is P1, measured rather than claimed.
4. It runs the safe threat simulator, and polls the Judge as the scramble
   unfolds, so it can report how few files were touched before the line was
   crossed and how many real seconds that took. That is P2.
5. The Vault, on its own clock, has been pulling clean copies the whole
   time. The scrambled pull comes back SUSPECT and the last clean point
   stays pinned. That is P3.
6. It restores from that clean point and records the five checks, 5,000 of
   5,000 cards. That is P4.

Everything it learns is written to `<out_dir>/reports/run.json`, which the
console reads. No number on a console screen is invented once this has run.

Two things keep the witnesses honest here, and they are load-bearing:

- The district lives in `<out_dir>/pds` and the Vault in `<out_dir>/vault`,
  so the Watcher, which is recursive, never sees the Vault's own writes.
- This runner never reads a ground-truth log. It learns what changed only
  from the Watcher, exactly as Nightkeep does in an office. Grouping those
  events back into per-job runs is the "active writer in window" fallback
  MVP section 14 allows: each night task owns a folder, and the file
  changes in that folder over the night are that task's run.
"""

import json
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from nightkeep import mock_pds
from nightkeep.config import Config
from nightkeep.habit import Habit, open_habit
from nightkeep.judge import Judge
from nightkeep.simulator import FAST, simulate
from nightkeep.types import (
    CREATED,
    DELETED,
    INCIDENT,
    MODIFIED,
    ODD,
    RENAMED,
    Event,
    JobRun,
)
from nightkeep.vault import Vault
from nightkeep.watcher import Watcher

REPORT_NAME = "run.json"

# Each night task owns a folder. The file changes there over the night are
# that task's run. Two tasks share share/allocations, so they are split by
# what they do to a file, not only where: the allocation job writes .tmp
# files, and the format-maintenance job renames them to .dat and rewrites
# allocation files in place.
_EXPORTS = "share/exports"
_ALLOCATIONS = "share/allocations"
_BACKUPS = "share/backups"
_ARCHIVE = "archive"

# Nightkeep's own databases live under data/ too. They are not a night task,
# and the runner must not mistake its own bookkeeping for the office's.
_OWN_DATABASES = ("data/judge.db", "data/habit.db")

# The counter-clerk name for each job. The console renders these; it does
# not invent them. Kept here because the runner is what turns a night's real
# numbers into the one sentence a clerk reads.
FRIENDLY_NAMES = {
    "nightly_export": "Day-end upload",
    "allocation_gen": "Allotment file creation",
    "db_backup": "Safe copy of the database",
    "archive_old": "Old file clean-up",
    "fix_dat": "Data format maintenance",
    "operator_activity": "Counter clerk entries",
}

# The identity a job keeps across the run. Stable, so learning builds one
# card per job rather than churning a new version every night.
def _identity(job: str) -> str:
    return f"{job}|v1"


@dataclass
class DemoResult:
    """Everything the run proved, ready to be written to run.json."""

    seed: int
    variant: str
    district: dict
    learning_days: int
    guard_days: int
    proofs: dict = field(default_factory=dict)
    habit_cards: dict = field(default_factory=dict)
    guard_verdicts: list = field(default_factory=list)
    night_tasks: list = field(default_factory=list)
    attack: dict = field(default_factory=dict)
    snapshots: list = field(default_factory=list)
    restore: dict = field(default_factory=dict)
    timeline: list = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "seed": self.seed,
            "variant": self.variant,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "district": self.district,
            "learning_days": self.learning_days,
            "guard_days": self.guard_days,
            "proofs": self.proofs,
            "habit_cards": self.habit_cards,
            "guard_verdicts": self.guard_verdicts,
            "night_tasks": self.night_tasks,
            "attack": self.attack,
            "snapshots": self.snapshots,
            "restore": self.restore,
            "timeline": self.timeline,
        }


def run_demo(
    *,
    config: Config,
    out_dir: Path,
    variant: str = FAST,
    on_step: Callable[[str], None] | None = None,
) -> DemoResult:
    """Live the whole story once and return what it proved. Writes run.json."""
    say = on_step or (lambda _message: None)
    out_dir = Path(out_dir)
    pds = out_dir / "pds"
    vault_root = out_dir / "vault"
    _clear(out_dir)

    say("Building the Thane district")
    mock_pds.build_district(config.seed, config.district, pds)

    habit = open_habit(
        pds, config.habit.mad_multiplier,
        config.habit.min_runs_before_scoring, config.habit.minimum_spread_fraction,
    )
    judge = Judge(
        root=pds, habit=habit, odd_score=config.judge.odd_score,
        rename_burst=config.judge.rename_burst, entropy_jump=config.judge.entropy_jump,
        entropy_floor=config.judge.entropy_floor,
        recovery_commands=config.judge.recovery_commands,
        canary_files=config.judge.canary_files,
    )
    judge.plant_canaries()
    vault = Vault(
        share=pds / "share", root=vault_root,
        suspect_randomness=config.vault.suspect_entropy,
        restore_folder_name=config.vault.restore_folder_name,
        expected_records=config.district.ration_cards,
    )

    result = DemoResult(
        seed=config.seed, variant=variant,
        district={"ration_cards": config.district.ration_cards,
                  "fps_count": config.district.fps_count},
        learning_days=config.clock.learning_days,
        guard_days=config.clock.guard_days,
    )

    with Watcher(pds, config.watcher.poll_seconds, config.watcher.settle_seconds) as watcher:
        last_runs = _learn_and_guard(
            watcher, habit, judge, vault, config, pds, result, say
        )
        _attack(watcher, judge, vault, config, pds, variant, result, say)

    _fill_night_tasks(result, habit, last_runs, config.jobs)
    _finish(result, vault)

    reports = pds / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / REPORT_NAME).write_text(
        json.dumps(result.to_json(), indent=2) + "\n", encoding="utf-8"
    )
    say(f"Wrote {reports / REPORT_NAME}")
    return result


# --- the learning and guard nights -----------------------------------------


def _learn_and_guard(
    watcher, habit, judge, vault, config, pds, result, say
) -> dict:
    """Live every night, learning then guarding, pulling a clean copy each day.

    Returns the last run seen for each job, so the console can say what each
    task did "last night".
    """
    total = config.clock.learning_days + config.clock.guard_days
    sim_day = datetime(2026, 9, 1, tzinfo=timezone.utc)
    false_incidents = 0
    odd_cards = 0
    last_runs: dict[str, JobRun] = {}

    surprise_day = total  # the last guard night, so it reads as "last night"
    for day_no in range(1, total + 1):
        learning = day_no <= config.clock.learning_days
        phase = "learning" if learning else "guard"
        say(f"Day {day_no} ({phase})")

        start = datetime.now(timezone.utc)
        mock_pds.run_day(
            day_no, seed=config.seed, clock=config.clock, jobs=config.jobs,
            harvest_surge=config.harvest_surge, district_dir=pds,
        )
        time.sleep(config.watcher.settle_seconds + 0.3)
        end = datetime.now(timezone.utc)

        runs = _runs_from_events(
            watcher.events_between(start, end), sim_day, day_no
        )
        last_runs.update(runs)

        for job, run in runs.items():
            if learning:
                habit.learn(run)
            else:
                verdict = judge.verdict(run, list(run.events))
                if verdict.level == INCIDENT:
                    false_incidents += 1
                    judge.undo()
                if verdict.level == ODD:
                    odd_cards += 1
                result.guard_verdicts.append({
                    "day": day_no, "job": job, "level": verdict.level,
                    "reasons": list(verdict.reasons), "actions": list(verdict.actions),
                })

        # On the last guard night, a legitimate surprise: the day-end upload
        # runs a big catch-up batch after an outage. Erratic, but harmless,
        # and exactly the twist Nightkeep must not alarm on. It reads as ODD.
        if day_no == surprise_day:
            odd = _legit_surprise(watcher, judge, config, pds, sim_day, day_no, say)
            if odd is not None:
                last_runs["nightly_export"] = odd["run"]
                if odd["level"] == ODD:
                    odd_cards += 1
                result.guard_verdicts.append(odd["record"])

        snapshot = vault.pull(at=sim_day)
        say(f"  safe copy pulled: {snapshot.snapshot_id} ({snapshot.health})")
        sim_day += timedelta(days=1)

    result.proofs["p1_false_incidents"] = false_incidents
    result.proofs["p1_odd_cards"] = odd_cards
    result.habit_cards = _habit_cards(habit)
    result.proofs["p1_odd_beat"] = odd_cards >= 1
    # The counter entries made on the last night: the ones a clerk should
    # re-check against the register after a restore, because they are the
    # newest and the most likely to sit after the last safe copy.
    last_operator = last_runs.get("operator_activity")
    result.proofs["entries_to_recheck"] = len(last_operator.events) if last_operator else 0
    return last_runs


# --- the legit surprise: weird but fine -------------------------------------

# How many CSVs the catch-up export writes at once. Far above the day-end
# upload's usual one file a night, so it reads as unusual, while every file is
# a valid export that trips no threat signal.
CATCHUP_EXPORT_FILES = 8

_EXPORT_HEADER = (
    "transaction_id,card_no,fps_id,occurred_at,allotment_month,"
    "commodity,quantity_kg,auth_mode,status\n"
)


def _legit_surprise(watcher, judge, config, pds, sim_day, day_no, say):
    """One catch-up day-end export: several valid CSVs at once, harmlessly.

    This is the "weird but fine" beat. After an outage a district uploads
    several days of backlog in one go, so the day-end upload writes far more
    files than usual. Nothing is scrambled, renamed to an unseen type, or
    written over: they are new, valid CSVs. So no threat signal fires, but
    the file count is well outside the job's learned habit, and the verdict
    is ODD. That is the whole point: erratic is not the same as dangerous.
    """
    say("Legit surprise: a catch-up day-end upload (weird but fine)")
    exports = pds / "share" / "exports"
    exports.mkdir(parents=True, exist_ok=True)

    start = datetime.now(timezone.utc)
    for n in range(CATCHUP_EXPORT_FILES):
        # A real day-end export is a day of transactions, kilobytes not bytes.
        # Sizing these realistically matters: a byte-sized file scrambled
        # stays below the Vault's noise floor, so a true-to-life export is
        # also what lets the Vault recognise it as damaged if it is hit.
        rows = "".join(
            f"{n}{r:04d},110300512{r % 1000:03d},27030300145,"
            f"2026-09-{1 + r % 28:02d} 11:{r % 60:02d},2026-09,Rice,"
            f"{5 + r % 20}.000,Biometric,Collected\n"
            for r in range(60)
        )
        (exports / f"epos_catchup_{n:02d}.csv").write_text(
            _EXPORT_HEADER + rows, encoding="utf-8"
        )
    time.sleep(config.watcher.settle_seconds + 0.3)
    end = datetime.now(timezone.utc)

    events = [e for e in watcher.events_between(start, end)
              if _classify(e) == "nightly_export"]
    if not events:
        return None
    run = JobRun(
        job="nightly_export", identity=_identity("nightly_export"),
        started_at=min(e.at for e in events), finished_at=max(e.at for e in events),
        events=tuple(events), sim_started_at=sim_day, day_no=day_no,
    )
    verdict = judge.verdict(run, list(run.events))
    say(f"  verdict: {verdict.level} (nothing blocked)")
    return {
        "run": run,
        "level": verdict.level,
        "record": {
            "day": day_no, "job": "nightly_export", "level": verdict.level,
            "reasons": list(verdict.reasons), "actions": list(verdict.actions),
            "surprise": "catch-up day-end upload",
        },
    }


# --- the attack -------------------------------------------------------------


def _attack(watcher, judge, vault, config, pds, variant, result, say):
    """Run the simulator, catch it live, stop it, then pull and pin around it.

    The Judge is polled on the Watcher's own cadence, not once per file, so
    "how many files before it was caught" is what the deployed product would
    really see rather than an artefact of a tight loop. The moment the poll
    crosses into INCIDENT, the scramble is stopped where it stands: in an
    office the Judge suspends the process; here the in-process simulator
    honours the same stop, so the demo shows the damage halting rather than
    running to the end.
    """
    say(f"Threat test: {variant}")
    sim = config.simulator
    identity = _identity("nightly_export")  # it strikes the export folder
    touched = 0
    caught_at: dict[str, float | int | None] = {"files": None, "seconds": None}
    began = time.monotonic()
    last_poll = 0.0
    attack_start = datetime.now(timezone.utc)

    def watch_each(_path: Path) -> None:
        nonlocal touched, last_poll
        touched += 1
        if caught_at["files"] is not None:
            return
        # Poll at the Watcher's cadence, the same rhythm the real Judge runs
        # on, so the file count at detection is honest.
        now = time.monotonic()
        if now - last_poll < config.watcher.poll_seconds:
            return
        last_poll = now
        events = watcher.events_since(attack_start)
        incident, _codes = judge.would_incident(_threat_run(events, identity), events)
        if incident:
            caught_at["files"] = touched
            caught_at["seconds"] = round(now - began, 2)

    def caught() -> bool:
        return caught_at["files"] is not None

    report = simulate(
        pds, variant=variant, config=sim,
        recovery_commands=config.judge.recovery_commands,
        on_file=watch_each, stop_when=caught,
    )

    time.sleep(config.watcher.settle_seconds + 0.3)
    events = watcher.events_between(attack_start, datetime.now(timezone.utc))
    run = _threat_run(events, identity)
    verdict = judge.verdict(run, events)
    actions = list(verdict.actions)
    judge.undo()  # a demo can be run again; leave nothing paused or locked

    # A share small enough to finish before the first poll is still caught by
    # the committing verdict; record the whole burst as the loss window then.
    if caught_at["files"] is None and verdict.level == INCIDENT:
        caught_at["files"] = report.files_scrambled
        caught_at["seconds"] = round(time.monotonic() - began, 2)

    attack_snapshot = vault.pull(at=datetime.now(timezone.utc))

    result.attack = {
        "variant": variant,
        "files_scrambled": report.files_scrambled,
        "files_renamed": report.files_renamed,
        "files_before_incident": caught_at["files"],
        "detection_seconds": caught_at["seconds"],
        "verdict_level": verdict.level,
        "reasons": list(verdict.reasons),
        "actions": actions,
        "signals": [
            {"code": s.code, "title": s.title, "reason": s.reason}
            for s in verdict.signals
        ],
        "command_text_written_to": report.command_text_written_to,
    }
    result.proofs["p2_files_before_incident"] = caught_at["files"]
    result.proofs["p2_detection_seconds"] = caught_at["seconds"]
    result.proofs["p2_verdict"] = verdict.level
    result.proofs["p3_attack_snapshot_health"] = attack_snapshot.health
    say(f"  verdict: {verdict.level}; the scrambled pull is {attack_snapshot.health}")


# --- turning events into runs ----------------------------------------------


def _classify(event: Event) -> str | None:
    """Which night task owns this change, if any. The fallback in MVP 14."""
    path = event.path
    if path in _OWN_DATABASES or path.startswith(tuple(f"{d}-" for d in _OWN_DATABASES)):
        return None
    if path.startswith(_EXPORTS + "/"):
        # The clean-up job is the only thing that deletes an export.
        return "archive_old" if event.kind == DELETED else "nightly_export"
    if path.startswith(_BACKUPS + "/"):
        return "db_backup"
    if path.startswith(_ARCHIVE + "/"):
        return "archive_old"
    if path.startswith(_ALLOCATIONS + "/"):
        if event.kind == RENAMED or path.endswith(".dat"):
            return "fix_dat"
        if path.endswith(".tmp") and event.kind == CREATED:
            return "allocation_gen"
        return "fix_dat"  # a rewritten allocation file
    if path.startswith("data/district.db"):
        return "operator_activity"
    return None


def _runs_from_events(
    events: list[Event], sim_day: datetime, day_no: int
) -> dict[str, JobRun]:
    """Group one night's file changes into one run per task that was active."""
    by_job: dict[str, list[Event]] = {}
    for event in events:
        job = _classify(event)
        if job is not None:
            by_job.setdefault(job, []).append(event)

    runs: dict[str, JobRun] = {}
    for job, job_events in by_job.items():
        moments = [event.at for event in job_events]
        runs[job] = JobRun(
            job=job, identity=_identity(job),
            started_at=min(moments), finished_at=max(moments),
            events=tuple(job_events), sim_started_at=sim_day, day_no=day_no,
        )
    return runs


def _threat_run(events: list[Event], identity: str) -> JobRun:
    """Wrap the scramble so far as a run of the job it is impersonating."""
    now = datetime.now(timezone.utc)
    moments = [event.at for event in events] or [now]
    return JobRun(
        job="nightly_export", identity=identity,
        started_at=min(moments), finished_at=max(moments),
        events=tuple(events), sim_started_at=now, day_no=None,
    )


# --- the console-facing summaries ------------------------------------------


def _habit_cards(habit: Habit) -> dict:
    """Each job's learned card. habit returns each feature as (median, spread)."""
    cards = {}
    for job, features in habit.cards().items():
        cards[job] = {
            "runs": habit.run_count(job),
            "features": {
                name: {"median": round(median, 2), "spread": round(spread, 2)}
                for name, (median, spread) in features.items()
            },
        }
    return cards


def _fill_night_tasks(result: DemoResult, habit: Habit, last_runs: dict, jobs) -> None:
    """One console-ready line per task: its name, its habit, and last night."""
    cards = habit.cards()
    verdict_by_job = {v["job"]: v for v in result.guard_verdicts}

    for job, friendly in FRIENDLY_NAMES.items():
        card = cards.get(job, {})
        last = last_runs.get(job)
        result.night_tasks.append({
            "job": job,
            "task_name": friendly,
            "usually": _usually(job, card, getattr(jobs, job, None)),
            "last_night": _last_night(last),
            "status": _status(verdict_by_job.get(job)),
        })


def _usually(job: str, card: dict, job_config) -> str:
    """A plain sentence for a task's habit: its schedule, and its learned size.

    The schedule window comes from config, because it is the actual time the
    task is set to run and the compressed demo clock cannot learn a real
    time of day in two seconds a night. The file volume is the learned part:
    each feature is (median, spread), so the everyday range is the median
    give or take the spread, the same arithmetic the habit score uses.
    """
    parts = []
    window = getattr(job_config, "start_window", None)
    if window is not None:
        parts.append(
            f"{window.earliest.strftime('%H:%M')} to "
            f"{window.latest.strftime('%H:%M')}"
        )
    created = card.get("files_created") if card else None
    if created and created[0] >= 1:
        median, spread = created
        low = max(0, int(median - spread))
        high = int(median + spread)
        span = f"{low}" if low == high else f"{low} to {high}"
        parts.append(f"writes about {span} files")
    elif not card:
        parts.append("runs only some nights")
    return ", ".join(parts) if parts else "runs some nights"


def _last_night(run: JobRun | None) -> str:
    """What the task did on the last guard night, in file changes.

    Deliberately no clock time: the demo compresses each night into a couple
    of real seconds, so the only honest time to show would be tonight's real
    one, which means nothing to a clerk. The change count is real.
    """
    if run is None:
        return "did not run"
    changes = len(run.events)
    return f"{changes} file change{'' if changes == 1 else 's'}"


def _status(verdict: dict | None) -> str:
    if verdict is None:
        return "Normal"
    return {"NORMAL": "Normal", "ODD": "Unusual, not blocked",
            "SUSPICIOUS": "Needs review", "INCIDENT": "Stopped"}.get(
        verdict["level"], "Normal")


def _finish(result: DemoResult, vault: Vault) -> None:
    """Read the Vault's own record of what it holds, and restore from it."""
    snapshots = vault.snapshots()
    clean_point = next((s for s in snapshots if s.is_clean_point), None)
    result.snapshots = [
        {"id": s.snapshot_id, "taken_at": s.taken_at.isoformat(timespec="seconds"),
         "health": s.health, "is_clean_point": s.is_clean_point,
         "file_count": s.file_count, "reasons": list(s.reasons)}
        for s in snapshots
    ]
    result.proofs["p3_clean_point"] = clean_point.snapshot_id if clean_point else None

    restore = vault.restore()
    result.restore = {
        "ok": restore.ok,
        "snapshot_id": restore.snapshot_id,
        "records_verified": restore.records_verified,
        "records_expected": restore.records_expected,
        "checks": [{"statement": c.statement, "passed": c.passed}
                   for c in restore.checks],
        "reasons": list(restore.reasons),
    }
    result.proofs["p4_records_verified"] = restore.records_verified
    result.proofs["p4_records_expected"] = restore.records_expected
    result.proofs["p4_ok"] = restore.ok

    result.timeline = _timeline(result)


def _timeline(result: DemoResult) -> list:
    """The story in the order it happened, for the alert screen."""
    attack = result.attack
    line = []
    if attack.get("detection_seconds") is not None:
        line.append({
            "title": "Threat test caught",
            "detail": (f"Stopped after {attack['files_before_incident']} files, "
                       f"in {attack['detection_seconds']} seconds."),
        })
    line.append({
        "title": "Safe copies held",
        "detail": (f"The scrambled copy was marked "
                   f"{result.proofs.get('p3_attack_snapshot_health')}, and the "
                   f"clean copy {result.proofs.get('p3_clean_point')} stayed pinned."),
    })
    line.append({
        "title": "Records restored",
        "detail": (f"{result.proofs.get('p4_records_verified')} of "
                   f"{result.proofs.get('p4_records_expected')} ration cards "
                   f"verified from the clean copy."),
    })
    return line


def _clear(out_dir: Path) -> None:
    """Remove a previous demo run, and nothing that is not one."""
    if not out_dir.exists():
        return
    for child in out_dir.iterdir():
        if child.name in ("pds", "vault") or child.name.startswith("pds"):
            shutil.rmtree(child, ignore_errors=True)


__all__ = ["run_demo", "DemoResult", "REPORT_NAME", "FRIENDLY_NAMES"]
