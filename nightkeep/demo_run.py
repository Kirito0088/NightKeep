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
from collections.abc import Callable
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
    HEARTBEAT_FILENAME,
    INCIDENT,
    NORMAL,
    RENAMED,
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


def _recovery_killer_command_args(
    recovery_commands: tuple[str, ...],
) -> tuple[str, ...]:
    """The simulator argv carrying the configured recovery commands.

    One repeated ``--command`` per configured command, exactly what the
    simulator's CLI expects. An empty configuration is refused outright:
    with no commands the simulator would build a broken echo shell
    (``sh -c "; sleep ..."`` is a syntax error), and the recovery-killer
    variant would silently exercise no S5 evidence at all.
    """
    if not recovery_commands:
        raise ValueError(
            "the recovery-killer variant needs at least one configured "
            "recovery command (judge.recovery_commands in the config); "
            "got none"
        )
    return tuple(
        arg
        for command in recovery_commands
        for arg in ("--command", command)
    )


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


def _is_judgeable(event: Event) -> bool:
    """Events the Judge may see in a live window.

    The watcher already filters its heartbeat (and the atomic temp sibling),
    its own log, and the _truth folder at record time, so these never reach
    the log. This is the demo's defensive second net: a window fed to the
    Judge must never carry liveness or bookkeeping noise, even if the
    watcher's filter ever changes.
    """
    name = event.path.rsplit("/", 1)[-1]
    if name == "watcher.jsonl":
        return False
    if name == HEARTBEAT_FILENAME or name.startswith(HEARTBEAT_FILENAME + "."):
        return False
    if "_truth" in event.path.split("/"):
        return False
    return True


class _EventCursor:
    """Exactly-once consumption of the watcher's append-only event log.

    The log is append-only and never rewritten, so a count of consumed
    events is a stable cursor. Each drain returns only the events appended
    since the previous drain, oldest first. Nothing is ever yielded twice,
    which is what lets the live loop judge cumulative windows without
    double-counting.
    """

    def __init__(self, event_log: EventLog) -> None:
        self._event_log = event_log
        self._consumed = 0

    def rewind_to_end(self) -> None:
        """Skip everything logged so far.

        Called at attack start so pre-attack day-job events are never part
        of a live window.
        """
        self._consumed = len(self._event_log.read_all())

    def drain(self) -> list[Event]:
        """Events appended since the last drain, oldest first."""
        events = self._event_log.read_all()
        new = list(events[self._consumed :])
        self._consumed = len(events)
        return new


def _await_silence(vault: Vault, timeout_seconds: float) -> WatcherLiveness:
    """Wait until the Vault's own clock calls the watcher silent.

    Real timing, not a claim: this returns only after the Vault's
    background liveness monitor has recorded the silence and flipped
    the Vault into Protect mode (protect_mode is True). The fresh
    direct check_watcher_liveness() reads are kept as early
    information, but they are a pure read -- they never update the
    Vault's recorded verdict -- so the loop does not finish on them
    alone. If the timeout expires first, the returned liveness says
    so and the caller proceeds without the S6 state recorded.
    """
    deadline = time.monotonic() + timeout_seconds
    liveness = vault.check_watcher_liveness()
    while (
        time.monotonic() < deadline
        and (liveness.alive or not vault.protect_mode)
    ):
        time.sleep(0.5)
        liveness = vault.check_watcher_liveness()
    return liveness


# --- live attack orchestration ---------------------------------------------

# How often the live loop drains the event log while the simulator runs.
_LIVE_POLL_SECONDS = 0.5
# How long to watch for post-containment writes when proving the attack
# stopped. Long enough to exceed the watcher's poll interval, short enough
# to keep the demo moving.
_CONTAINMENT_PROOF_WAIT_SECONDS = 3.0


