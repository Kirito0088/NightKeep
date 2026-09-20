"""The first end-to-end MVP proof, as one orchestrated run.

Glue only. Every decision lives in the modules; this file only calls them
in the order the demo needs and writes down what happened:

1. Build the district.
2. Plant the Judge's trap files, then start the watcher, open Habit, set
   up the Judge and the Vault.
3. Run the learning days, folding every observed job run into Habit. The
   first Vault pull happens after day 1's jobs, so the pinned clean
   baseline is populated and holds a database backup.
4. Run the guard days, scoring every run and asking the Judge for a
   verdict. Expect noise at most, never an INCIDENT.
5. Launch the safe ransomware simulator as its own process.
6. Ask the Judge about the attack run. Expect INCIDENT, with the
   suspend/read-only actions the Judge takes itself.
7. Pull the Vault again. Expect SUSPECT, with the clean pin unmoved.
8. Restore the pinned clean snapshot with F7's Vault.restore and report
   its checks, including the 5,000/5,000 card count.

`run_day` is a black box and the truth logs are off-limits, so per-job
windows are observed by wrapping `_day.launch` while a day runs: the
wrapper records each job's wall-clock window and simulated start, then
hands the real launch through untouched. The wrapper lives and dies inside
one run and is always restored afterwards.

Usage (from the entrypoint, which is the only caller of load_config):
    python -m nightkeep --demo-run [--seed ...] [--variant fast]
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from nightkeep import mock_pds
from nightkeep.config import Config
from nightkeep.habit import open_habit
from nightkeep.judge import Judge
from nightkeep.mock_pds import _day
from nightkeep.types import INCIDENT, CLEAN, SUSPECT, JobRun
from nightkeep.vault import Vault
from nightkeep.watcher import Watcher

REPORT_NAME = "demo_run.json"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --- observing job runs without touching module logic ----------------------

@dataclass
class _ObservedRun:
    """One job launch, as the wrapper saw it: names and clocks only."""

    job: str
    day_no: int
    sim_started_at: datetime
    wall_started_at: datetime
    wall_finished_at: datetime

    def to_job_run(self, watcher: Watcher) -> JobRun:
        events = tuple(
            watcher.events_between(self.wall_started_at, self.wall_finished_at)
        )
        return JobRun(
            job=self.job,
            identity=_job_identity(self.job),
            started_at=self.wall_started_at,
            finished_at=self.wall_finished_at,
            events=events,
            sim_started_at=self.sim_started_at,
            day_no=self.day_no,
        )


def _job_identity(job: str) -> str:
    """Executable + script path + SHA-256, per SOLUTION_DESIGN.md.

    Read from the same mapping the scheduler uses, so the identity can
    never drift from what actually ran.
    """
    path = _day._job_path(job)
    exe = Path(_day._INTERPRETERS[path.suffix](path)[0]).name
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"{exe}|jobs/{path.name}|{digest}"


class _LaunchObserver:
    """Records each job's window by wrapping `_day.launch` for one run.

    The real launch is always called; this only watches the clock around
    it. `stop()` restores the original, and is safe to call twice.
    """

    def __init__(self) -> None:
        self.runs: list[_ObservedRun] = []
        self._original = _day.launch
        self._active = False

    def start(self) -> "_LaunchObserver":
        if not self._active:
            observer = self

            def wrapped(job: str, district_dir: Path, day_no: int,
                        sim_start: datetime, sim_end: datetime,
                        *arguments: str) -> None:
                wall_start = _utcnow()
                try:
                    observer._original(
                        job, district_dir, day_no,
                        sim_start, sim_end, *arguments,
                    )
                finally:
                    observer.runs.append(_ObservedRun(
                        job=job,
                        day_no=day_no,
                        sim_started_at=sim_start,
                        wall_started_at=wall_start,
                        wall_finished_at=_utcnow(),
                    ))

            _day.launch = wrapped  # type: ignore[method-assign]
            self._active = True
        return self

    def stop(self) -> None:
        if self._active:
            _day.launch = self._original  # type: ignore[method-assign]
            self._active = False


# --- the run ---------------------------------------------------------------

def run_demo(config: Config, out_dir: Path,
             variant: str = "fast",
             simulator_extra_args: tuple[str, ...] = ()) -> dict:
    """Run the whole MVP proof. Returns the report; also writes it to disk.

    Raises nothing of its own: a failed expectation is recorded in the
    report and reflected in the entrypoint's exit code via `main`.
    """
    out_dir = Path(out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    district_dir = out_dir / "district"
    vault_dir = out_dir / "vault"

    clock, jobs, harvest_surge = config.clock, config.jobs, config.harvest_surge
    steps: list[str] = []

    def say(message: str) -> None:
        print(message, flush=True)
        steps.append(message)

    say(f"Nightkeep end-to-end proof, seed {config.seed}")
    district_built = mock_pds.build_district(
        config.seed, config.district, district_dir)
    say(f"district built at {district_built} "
        f"({config.district.ration_cards:,} ration cards)")

    watcher_cfg, habit_cfg, judge_cfg = config.watcher, config.habit, config.judge
    vault_cfg, sim_cfg = config.vault, config.simulator

    # The Judge's trap files are planted BEFORE the watcher starts: the
    # planting itself is not an event anyone should ever judge, and the
    # watcher stamps delivery time on what it sees, so a decoy created
    # moments before the first job could otherwise land inside that job's
    # window and read as an S2 trap touch.
    _plant_judge = Judge(
        root=district_dir,
        habit=None,  # type: ignore[arg-type]
        odd_score=judge_cfg.odd_score,
        rename_burst=judge_cfg.rename_burst,
        entropy_jump=judge_cfg.entropy_jump,
        entropy_floor=judge_cfg.entropy_floor,
        recovery_commands=tuple(judge_cfg.recovery_commands),
        trap_files=tuple(judge_cfg.trap_files),
    )
    planted = _plant_judge.plant_traps()
    say(f"judge ready: {len(planted)} trap files planted before watching "
        f"began, tripwires live from minute one")

    watcher = Watcher(
        district_dir,
        poll_seconds=watcher_cfg.poll_seconds,
        settle_seconds=watcher_cfg.settle_seconds,
    ).start()
    habit = open_habit(
        district_dir,
        habit_cfg.mad_multiplier,
        habit_cfg.min_runs_before_scoring,
        habit_cfg.minimum_spread_fraction,
    )
    judge = Judge(
        root=district_dir,
        habit=habit,
        odd_score=judge_cfg.odd_score,
        rename_burst=judge_cfg.rename_burst,
        entropy_jump=judge_cfg.entropy_jump,
        entropy_floor=judge_cfg.entropy_floor,
        recovery_commands=tuple(judge_cfg.recovery_commands),
        trap_files=tuple(judge_cfg.trap_files),
    )
    vault = Vault(
        root=vault_dir,
        share=district_dir / "share",
        suspect_entropy=vault_cfg.suspect_entropy,
        suspect_changed_fraction=vault_cfg.suspect_changed_fraction,
        suspect_record_drop_fraction=(
            vault_cfg.suspect_record_drop_fraction),
        restore_folder_name=vault_cfg.restore_folder_name,
    )
    # The first Vault pull happens after day 1's jobs, not before them:
    # the Vault judges each pull against the last CLEAN snapshot, and a
    # baseline taken from an empty share/ would flag every later day's
    # ordinary churn as SUSPECT (2 new files over a 1-file baseline is
    # already past the 50% changed limit). A post-day-1 baseline is
    # populated, holds a database backup, and lets the clean pin advance
    # on quiet days -- which is what the restore proof needs.
    report: dict = {
        "seed": config.seed,
        "variant": variant,
        "learning_days": [],
        "guard_days": [],
        "verdicts": [],
        "snapshots": [],
        "checks": {},
    }

    observer = _LaunchObserver().start()
    try:
        say(f"--- learning: {clock.learning_days} days ---")
        for day_no in range(1, clock.learning_days + 1):
            before = len(observer.runs)
            mock_pds.run_day(
                day_no, seed=config.seed, clock=clock, jobs=jobs,
                harvest_surge=harvest_surge, district_dir=district_dir,
            )
            day_runs = observer.runs[before:]
            for observed in day_runs:
                habit.learn(observed.to_job_run(watcher))
            snap = vault.pull()
            report["snapshots"].append(snap.snapshot_id)
            say(f"day {day_no}: learned {len(day_runs)} job runs; "
                f"vault {snap.snapshot_id}: {snap.health}")
            report["learning_days"].append(
                {"day": day_no, "runs_learned": len(day_runs),
                 "snapshot": snap.snapshot_id, "health": snap.health})

        say(f"--- guard: {clock.guard_days} days ---")
        first_guard_day = clock.learning_days + 1
        for day_no in range(first_guard_day,
                            first_guard_day + clock.guard_days):
            before = len(observer.runs)
            mock_pds.run_day(
                day_no, seed=config.seed, clock=clock, jobs=jobs,
                harvest_surge=harvest_surge, district_dir=district_dir,
            )
            day_runs = observer.runs[before:]
            for observed in day_runs:
                run = observed.to_job_run(watcher)
                verdict = judge.verdict(run)
                report["verdicts"].append(
                    {"day": day_no, "job": observed.job,
                     "level": verdict.level,
                     "signals": [s.code for s in verdict.signals]})
                if verdict.level == INCIDENT:
                    say(f"day {day_no} {observed.job}: INCIDENT "
                        f"(unexpected on a guard day)")
                else:
                    say(f"day {day_no} {observed.job}: {verdict.level}")
            snap = vault.pull()
            report["snapshots"].append(snap.snapshot_id)
            say(f"day {day_no}: vault {snap.snapshot_id}: {snap.health}")
            report["guard_days"].append(
                {"day": day_no, "runs_judged": len(day_runs),
                 "snapshot": snap.snapshot_id, "health": snap.health})

        say("--- attack: safe ransomware simulator ---")
        attack_start = _utcnow()
        subprocess.run(
            [sys.executable, "-m", "nightkeep.simulator",
             "--variant", variant,
             "--root", str(district_dir),
             "--key", sim_cfg.key,
             "--locked-extension", sim_cfg.locked_extension,
             "--ransom-note-name", sim_cfg.ransom_note_name,
             "--delay", str(sim_cfg.delay_between_files_seconds),
             *simulator_extra_args],
            check=True,
        )
        # The watcher stamps delivery time on what it sees, so wait out
        # its settle window before closing the attack's event window;
        # otherwise the attack's tail could arrive after the window closed
        # and go unjudged.
        time.sleep(watcher_cfg.settle_seconds)
        attack_end = _utcnow()
        attack_events = tuple(watcher.events_between(attack_start, attack_end))
        attack_run = JobRun(
            job="simulator",
            identity=f"simulator|{variant}|external-process",
            started_at=attack_start,
            finished_at=attack_end,
            events=attack_events,
            sim_started_at=None,
            day_no=first_guard_day + clock.guard_days,
        )
        attack_verdict = judge.verdict(attack_run)
        say(f"attack verdict: {attack_verdict.level}")
        for reason in attack_verdict.reasons:
            say(f"  why: {reason}")
        for action in attack_verdict.actions:
            say(f"  did: {action}")
        report["attack"] = {
            "variant": variant,
            "level": attack_verdict.level,
            "signals": [s.code for s in attack_verdict.signals],
            "reasons": list(attack_verdict.reasons),
            "actions": list(attack_verdict.actions),
            "events_observed": len(attack_events),
        }

        say("--- vault after the attack ---")
        pin_before = _clean_point(vault)
        damaged = vault.pull()
        pin_after = _clean_point(vault)
        say(f"vault pull {damaged.snapshot_id}: {damaged.health}")
        for reason in damaged.reasons:
            say(f"  why: {reason}")
        say(f"clean pin before: {pin_before}; after: {pin_after}")
        report["snapshots"].append(damaged.snapshot_id)
        report["attack"]["snapshot"] = damaged.snapshot_id
        report["attack"]["snapshot_health"] = damaged.health
        report["attack"]["clean_pin_held"] = pin_before == pin_after

        say("--- recovery: restore the pinned clean snapshot ---")
        restore_result = vault.restore(pin_after)
        say(f"restored {restore_result.snapshot_id} to "
            f"{restore_result.restored_to}")
        for check in restore_result.checks:
            mark = "pass" if check.passed else "FAIL"
            say(f"  [{mark}] {check.statement}")
        say(f"cards recovered: {restore_result.records_verified:,} / "
            f"{restore_result.records_expected:,}")
        report["restore"] = {
            "snapshot_id": restore_result.snapshot_id,
            "ok": restore_result.ok,
            "records_verified": restore_result.records_verified,
            "records_expected": restore_result.records_expected,
            "checks": [{"statement": c.statement, "passed": c.passed}
                       for c in restore_result.checks],
            "restored_to": restore_result.restored_to,
        }
    finally:
        observer.stop()
        watcher.stop()

    incidents_on_quiet_days = sum(
        1 for v in report["verdicts"] if v["level"] == INCIDENT)
    attack_ok = report["attack"]["level"] == INCIDENT
    suspect_ok = report["attack"]["snapshot_health"] == SUSPECT
    pin_ok = report["attack"]["clean_pin_held"]
    restore = report["restore"]
    restore_ok = (restore["ok"] and restore["records_verified"]
                  == restore["records_expected"]
                  == config.district.ration_cards)
    report["checks"] = {
        "no_incident_on_learning_or_guard_days": incidents_on_quiet_days == 0,
        "attack_judged_incident": attack_ok,
        "damaged_snapshot_suspect": suspect_ok,
        "clean_pin_held": pin_ok,
        "restore_ok_5000_of_5000": restore_ok,
    }
    passed = all(report["checks"].values())
    say("--- proof " + ("PASSED" if passed else "FAILED") + " ---")
    for name, ok in report["checks"].items():
        say(f"  [{'pass' if ok else 'FAIL'}] {name}")
    report["passed"] = passed
    report["steps"] = steps

    report_path = district_dir / "reports" / REPORT_NAME
    report_path.write_text(json.dumps(report, indent=2, default=str) + "\n",
                           encoding="utf-8")
    say(f"report written to {report_path}")
    return report


def _clean_point(vault: Vault) -> str | None:
    """The currently pinned clean snapshot id, if any."""
    pinned = [s for s in vault.snapshots() if s.is_clean_point]
    return pinned[-1].snapshot_id if pinned else None


def main(config: Config, out_dir: Path, variant: str = "fast") -> int:
    """Entrypoint wrapper: run the proof, return a process exit code."""
    try:
        report = run_demo(config, out_dir, variant=variant)
    except FileNotFoundError as problem:
        # The Windows-only jobs (fix_dat.vbs via cscript, archive_old.bat
        # via cmd) cannot run where those interpreters do not exist. The
        # proof itself is written for the demo machine; this names the
        # blocker instead of failing mysteriously.
        print(f"Nightkeep cannot run the proof here. {problem}",
              file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as problem:
        print(f"Nightkeep cannot run the proof here. {problem}",
              file=sys.stderr)
        return 1
    return 0 if report["passed"] else 1


__all__ = ["run_demo", "main", "REPORT_NAME"]
