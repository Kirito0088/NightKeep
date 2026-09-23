"""The live session: the district PDS server, running while the console does.

Glue, with the same standing as demo_run.py, whose proven pieces it reuses:
the watcher agent, the launch observer's windows, and the live attack loop.
Every decision stays in the modules. This file only calls them in the order
a live office needs and writes down what happened, for the console to read:

1. Build the district, plant the Judge's canaries, start the watcher agent,
   open Habit, set up the Judge and the Vault with its liveness monitor.
2. Live simulated days, one after another, on a thread of their own. Days
   1 to clock.learning_days fold every job run into Habit. Every later day
   asks the Judge about every run. The Vault pulls after each day.
3. Between job runs, obey the demo controls the console writes to
   control.json: the harvest surge switch and the safe simulator.
4. On an attack: wait for any running job to finish, hold further jobs,
   and run demo_run's live attack loop. The simulator is ended, but the
   Judge's read-only lock keeps holding the records. The Vault pulls the
   damage (SUSPECT) with its clean pin held.
5. Manual mode: wait for the console to report that the supervisor
   restored from the Vault, then release the lock. Autopilot mode (the
   Full MVP Demo): after the guard days, attack by itself, restore by
   itself, and write the same proof lines demo_run prints.

The two sides only share files (nightkeep.live_protocol). The jobs are
never told where the Vault is, exactly as in demo_run. This file never
reads a ground-truth log.

Usage (from the entrypoint, the only caller of load_config):
    python -m nightkeep --live-engine --out-dir demo/live [--autopilot]
"""

from __future__ import annotations

import json
import os
import queue
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from nightkeep import mock_pds
from nightkeep import live_protocol as lp
from nightkeep.config import Config
from nightkeep.demo_run import (
    _clean_point,
    _judge_attack_live,
    _ObservedRun,
    _recovery_killer_command_args,
    _start_watcher_agent,
    _stop_watcher_agent,
)
from nightkeep.habit import open_habit
from nightkeep.judge import Judge
from nightkeep.mock_pds import _day
from nightkeep.types import CLEAN, INCIDENT, ODD, SUSPECT
from nightkeep.vault import Vault, combined_verdict
from nightkeep.watcher import event_log_for


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat(timespec="seconds") if value is not None else None


class _Halted(Exception):
    """The office stopped: an attack is being handled, or the session ends."""


class _Office:
    """Wraps `_day.launch` for the whole session.

    Records each job's window exactly as demo_run's observer does, and adds
    the two things a live office needs: a lock held for the length of every
    job, so an attack can wait for a running job instead of overlapping it,
    and a halt that refuses every job after it.
    """

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.halted = threading.Event()
        self.running: dict | None = None
        self._runs: list[_ObservedRun] = []
        self._runs_lock = threading.Lock()
        self._original = _day.launch
        self._active = False

    def start(self) -> None:
        if not self._active:
            _day.launch = self._launch  # type: ignore[method-assign]
            self._active = True

    def stop(self) -> None:
        if self._active:
            _day.launch = self._original  # type: ignore[method-assign]
            self._active = False

    def halt(self) -> None:
        """Refuse every later job. Waits for a running job to finish first."""
        with self.lock:
            self.halted.set()

    def _launch(self, job: str, district_dir: Path, day_no: int,
                sim_start: datetime, sim_end: datetime, *arguments: str) -> None:
        with self.lock:
            if self.halted.is_set():
                raise _Halted()
            self.running = {"job": job, "day": day_no,
                            "sim_start": sim_start.strftime("%H:%M")}
            wall_start = _utcnow()
            try:
                self._original(job, district_dir, day_no,
                               sim_start, sim_end, *arguments)
            finally:
                self.running = None
                with self._runs_lock:
                    self._runs.append(_ObservedRun(
                        job=job, day_no=day_no, sim_started_at=sim_start,
                        wall_started_at=wall_start, wall_finished_at=_utcnow(),
                    ))

    def take_settled(self, settle_seconds: float,
                     wait: bool = False) -> list[_ObservedRun]:
        """Finished runs whose settle window has passed, oldest first.

        With wait=True, waits out the settle window of the newest run so
        every finished run is returned.
        """
        with self._runs_lock:
            pending = list(self._runs)
        if not pending:
            return []
        if wait:
            newest = max(run.wall_finished_at for run in pending)
            remaining = settle_seconds - (_utcnow() - newest).total_seconds()
            if remaining > 0:
                time.sleep(remaining)
        now = _utcnow()
        settled = [
            run for run in pending
            if (now - run.wall_finished_at).total_seconds() >= settle_seconds
        ]
        with self._runs_lock:
            for run in settled:
                self._runs.remove(run)
        return settled


