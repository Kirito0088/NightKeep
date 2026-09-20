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
from datetime import datetime, timedelta, timezone
from pathlib import Path

from nightkeep import mock_pds
from nightkeep.config import Config
from nightkeep.habit import open_habit
from nightkeep.judge import Judge
from nightkeep.mock_pds import _day
from nightkeep.types import (
    CLEAN,
    INCIDENT,
    NORMAL,
    SUSPECT,
    SUSPICIOUS,
    Event,
    JobRun,
    WatcherLiveness,
)
from nightkeep.vault import Vault, combined_verdict
from nightkeep.watcher import event_log_for
from nightkeep.watcher.__main__ import heartbeat_path
from nightkeep.watcher._log import EventLog

REPORT_NAME = "demo_run.json"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --- the F11 watcher agent ---------------------------------------------------

# argv the demo uses to start the agent. The watcher-killer finds it by
# these same markers plus the demo root; nothing else on the machine looks
# like this.


def _start_watcher_agent(
    district_dir: Path,
    interval_seconds: float,
    poll_seconds: float,
    settle_seconds: float,
) -> subprocess.Popen:
    """Launch the Watcher agent as its own process.

    This IS the agent: it watches the folder and writes the liveness
    heartbeat. A separate process on purpose: the watcher-killer
    terminates exactly this, and the demo must survive that. The agent
    writes into the share; the Vault reads it back through the share, so
    the one-way pull model and the separation of the two machines are
    untouched.
    """
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "nightkeep.watcher",
            "--run",
            "--root",
            str(district_dir),
            "--interval",
            str(interval_seconds),
            "--poll-seconds",
            str(poll_seconds),
            "--settle-seconds",
            str(settle_seconds),
        ]
    )
    # The agent stamps the heartbeat before its first sleep, but importing
    # nightkeep takes a moment: wait until the first beat actually lands.
    deadline = time.monotonic() + 30
    while not heartbeat_path(district_dir).exists():
        if proc.poll() is not None:
            raise RuntimeError(
                "the watcher agent exited before its first beat")
        if time.monotonic() > deadline:
            raise RuntimeError(
                "the watcher agent never wrote its first beat")
        time.sleep(0.1)
    return proc