def _kill_process_tree(pid: int) -> list[int]:
    """SIGKILL a process and all its descendants. Returns the PIDs signaled.

    A suspended (SIGSTOP) process still dies to SIGKILL, which is what lets
    cleanup end an attack the Judge paused mid-burst. Children are killed
    too: the recovery-killer's lingering echo shell must not survive its
    parent.
    """
    import psutil

    try:
        root = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return []
    targets = [root] + root.children(recursive=True)
    signaled = []
    for target in targets:
        try:
            target.kill()
            signaled.append(target.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return signaled


def _process_is_stopped(pid: int) -> bool | None:
    """True if the process exists and is suspended, False if it is running,
    None if it is gone."""
    import psutil

    try:
        status = psutil.Process(pid).status()
    except psutil.NoSuchProcess:
        return None
    return status == psutil.STATUS_STOPPED


# The simulator's documented boundary (nightkeep/simulator/__init__.py):
# it never enters these top-level folders, nor any _truth folder. The
# containment proof must cover exactly the same surface the simulator
# could have written -- share/ alone is not enough, because the blast
# radius is the whole demo root. Mirrored here rather than imported so
# the simulator's public surface does not grow; a regression test pins
# the two together.
_PROOF_OFF_LIMIT_TOP_LEVELS = frozenset({"logs", "data", ".nightkeep-sim"})
_PROOF_TRUTH_FOLDER = "_truth"


def _eligible_files_modified_after(root: Path, since_ts: float) -> list[str]:
    """Simulator-eligible files under the demo root written after since_ts.

    The actual attack surface, not just share/: the simulator's _targets()
    walks the whole demo root minus its off-limits folders. mtime is write
    time, not the watcher's observation time, so a late-delivered event for
    a pre-containment write cannot false-positive here. The watcher's own
    bookkeeping is excluded: the liveness heartbeat (and its atomic temp
    sibling) and the append-only event log keep being written by design,
    and they are not the attack.
    """
    modified = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if relative.parts[0] in _PROOF_OFF_LIMIT_TOP_LEVELS:
            continue
        if _PROOF_TRUTH_FOLDER in relative.parts:
            continue
        name = path.name
        if name == HEARTBEAT_FILENAME or name.startswith(
            HEARTBEAT_FILENAME + "."
        ):
            continue
        if name == "watcher.jsonl":
            continue
        try:
            if path.stat().st_mtime > since_ts:
                modified.append(str(path))
        except OSError:
            continue
    return modified


def _canonical_affected_path(event: Event) -> str:
    """One identity per physical file, for the affected-file count.

    The simulator encrypts a file in place (MODIFIED on its original path)
    and then renames it (RENAMED to the .locked name): two events, one
    file. The rename's original/source path is the identity. Report-only;
    the Judge's detection never sees this.
    """
    if event.kind == RENAMED and event.old_path:
        return event.old_path
    return event.path


def _judge_attack_live(
    *,
    simulator_argv: list[str],
    event_log: EventLog,
    judge: Judge,
    district_dir: Path,
    variant: str,
    day_no: int,
    settle_seconds: float,
    say: Callable[[str], None],
) -> dict:
    """Run the simulator live and judge cumulative windows until INCIDENT.

    The simulator is launched with Popen, not run: the Judge sees each
    window while the attack is still in progress. Windows are cumulative
    from attack start, so a burst spread over several drains (S4) is still
    caught. Judging stops at the first INCIDENT, so suspension, the
    read-only lock and the pop-up happen exactly once. Every window is
    judged with an explicit event slice, which never updates the baseline.

    Settle is applied once: after the simulator exits, one wait lets the
    watcher's tail arrive, then a final drain and a final verdict. A very
    fast attack that finishes before its first events are judged is still
    caught honestly by that final drain.

    Detection latency is measured to the INCIDENT verdict's own decision
    timestamp, stamped inside the Judge before the (on Windows, blocking)
    server pop-up: popup dismissal can never inflate it. The containment
    proof watches the simulator's whole eligible attack surface -- the
    demo root minus the simulator's off-limits folders -- for writes after
    the verdict's containment-completed timestamp.

    Returns behavioral evidence for the report: real PIDs, timestamps and
    counts, nothing inferred.
    """
    import psutil

    cursor = _EventCursor(event_log)
    cursor.rewind_to_end()

    attack_start = _utcnow()
    proc = subprocess.Popen(simulator_argv)
    sim_pid = proc.pid
    say(f"simulator launched live: pid {sim_pid}")

    attack_run = JobRun(
        job="simulator",
        identity=f"simulator|{variant}|external-process",
        started_at=attack_start,
        finished_at=attack_start,
        events=(),
        sim_started_at=None,
        day_no=day_no,
    )

    prefix: list[Event] = []
    verdicts_judged = 0
    incident_verdict = None
    first_event_at: datetime | None = None
    sim_alive_before_containment: bool | None = None

    def drain_new() -> bool:
        nonlocal first_event_at
        added = False
        for event in cursor.drain():
            if event.at < attack_start or not _is_judgeable(event):
                continue
            prefix.append(event)
            added = True
        if added and first_event_at is None:
            first_event_at = prefix[0].at
        return added

    def judge_prefix():
        nonlocal verdicts_judged
        verdicts_judged += 1
        return judge.verdict(attack_run, events=list(prefix))

    evidence: dict = {
        "variant": variant,
        "simulator_pid": sim_pid,
        "attack_start": attack_start.isoformat(),
        "attack_end": None,
        "verdicts_judged": 0,
        "events_observed": 0,
        "level": "NORMAL",
        "signals": [],
        "reasons": [],
        "actions": [],
    }
    try:
        while True:
            if drain_new():
                # The simulator's state right now is the "immediately before
                # containment" evidence, if this verdict is the INCIDENT one.
                alive_now = proc.poll() is None
                verdict = judge_prefix()
                say(f"live window: {len(prefix)} events -> {verdict.level}")
                if verdict.level == INCIDENT:
                    incident_verdict = verdict
                    sim_alive_before_containment = alive_now
                    say(
                        f"INCIDENT with the simulator alive: {alive_now} "
                        f"(pid {sim_pid})"
                    )
                    break
            if proc.poll() is not None:
                # The simulator finished. One settle wait for the watcher's
                # tail, a final drain, and a final verdict on the whole
                # prefix -- this is what catches a very fast attack honestly.
                time.sleep(settle_seconds)
                drain_new()
                verdict = judge_prefix()
                say(f"final window: {len(prefix)} events -> {verdict.level}")
                if verdict.level == INCIDENT and incident_verdict is None:
                    incident_verdict = verdict
                    sim_alive_before_containment = False
                break
            time.sleep(_LIVE_POLL_SECONDS)

        attack_end = _utcnow()

        if incident_verdict is not None:
            # The verdict carries its own decision and containment
            # timestamps, stamped inside the Judge before the server pop-up.
            # Using them -- not a clock read after the verdict returns --
            # keeps popup dismissal out of the latency, and gives the
            # containment proof a cutoff no post-verdict step can move.
            incident_decision_at = incident_verdict.decided_at
            containment_completed_at = incident_verdict.contained_at
            assert incident_decision_at is not None
            assert containment_completed_at is not None
            assert first_event_at is not None
            latency = (
                incident_decision_at - first_event_at
            ).total_seconds()
            sim_stopped = _process_is_stopped(sim_pid)
            say(
                f"containment: simulator pid {sim_pid} "
                f"{'suspended' if sim_stopped else 'NOT suspended'}; "
                f"latency {latency:.1f}s; "
                f"{len({_canonical_affected_path(e) for e in prefix})} "
                "files in the window"
            )
            # Prove the attack stopped: after containment completed, no
            # simulator-eligible file may be written anywhere under the demo
            # root. mtime is write time, not watch time, so a late-delivered
            # event for a pre-containment write cannot false-positive.
            time.sleep(_CONTAINMENT_PROOF_WAIT_SECONDS)
            written_after = _eligible_files_modified_after(
                district_dir, containment_completed_at.timestamp()
            )
            further_stopped = not written_after
            if not further_stopped:
                say(f"attack continued after containment: {written_after}")

            evidence.update(
                {
                    "level": incident_verdict.level,
                    "signals": [s.code for s in incident_verdict.signals],
                    "reasons": list(incident_verdict.reasons),
                    "actions": list(incident_verdict.actions),
                    "first_event_at": first_event_at.isoformat(),
                    "incident_decision_at": incident_decision_at.isoformat(),
                    "containment_completed_at": (
                        containment_completed_at.isoformat()
                    ),
                    "detection_latency_seconds": latency,
                    "affected_files_at_incident": len(
                        {_canonical_affected_path(e) for e in prefix}
                    ),
                    "simulator_alive_before_containment": (
                        sim_alive_before_containment
                    ),
                    "simulator_stopped_after_containment": sim_stopped,
                    "further_attack_stopped": further_stopped,
                }
            )
        else:
            # No INCIDENT: the watcher-killer (or an unexpected quiet attack).
            # The last verdict stands as the post-mortem.
            evidence["simulator_alive_before_containment"] = False
        attack_end = _utcnow()
        evidence["attack_end"] = attack_end.isoformat()
        evidence["verdicts_judged"] = verdicts_judged
        evidence["events_observed"] = len(prefix)
    finally:
        # The simulator must not survive the demo, and the read-only
        # lock must not survive it either, even if judging raised
        # halfway through the loop above.
        # --- cleanup: the simulator must not survive the demo ----------------
        killed = _kill_process_tree(sim_pid)
        # Reap the direct child so it never becomes a zombie.
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        undone = judge.undo()
        say(f"cleanup: signaled pids {killed}; judge undo: {undone}")
        try:
            still_there = psutil.pid_exists(sim_pid)
        except Exception:
            still_there = False
        evidence["cleanup_killed_pids"] = killed
        evidence["cleanup_undo"] = undone
        evidence["simulator_process_gone"] = not still_there
        evidence["cleanup_at"] = _utcnow().isoformat()
        # Writability is restored by judge.undo(); prove it on one file.
        probe = district_dir / "share" / ".nightkeep-write-probe"
        try:
            probe.write_text("ok")
            probe.unlink()
            writable = True
        except OSError:
            writable = False
        evidence["share_writable_after_cleanup"] = writable
        say(f"cleanup: simulator gone: {not still_there}; "
            f"share writable: {writable}")

    return evidence


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
        if variant == "recovery-killer":
            # The recovery commands live in config; the demo path must pass
            # them through as repeated --command arguments, or the variant
            # would run with an empty command list and produce no S5
            # evidence. _recovery_killer_command_args refuses that
            # silently-broken shape outright.
            simulator_extra_args = (
                *simulator_extra_args,
                *_recovery_killer_command_args(
                    tuple(judge_cfg.recovery_commands)),
            )
        # Live, not blocking: the simulator runs under Popen while the
        # Judge judges cumulative windows, stopping at the first INCIDENT.
        # Settle is applied once, inside _judge_attack_live.
        attack_evidence = _judge_attack_live(
            simulator_argv=[
                sys.executable, "-m", "nightkeep.simulator",
                "--variant", variant,
                "--root", str(district_dir),
                "--key", sim_cfg.key,
                "--locked-extension", sim_cfg.locked_extension,
                "--ransom-note-name", sim_cfg.ransom_note_name,
                "--delay", str(sim_cfg.delay_between_files_seconds),
                *simulator_extra_args,
            ],
            event_log=event_log,
            judge=judge,
            district_dir=district_dir,
            variant=variant,
            day_no=first_guard_day + clock.guard_days,
            settle_seconds=watcher_cfg.settle_seconds,
            say=say,
        )
        say(f"attack verdict: {attack_evidence['level']}")
        for reason in attack_evidence["reasons"]:
            say(f"  why: {reason}")
        for action in attack_evidence["actions"]:
            say(f"  did: {action}")
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
        liveness_after = vault.check_watcher_liveness()
        say(f"watcher liveness after attack: "
            f"{'alive' if liveness_after.alive else 'SILENT'} "
            f"({liveness_after.reason})")
        report["attack"] = attack_evidence
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