@dataclass
class _JobState:
    last_day: int | None = None
    last_sim_start: str | None = None
    last_level: str | None = None
    last_reasons: tuple[str, ...] = ()


class LiveEngine:
    """One live session. `run()` returns a process exit code."""

    def __init__(self, config: Config, paths: lp.SessionPaths, *,
                 autopilot: bool, variant: str,
                 parent_pid: int | None = None) -> None:
        self.config = config
        self.paths = paths
        self.autopilot = autopilot
        self.variant = variant
        self.parent_pid = parent_pid

        self._state_lock = threading.Lock()
        self._control: dict = lp.empty_control()
        self._handled_attack_id = None
        self._handled_restore_id = None

        self.phase = lp.STARTING
        self.note = "Preparing the district."
        self.day_no = 0
        self.days_done = 0
        self.surge_tonight = False
        self.surge_why: str | None = None
        self.jobs = {name: _JobState() for name in vars(config.jobs)}
        self.nights_checked = 0
        self.odd_count = 0
        self.incident_count = 0
        self.recent = deque(maxlen=config.live.recent_checks_kept)
        self.attack: dict = {"state": "none"}
        self.proof: dict | None = None
        self.error: str | None = None
        self._version = 0
        self._last_written: str | None = None

        self.report: dict = {
            "seed": config.seed,
            "variant": variant,
            "mode": "autopilot" if autopilot else "manual",
            "learning_days": [],
            "guard_days": [],
            "verdicts": [],
            "snapshots": [],
            "checks": {},
        }
        self._office = _Office()
        self._days_done: queue.Queue = queue.Queue()
        self._acks: queue.Queue = queue.Queue()
        self._days_over = threading.Event()
        self._day_error: BaseException | None = None
        self.vault: Vault | None = None
        self.habit = None
        self.judge: Judge | None = None

    # --- output ----------------------------------------------------------

    def say(self, message: str) -> None:
        print(message, flush=True)

    def _set_phase(self, phase: str, note: str) -> None:
        self.phase = phase
        self.note = note
        self._write_status()

    # --- the run -----------------------------------------------------------

    def run(self) -> int:
        cfg = self.config
        district_dir = self.paths.district
        self.say(f"Nightkeep live session, seed {cfg.seed}, "
                 f"{'autopilot' if self.autopilot else 'manual'} mode")
        self._write_status()
        agent_proc = None
        try:
            leftovers = [path.name for path in (district_dir, self.paths.vault)
                         if path.exists()]
            if leftovers:
                # The console wipes the session folder before every start.
                # A district or Vault already here is an older session's:
                # its .locked files and snapshots would pass for this one's.
                raise RuntimeError(
                    f"{self.paths.root} already holds {', '.join(leftovers)} "
                    "from an earlier session; start from an empty folder"
                )
            mock_pds.build_district(cfg.seed, cfg.district, district_dir)
            self.say(f"district built at {district_dir} "
                     f"({cfg.district.ration_cards:,} ration cards)")
            self.judge = self._make_judge(server_alerts=True, habit=None)
            planted = self.judge.plant_canaries()
            self.say(f"judge ready: {len(planted)} canary files planted, "
                     "canaries live from minute one")
            agent_proc = _start_watcher_agent(
                district_dir,
                cfg.watcher.heartbeat_interval_seconds,
                cfg.watcher.poll_seconds,
                cfg.watcher.settle_seconds,
            )
            self.event_log = event_log_for(district_dir)
            self.habit = open_habit(
                district_dir, cfg.habit.mad_multiplier,
                cfg.habit.min_runs_before_scoring,
                cfg.habit.minimum_spread_fraction,
            )
            self.judge = self._make_judge(server_alerts=True, habit=self.habit)
            self.vault = Vault(
                root=self.paths.vault,
                share=district_dir / "share",
                suspect_entropy=cfg.vault.suspect_entropy,
                suspect_changed_fraction=cfg.vault.suspect_changed_fraction,
                suspect_record_drop_fraction=cfg.vault.suspect_record_drop_fraction,
                restore_folder_name=cfg.vault.restore_folder_name,
                watcher_silence_seconds=cfg.watcher.silence_threshold_seconds,
                liveness_check_interval_seconds=(
                    cfg.watcher.liveness_check_interval_seconds),
            )
            self.vault.start_liveness_monitor(on_state_change=self._on_vault_state)
            self.say("watcher agent and vault liveness monitor running")

            self._office.start()
            self._set_phase(lp.LEARNING, "Learning the night jobs.")
            self.say(f"--- learning: {cfg.clock.learning_days} days ---")
            days = threading.Thread(target=self._live_days, name="office-days",
                                    daemon=True)
            days.start()
            self._loop()
        except KeyboardInterrupt:
            self.say("stopped from the keyboard")
        except Exception as problem:  # the session must say why it died
            self.error = f"{type(problem).__name__}: {problem}"
            self.say(f"the live session failed: {self.error}")
            self.phase = lp.FAILED
            self.note = "The live session stopped because of an error."
        finally:
            # halt(), not halted.set(): wait for a night job that is running
            # right now. The days thread is a daemon, so without the wait
            # the job's own process would outlive the engine and keep
            # writing into a district the console is about to wipe.
            self._office.halt()
            self._office.stop()
            self._acks.put(None)
            if self.vault is not None:
                self.vault.stop_liveness_monitor()
            if agent_proc is not None:
                _stop_watcher_agent(agent_proc)
            if self.judge is not None:
                self.judge.undo()
            if self.phase not in lp.FINISHED_PHASES:
                self.phase = lp.STOPPED
                self.note = "The live session has stopped."
            self._write_status(force=True)
            self._write_report()
        if self.phase == lp.FAILED:
            return 1
        if self.proof is not None and not self.proof.get("passed"):
            return 1
        return 0

    def _make_judge(self, *, server_alerts: bool, habit) -> Judge:
        judge_cfg = self.config.judge
        return Judge(
            root=self.paths.district,
            habit=habit,  # type: ignore[arg-type]
            odd_score=judge_cfg.odd_score,
            rename_burst=judge_cfg.rename_burst,
            entropy_jump=judge_cfg.entropy_jump,
            entropy_floor=judge_cfg.entropy_floor,
            recovery_commands=tuple(judge_cfg.recovery_commands),
            canary_files=tuple(judge_cfg.canary_files),
            server_alerts=server_alerts,
        )

    def _on_vault_state(self, state) -> None:
        self.report.setdefault("vault_alerts", []).append({
            "verdict": state.verdict,
            "previous_verdict": state.previous_verdict,
            "watcher_alive": state.watcher_alive,
            "snapshot_health": state.snapshot_health,
        })
        self.say(f"*** VAULT ALERT: {state.verdict} -- watcher alive: "
                 f"{state.watcher_alive}, snapshot: {state.snapshot_health}")

    # --- the days thread ---------------------------------------------------

    def _live_days(self) -> None:
        cfg = self.config
        last_autopilot_day = cfg.clock.learning_days + cfg.clock.guard_days
        day_no = 0
        try:
            while not self._office.halted.is_set():
                day_no += 1
                if self.autopilot and day_no > last_autopilot_day:
                    break
                switched_on = bool(self._control.get("harvest_surge"))
                scheduled = day_no in cfg.harvest_surge.days
                with self._state_lock:
                    self.day_no = day_no
                    self.surge_tonight = switched_on or scheduled
                    self.surge_why = ("switched on" if switched_on
                                      else "scheduled" if scheduled else None)
                mock_pds.run_day(
                    day_no, seed=cfg.seed, clock=cfg.clock, jobs=cfg.jobs,
                    harvest_surge=cfg.harvest_surge,
                    district_dir=self.paths.district,
                    harvest_surge_override=True if switched_on else None,
                )
                self._days_done.put(day_no)
                self._acks.get()
        except _Halted:
            pass
        except BaseException as problem:
            if not self._office.halted.is_set():
                self._day_error = problem
        finally:
            self._days_over.set()

    # --- the main loop -----------------------------------------------------

    def _loop(self) -> None:
        poll = self.config.live.command_poll_seconds
        while True:
            self._control = lp.read_json(self.paths.control) or self._control
            if self._control.get("stop"):
                self.say("stop requested by the console")
                return
            if self.parent_pid is not None and not _pid_alive(self.parent_pid):
                self.say("the console has gone; stopping")
                return
            if self._day_error is not None:
                raise RuntimeError(
                    f"a simulated day failed: {self._day_error}"
                ) from self._day_error

            self._digest(self._office.take_settled(
                self.config.watcher.settle_seconds))
            self._finish_days()
            self._obey_commands()

            if (self.autopilot and self._days_over.is_set()
                    and self.attack["state"] == "none"
                    and self.phase in (lp.LEARNING, lp.GUARD)):
                self._attack(self.config.console.full_demo_variant, None)
            if self.phase in lp.FINISHED_PHASES:
                return
            self._write_status()
            time.sleep(poll)

    def _finish_days(self) -> None:
        while True:
            try:
                day_no = self._days_done.get_nowait()
            except queue.Empty:
                return
            if self._office.halted.is_set():
                # The day was cut short by an attack: it is not a night the
                # Vault should pull as ordinary work.
                self._acks.put(None)
                continue
            self._digest(self._office.take_settled(
                self.config.watcher.settle_seconds, wait=True))
            snap = self.vault.pull()
            self.report["snapshots"].append(snap.snapshot_id)
            learning = day_no <= self.config.clock.learning_days
            entry = {"day": day_no, "snapshot": snap.snapshot_id,
                     "health": snap.health}
            (self.report["learning_days"] if learning
             else self.report["guard_days"]).append(entry)
            self.days_done = day_no
            self.say(f"day {day_no}: vault {snap.snapshot_id}: {snap.health}")
            if day_no == self.config.clock.learning_days:
                self.say(f"--- guard: {self.config.clock.guard_days} days ---")
                if self.phase == lp.LEARNING:
                    self._set_phase(lp.GUARD, "Checking every night job.")
            self._write_report()
            self._acks.put(None)

    def _digest(self, observed_runs: list[_ObservedRun]) -> None:
        """Fold finished runs into Habit, or ask the Judge about them."""
        for observed in observed_runs:
            run = observed.to_job_run(self.event_log,
                                      self.config.watcher.settle_seconds)
            state = self.jobs.setdefault(observed.job, _JobState())
            state.last_day = observed.day_no
            state.last_sim_start = observed.sim_started_at.strftime("%H:%M")
            if observed.day_no <= self.config.clock.learning_days:
                self.habit.learn(run)
                continue
            verdict = self.judge.verdict(run)
            state.last_level = verdict.level
            state.last_reasons = tuple(verdict.reasons)
            self.nights_checked += 1
            if verdict.level == ODD:
                self.odd_count += 1
            record = {"day": observed.day_no, "job": observed.job,
                      "level": verdict.level,
                      "signals": [s.code for s in verdict.signals],
                      "reasons": list(verdict.reasons)}
            self.report["verdicts"].append(record)
            self.recent.appendleft(record)
            self.say(f"day {observed.day_no} {observed.job}: {verdict.level}")
            if verdict.level == INCIDENT:
                # P1 says this never happens. If it ever does, the Judge has
                # already contained it; the office stops and waits for a
                # restore like any other incident.
                self.incident_count += 1
                self._office.halted.set()
                self.attack = {"state": "contained", "variant": None,
                               "job": observed.job}
                self._set_phase(lp.CONTAINED,
                                "A night job tripped a canary and was stopped.")

    def _obey_commands(self) -> None:
        attack = self._control.get("attack")
        if isinstance(attack, dict) and attack.get("id") != self._handled_attack_id:
            self._handled_attack_id = attack.get("id")
            if self.attack_readiness() == lp.ATTACK_READY:
                variant = attack.get("variant") or self.config.console.attack_variants[0]
                if variant not in self.config.console.attack_variants:
                    self.say(f"ignored an attack request for unknown variant {variant!r}")
                else:
                    self._attack(variant, attack.get("id"))
            else:
                self.say(f"ignored an attack request: {self.attack_readiness()}")

        restored = self._control.get("restored")
        if (isinstance(restored, dict)
                and restored.get("id") != self._handled_restore_id):
            if self.phase == lp.CONTAINED:
                self._handled_restore_id = restored.get("id")
                if restored.get("ok"):
                    self._release_after_restore(restored)
            elif self.phase not in lp.LOCKED_PHASES:
                # No lock to release: nothing to do with this restore.
                self._handled_restore_id = restored.get("id")
            # Otherwise the attack is still being handled (the Vault is
            # pulling): keep the restore until the records are CONTAINED,
            # or the lock would never be released.

    def attack_readiness(self) -> str:
        if self.phase not in (lp.LEARNING, lp.GUARD):
            if self.attack["state"] != "none":
                return lp.ATTACK_ALREADY_RAN
            return lp.ATTACK_NOT_RUNNING
        if self.attack["state"] != "none":
            return lp.ATTACK_BUSY
        if self.vault is None or _clean_point(self.vault) is None:
            return lp.ATTACK_WAIT_FOR_CLEAN_COPY
        return lp.ATTACK_READY

    # --- the attack ----------------------------------------------------------

    def _attack(self, variant: str, request_id) -> None:
        cfg = self.config
        self.attack = {"state": "waiting", "variant": variant, "id": request_id}
        self._set_phase(lp.ATTACK, "Waiting for the running night job to finish.")
        self._office.halt()
        self._acks.put(None)
        self._digest(self._office.take_settled(cfg.watcher.settle_seconds,
                                               wait=True))
        if self.phase != lp.ATTACK:
            return  # a night job's own incident got there first

        self.say("--- attack: safe ransomware simulator ---")
        self.attack["state"] = "running"
        self._set_phase(lp.ATTACK, "The safe simulated attack is running.")
        liveness_before = self.vault.check_watcher_liveness()
        extra: tuple[str, ...] = ()
        if variant == "recovery-killer":
            extra = _recovery_killer_command_args(tuple(cfg.judge.recovery_commands))
        sim = cfg.simulator
        evidence = _judge_attack_live(
            simulator_argv=[
                sys.executable, "-m", "nightkeep.simulator",
                "--variant", variant,
                "--root", str(self.paths.district),
                "--key", sim.key,
                "--locked-extension", sim.locked_extension,
                "--ransom-note-name", sim.ransom_note_name,
                "--delay", str(sim.delay_between_files_seconds),
                *extra,
            ],
            event_log=self.event_log,
            judge=self.judge,
            district_dir=self.paths.district,
            variant=variant,
            day_no=self.day_no,
            settle_seconds=cfg.watcher.settle_seconds,
            say=self.say,
            release_lock=False,
        )
        self.say(f"attack verdict: {evidence['level']}")
        for reason in evidence["reasons"]:
            self.say(f"  why: {reason}")
        for action in evidence["actions"]:
            self.say(f"  did: {action}")
        self.report["attack"] = evidence
        caught = evidence["level"] == INCIDENT
        if caught:
            self.incident_count += 1
        self.attack.update({"state": "contained" if caught else "missed",
                            "level": evidence["level"]})
        self._set_phase(lp.CONTAINMENT if caught else lp.VAULT,
                        "The attack was stopped." if caught
                        else "The attack was not stopped.")

        self.say("--- vault after the attack ---")
        self._set_phase(lp.VAULT, "The Vault is checking the newest copy.")
        pin_before = _clean_point(self.vault)
        damaged = self.vault.pull()
        pin_after = _clean_point(self.vault)
        self.say(f"vault pull {damaged.snapshot_id}: {damaged.health}")
        for reason in damaged.reasons:
            self.say(f"  why: {reason}")
        self.say(f"clean pin before: {pin_before}; after: {pin_after}")
        liveness_after = self.vault.check_watcher_liveness()
        self.report["snapshots"].append(damaged.snapshot_id)
        evidence.update({
            "snapshot": damaged.snapshot_id,
            "snapshot_health": damaged.health,
            "clean_pin_held": pin_before == pin_after,
            "pin_snapshot_id": pin_after,
            "pin_before_snapshot_id": pin_before,
        })
        self.report["watcher_liveness"] = {
            "before_attack": {"alive": liveness_before.alive,
                              "reason": liveness_before.reason},
            "after_attack": {"alive": liveness_after.alive,
                             "reason": liveness_after.reason},
            "vault_side_verdict": combined_verdict(liveness_after, damaged.health),
            "protect_mode": self.vault.protect_mode,
        }
        self._write_report()

        if not caught:
            self.judge.undo()
            self._set_phase(lp.FAILED, "The simulated attack was not stopped.")
            self._finish_proof(restore_ok=False)
            return
        self._set_phase(lp.CONTAINED,
                        "The records are locked until they are restored.")
        if self.autopilot:
            self._autopilot_restore(pin_after)

    def _autopilot_restore(self, snapshot_id: str | None) -> None:
        self._set_phase(lp.RECOVERY, "Restoring from the last clean copy.")
        self.say("--- recovery: restore the pinned clean snapshot ---")
        result = self.vault.restore(snapshot_id)
        self.say(f"restored {result.snapshot_id} to {result.restored_to}")
        for check in result.checks:
            self.say(f"  [{'pass' if check.passed else 'FAIL'}] {check.statement}")
        self.say(f"cards recovered: {result.records_verified:,} / "
                 f"{result.records_expected:,}")
        self.report["restore"] = {
            "snapshot_id": result.snapshot_id,
            "ok": result.ok,
            "records_verified": result.records_verified,
            "records_expected": result.records_expected,
            "checks": [{"statement": c.statement, "passed": c.passed}
                       for c in result.checks],
            "restored_to": result.restored_to,
            "by": "autopilot",
        }
        self.say(f"lock released after the restore: {self.judge.undo()}")
        restore_ok = (result.ok and result.records_verified
                      == result.records_expected
                      == self.config.district.ration_cards)
        self._finish_proof(restore_ok=restore_ok)

    def _finish_proof(self, *, restore_ok: bool) -> None:
        if not self.autopilot:
            return
        attack = self.report.get("attack", {})
        liveness = self.report.get("watcher_liveness", {})
        quiet_incidents = sum(1 for v in self.report["verdicts"]
                              if v["level"] == INCIDENT)
        checks = {
            "no_incident_on_learning_or_guard_days": quiet_incidents == 0,
            "attack_judged_incident": attack.get("level") == INCIDENT,
            "damaged_snapshot_suspect": attack.get("snapshot_health") == SUSPECT,
            "clean_pin_held": bool(attack.get("clean_pin_held")),
            "watcher_stayed_alive": bool(
                liveness.get("after_attack", {}).get("alive")),
            "restore_ok_5000_of_5000": restore_ok,
        }
        passed = all(checks.values())
        self.report["checks"] = checks
        self.report["passed"] = passed
        self.proof = {"passed": passed, "checks": checks}
        self.say("--- proof " + ("PASSED" if passed else "FAILED") + " ---")
        for name, ok in checks.items():
            self.say(f"  [{'pass' if ok else 'FAIL'}] {name}")
        self._write_report()
        self._set_phase(lp.COMPLETE if passed else lp.FAILED,
                        "The full demonstration finished." if passed
                        else "The full demonstration did not pass.")

    def _release_after_restore(self, restored: dict) -> None:
        self.report["restore"] = {**restored, "by": "supervisor"}
        self.say(f"restore reported by the console: {restored.get('snapshot_id')}, "
                 f"{restored.get('records_verified')} / "
                 f"{restored.get('records_expected')} cards verified")
        self.say(f"lock released after the restore: {self.judge.undo()}")
        self._write_report()
        self._set_phase(lp.RECOVERED,
                        "The records were restored and checked.")

    # --- what the console reads ---------------------------------------------

    def _status(self) -> dict:
        habit = self.habit
        cards = {}
        counts = {}
        if habit is not None:
            try:
                cards = habit.cards()
                counts = {job: habit.run_count(job) for job in self.jobs}
            except Exception:
                cards, counts = {}, {}
        jobs = []
        for name, state in self.jobs.items():
            jobs.append({
                "job": name,
                "runs_seen": counts.get(name, 0),
                "has_card": name in cards,
                "card": {feature: list(values)
                         for feature, values in cards.get(name, {}).items()},
                "last_day": state.last_day,
                "last_sim_start": state.last_sim_start,
                "last_level": state.last_level,
                "last_reasons": list(state.last_reasons[:2]),
            })
        vault_info: dict = {"snapshots": 0}
        vault = self.vault
        if vault is not None:
            try:
                snaps = vault.snapshots()
                clean = [s for s in snaps if s.is_clean_point]
                vault_info = {
                    "snapshots": len(snaps),
                    "latest_health": snaps[-1].health if snaps else None,
                    "clean_point": clean[-1].snapshot_id if clean else None,
                    "clean_point_at": _iso(clean[-1].taken_at) if clean else None,
                    "protect_mode": bool(vault.protect_mode),
                    "verdict": vault.vault_verdict,
                    "suspect": any(s.health == SUSPECT for s in snaps),
                    "all_clean": all(s.health == CLEAN for s in snaps),
                }
            except Exception:
                pass
        with self._state_lock:
            day = {"number": self.day_no, "done": self.days_done,
                   "learning_days": self.config.clock.learning_days,
                   "guard_days": self.config.clock.guard_days,
                   "seconds": self.config.clock.simulated_day_seconds,
                   "surge_tonight": self.surge_tonight,
                   "surge_why": self.surge_why}
        return {
            "pid": os.getpid(),
            "mode": "autopilot" if self.autopilot else "manual",
            "phase": self.phase,
            "note": self.note,
            "day": day,
            "running_job": self._office.running,
            "harvest_surge_requested": bool(self._control.get("harvest_surge")),
            "jobs": jobs,
            "min_runs_for_card": self.config.habit.min_runs_before_scoring,
            "checks": {"nights_checked": self.nights_checked,
                       "odd": self.odd_count,
                       "incidents": self.incident_count,
                       "recent": list(self.recent)},
            "vault": vault_info,
            "attack": {k: v for k, v in self.attack.items() if k != "id"},
            "attack_readiness": self.attack_readiness(),
            "lock_held": self.phase in lp.LOCKED_PHASES,
            "restore": self.report.get("restore"),
            "proof": self.proof,
            "error": self.error,
        }

    def _write_status(self, force: bool = False) -> None:
        status = self._status()
        body = json.dumps(status, sort_keys=True, default=str)
        if body == self._last_written and not force:
            return
        self._last_written = body
        self._version += 1
        status["version"] = self._version
        status["updated_at"] = _iso(_utcnow())
        lp.write_json(self.paths.status, status)

    def _write_report(self) -> None:
        lp.write_json(self.paths.report, self.report)


def _pid_alive(pid: int) -> bool:
    import psutil

    try:
        return psutil.pid_exists(pid)
    except Exception:
        return True


def main(config: Config, out_dir: Path, *, autopilot: bool = False,
         variant: str | None = None, parent_pid: int | None = None) -> int:
    """Entrypoint wrapper: run one live session, return an exit code."""
    variant = variant or (config.console.full_demo_variant if autopilot
                          else config.console.attack_variants[0])
    engine = LiveEngine(config, lp.SessionPaths(Path(out_dir).resolve()),
                        autopilot=autopilot, variant=variant,
                        parent_pid=parent_pid)
    return engine.run()


__all__ = ["LiveEngine", "main"]