def _stop_watcher_agent(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def _events_between(
    event_log: EventLog,
    start: datetime,
    end: datetime,
    settle_seconds: float,
) -> list[Event]:
    """The changes the agent logged for one run's window.

    Read back from the agent's append-only on-disk log: the demo runner
    does not join the agent process. The end is stretched by
    settle_seconds, because a job's last writes can land a moment after
    its process has exited.
    """
    limit = end + timedelta(seconds=settle_seconds)
    return [
        event for event in event_log.read_all() if start <= event.at <= limit
    ]


def _await_silence(vault: Vault, timeout_seconds: float) -> WatcherLiveness:
    """Wait until the Vault's own clock calls the watcher silent.

    Real timing, not a claim: this returns only when a fresh
    check_watcher_liveness() actually reports silence, or when the
    timeout expires (in which case the returned liveness says so).
    """
    deadline = time.monotonic() + timeout_seconds
    liveness = vault.check_watcher_liveness()
    while liveness.alive and time.monotonic() < deadline:
        time.sleep(0.5)
        liveness = vault.check_watcher_liveness()
    return liveness


# --- observing job runs without touching module logic ----------------------

@dataclass
class _ObservedRun:
    """One job launch, as the wrapper saw it: names and clocks only."""

    job: str
    day_no: int
    sim_started_at: datetime
    wall_started_at: datetime
    wall_finished_at: datetime

    def to_job_run(self, event_log: EventLog, settle_seconds: float) -> JobRun:
        events = tuple(
            _events_between(
                event_log,
                self.wall_started_at,
                self.wall_finished_at,
                settle_seconds,
            )
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
    out_dir = Path(out_dir).resolve()
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

    # F11: the watcher agent runs as its own process -- it watches the
    # folder and writes the liveness heartbeat -- so the watcher-killer
    # can terminate the actual agent without taking the demo down. The
    # Vault reads its beats through the share; the demo reads its events
    # back from the agent's append-only log on disk.
    agent_proc = _start_watcher_agent(
        district_dir,
        watcher_cfg.heartbeat_interval_seconds,
        watcher_cfg.poll_seconds,
        watcher_cfg.settle_seconds,
    )
    event_log = event_log_for(district_dir)
    say("watcher agent running (watches + heartbeats; the vault checks it, S6)")
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
        # F9: the office computer shows its own pop-up the moment this
        # Judge decides INCIDENT. The trap-planting Judge above never
        # judges a run, so it needs no flag.
        server_alerts=True,
    )
    vault = Vault(
        root=vault_dir,
        share=district_dir / "share",
        suspect_entropy=vault_cfg.suspect_entropy,
        suspect_changed_fraction=vault_cfg.suspect_changed_fraction,
        suspect_record_drop_fraction=(
            vault_cfg.suspect_record_drop_fraction),
        restore_folder_name=vault_cfg.restore_folder_name,
        watcher_silence_seconds=watcher_cfg.silence_threshold_seconds,
        liveness_check_interval_seconds=(
            watcher_cfg.liveness_check_interval_seconds),
    )
    # F11: for the whole run the Vault asks the agent for liveness on its
    # own clock (design-doc S6: every 10 s), not only when the demo
    # happens to call check_watcher_liveness(). The state hook is the
    # documented SUSPICIOUS response made visible: the Vault records the
    # verdict itself, enters Protect mode, and raises the loud alert --
    # the demo prints it and keeps it in the report.
    vault_alerts: list = []

    def _on_vault_state(state) -> None:
        vault_alerts.append(
            {
                "verdict": state.verdict,
                "previous_verdict": state.previous_verdict,
                "watcher_alive": state.watcher_alive,
                "snapshot_health": state.snapshot_health,
            }
        )
        say(f"*** VAULT ALERT: {state.verdict} -- watcher alive: "
            f"{state.watcher_alive}, snapshot: {state.snapshot_health}, "
            f"protect mode {'ON' if state.protect_mode else 'off'}")

    vault.start_liveness_monitor(on_state_change=_on_vault_state)
    say("vault liveness monitor running (asks the watcher every "
        f"{watcher_cfg.liveness_check_interval_seconds:.0f} s)")
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
                habit.learn(observed.to_job_run(
                    event_log, watcher_cfg.settle_seconds))
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
                run = observed.to_job_run(
                    event_log, watcher_cfg.settle_seconds)
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
        liveness_before = vault.check_watcher_liveness()
        say(f"watcher liveness before attack: "
            f"{'alive' if liveness_before.alive else 'SILENT'} "
            f"({liveness_before.reason})")
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
        agent_terminated: bool | None = None
        if variant == "watcher-killer":
            # The killer just terminated the watcher agent itself. Wait
            # for the silence to actually age past the configured
            # threshold: the Vault detects it by its own clock, nothing
            # is asserted early.
            agent_terminated = agent_proc.poll() is not None
            say(f"watcher agent terminated by the killer: "
                f"{agent_terminated}")
            _await_silence(
                vault,
                timeout_seconds=watcher_cfg.silence_threshold_seconds + 30,
            )
        # The watcher stamps delivery time on what it sees, so wait out
        # its settle window before closing the attack's event window;
        # otherwise the attack's tail could arrive after the window closed
        # and go unjudged.
        time.sleep(watcher_cfg.settle_seconds)
        attack_end = _utcnow()
        attack_events = tuple(
            _events_between(
                event_log,
                attack_start,
                attack_end,
                watcher_cfg.settle_seconds,
            )
        )
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
        liveness_after = vault.check_watcher_liveness()
        say(f"watcher liveness after attack: "
            f"{'alive' if liveness_after.alive else 'SILENT'} "
            f"({liveness_after.reason})")
        report["attack"] = {
            "variant": variant,
            "level": attack_verdict.level,
            "signals": [s.code for s in attack_verdict.signals],
            "reasons": list(attack_verdict.reasons),
            "actions": list(attack_verdict.actions),
            "events_observed": len(attack_events),
        }
        report["watcher_liveness"] = {
            "before_attack": {
                "alive": liveness_before.alive,
                "reason": liveness_before.reason,
            },
            "after_attack": {
                "alive": liveness_after.alive,
                "reason": liveness_after.reason,
            },
            "heartbeat_interval_seconds":
                watcher_cfg.heartbeat_interval_seconds,
            "silence_threshold_seconds":
                watcher_cfg.silence_threshold_seconds,
            "liveness_check_interval_seconds":
                watcher_cfg.liveness_check_interval_seconds,
            "agent_terminated": agent_terminated,
            "vault_liveness_checks": vault.liveness_check_count,
            "vault_alerts": vault_alerts,
            "vault_verdict": vault.vault_verdict,
            "protect_mode": vault.protect_mode,
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
        report["attack"]["pin_snapshot_id"] = pin_after
        report["attack"]["pin_before_snapshot_id"] = pin_before
        # The Vault's own call from its two witnesses: S6 liveness plus
        # S7 data health. Kept out of the snapshot on purpose -- the
        # snapshot still describes only the data.
        vault_side = combined_verdict(liveness_after, damaged.health)
        say(f"vault-side call from S6 liveness + S7 data health: {vault_side}")
        report["watcher_liveness"]["vault_side_verdict"] = vault_side

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
        vault.stop_liveness_monitor()
        _stop_watcher_agent(agent_proc)

    incidents_on_quiet_days = sum(
        1 for v in report["verdicts"] if v["level"] == INCIDENT)
    attack_ok = report["attack"]["level"] == INCIDENT
    suspect_ok = report["attack"]["snapshot_health"] == SUSPECT
    pin_ok = report["attack"]["clean_pin_held"]
    liveness = report["watcher_liveness"]
    restore = report["restore"]
    restore_ok = (restore["ok"] and restore["records_verified"]
                  == restore["records_expected"]
                  == config.district.ration_cards)
    if variant == "watcher-killer":
        # F11's story: the killer stops the agent itself without touching
        # a file. The server-side Judge rightly sees nothing (NORMAL);
        # the Vault still raises the alarm from the silence (S6) and
        # enters Protect mode, which holds the last clean point. The
        # data is untouched, so the post-kill pull is still CLEAN -- but
        # it must NOT become the new pin while protection is active. The
        # check is that the pin still covers clean, identical data, now
        # by holding the pre-kill clean point instead of advancing.
        pin_snapshot_id = report["attack"]["pin_snapshot_id"]
        pin_is_clean = (
            pin_snapshot_id == report["attack"]["pin_before_snapshot_id"]
            and report["attack"]["snapshot_health"] == CLEAN
        )
        report["checks"] = {
            "no_incident_on_learning_or_guard_days":
                incidents_on_quiet_days == 0,
            "heartbeat_alive_before_kill":
                liveness["before_attack"]["alive"],
            "killer_terminated_watcher_agent":
                liveness["agent_terminated"] is True,
            "server_judge_saw_no_attack":
                report["attack"]["level"] == NORMAL,
            "vault_detected_silence_s6":
                not liveness["after_attack"]["alive"],
            "vault_side_call_suspicious":
                liveness["vault_side_verdict"] == SUSPICIOUS,
            "clean_pin_covers_untouched_data": pin_is_clean,
            "restore_ok_5000_of_5000": restore_ok,
        }
    else:
        report["checks"] = {
            "no_incident_on_learning_or_guard_days":
                incidents_on_quiet_days == 0,
            "attack_judged_incident": attack_ok,
            "damaged_snapshot_suspect": suspect_ok,
            "clean_pin_held": pin_ok,
            "watcher_stayed_alive": liveness["after_attack"]["alive"],
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
