"""End-to-end: live ransomware detection, containment, and cleanup.

These tests run the real simulator as a subprocess under the real watcher
agent, judged live by a real Judge via _judge_attack_live. They assert
behavioral evidence only: real PIDs, real suspension, measured latency,
files affected, and proof the attack stopped. Nothing is inferred from
action strings alone.
"""

from __future__ import annotations

import subprocess
import sys
import sqlite3
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

import psutil
import pytest

from nightkeep import simulator
from nightkeep.demo_run import (
    _judge_attack_live,
    _recovery_killer_command_args,
)
from nightkeep.habit import open_habit
from nightkeep.judge import Judge
from nightkeep.types import CLEAN, NORMAL, SUSPICIOUS
from nightkeep.vault import Vault
from nightkeep.watcher import event_log_for
from nightkeep.watcher.__main__ import heartbeat_path

KEY = "nightkeep-demo-key-not-a-secret"
COMMANDS = (
    "vssadmin delete shadows",
    "wbadmin delete catalog",
)
NOTE_NAME = "HOW_TO_GET_YOUR_FILES_BACK.txt"
TRAP = "share/exports/aaa_trap.csv"


def _scratch_district(file_count: int = 20) -> Path:
    root = (simulator.DEMO_DIR / ".sim-tests" / uuid.uuid4().hex).resolve()
    exports = root / "share" / "exports"
    exports.mkdir(parents=True)
    for index in range(file_count):
        (exports / f"day_end_{index:02d}.csv").write_text(
            "transaction_id,card_no,quantity_kg\n"
            + "".join(
                f"{index},{1000 + row},5\n" for row in range(200)
            ),
            encoding="utf-8",
        )
    # One eligible file outside share/: the simulator's blast radius is
    # the whole demo root, and the containment proof must cover it, not
    # just share/.
    reports = root / "reports"
    reports.mkdir(parents=True)
    (reports / "monthly_summary.csv").write_text(
        "month,total_kg\n2026-09,12345\n", encoding="utf-8",
    )
    # The Vault's S7 health check expects a database backup with a cards
    # table; without one every non-baseline pull is SUSPECT for data
    # reasons, which would muddy the watcher-killer's Vault story.
    backups = root / "share" / "backups"
    backups.mkdir(parents=True)
    conn = sqlite3.connect(backups / "district_backup.db")
    try:
        conn.execute(
            "CREATE TABLE cards (id INTEGER PRIMARY KEY, name TEXT)"
        )
        conn.executemany(
            "INSERT INTO cards (name) VALUES (?)",
            [(f"card {n}",) for n in range(120)],
        )
        conn.commit()
    finally:
        conn.close()
    return root


def _start_agent(root: Path) -> subprocess.Popen:
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "nightkeep.watcher", "--run",
            "--root", str(root),
            "--interval", "0.5",
            "--poll-seconds", "0.2",
            "--settle-seconds", "0.2",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    beat = heartbeat_path(root)
    deadline = time.monotonic() + 30
    while not beat.exists():
        assert proc.poll() is None, "the watcher agent died on startup"
        assert time.monotonic() < deadline, "no heartbeat from the agent"
        time.sleep(0.05)
    return proc


def _wait_for_log_quiet(root: Path, timeout: float = 15.0) -> None:
    """Wait until the watcher has logged everything pending (e.g. the trap
    plant) and the log goes quiet. Prevents setup events from leaking into
    the attack window."""
    log = event_log_for(root)
    quiet_for = 0.0
    last_count = -1
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        count = len(log.read_all())
        if count == last_count:
            quiet_for += 0.1
            if quiet_for >= 0.6:
                return
        else:
            quiet_for = 0.0
            last_count = count
        time.sleep(0.1)
    raise AssertionError("the event log never went quiet")


def _stop_agent(proc: subprocess.Popen) -> None:
    try:
        children = psutil.Process(proc.pid).children(recursive=True)
    except psutil.NoSuchProcess:
        children = []
    for child in children:
        try:
            child.kill()
        except psutil.NoSuchProcess:
            pass
    try:
        proc.terminate()
        proc.wait(timeout=10)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            proc.kill()
        except ProcessLookupError:
            pass


def _make_judge(root: Path) -> Judge:
    judge = Judge(
        root=root,
        habit=open_habit(root, 3.0, 5, 0.1),
        odd_score=0.5,
        rename_burst=10,
        entropy_jump=1.5,
        entropy_floor=7.0,
        recovery_commands=COMMANDS,
        canary_files=(TRAP,),
        server_alerts=False,
    )
    judge.plant_traps()
    # Let the agent log the trap plant, so the attack window starts clean.
    _wait_for_log_quiet(root)
    return judge


def _simulator_argv(
    root: Path, variant: str, delay: str, extra: tuple[str, ...] = ()
) -> list[str]:
    return [
        sys.executable, "-m", "nightkeep.simulator",
        "--variant", variant,
        "--root", str(root),
        "--key", KEY,
        "--locked-extension", ".locked",
        "--ransom-note-name", NOTE_NAME,
        "--delay", delay,
        *extra,
    ]


def _run_live(
    root: Path,
    judge: Judge,
    variant: str,
    delay: str,
    extra: tuple[str, ...] = (),
) -> dict:
    return _judge_attack_live(
        simulator_argv=_simulator_argv(root, variant, delay, extra),
        event_log=event_log_for(root),
        judge=judge,
        district_dir=root,
        variant=variant,
        day_no=4,
        settle_seconds=2.0,
        say=lambda message: None,
    )


@pytest.fixture
def district():
    root = _scratch_district()
    agent = _start_agent(root)
    yield root
    _stop_agent(agent)


def _assert_contained(evidence: dict, *, alive_before: bool | None = None,
                      stopped_after: bool | None = None):
    """The behavioral proof, shared by the attack scenarios."""
    assert evidence["level"] == "INCIDENT", evidence
    assert "S2" in evidence["signals"] or "S5" in evidence["signals"], (
        evidence["signals"]
    )
    if alive_before is not None:
        assert (
            evidence["simulator_alive_before_containment"] is alive_before
        ), evidence
    if stopped_after is not None:
        assert (
            evidence["simulator_stopped_after_containment"] is stopped_after
        ), evidence
    else:
        # Suspended (True) or already gone (None) are both contained; still
        # running (False) is not.
        assert evidence["simulator_stopped_after_containment"] is not False, (
            evidence
        )
    # Nothing was written after the INCIDENT timestamp.
    assert evidence["further_attack_stopped"] is True, evidence
    # Measured, not inferred.
    assert evidence["detection_latency_seconds"] > 0, evidence
    assert evidence["affected_files_at_incident"] >= 1, evidence
    # Explicit, ordered timestamps: the decision and containment stamps
    # come from the verdict itself (before the pop-up), and the latency
    # is exactly decision minus first event.
    first = datetime.fromisoformat(evidence["first_event_at"])
    decided = datetime.fromisoformat(evidence["incident_decision_at"])
    contained = datetime.fromisoformat(
        evidence["containment_completed_at"]
    )
    cleaned = datetime.fromisoformat(evidence["cleanup_at"])
    assert first <= decided <= contained <= cleaned, evidence
    assert evidence["detection_latency_seconds"] == pytest.approx(
        (decided - first).total_seconds()
    ), evidence
    # Cleanup: the tree is gone and the share is writable again.
    assert evidence["simulator_process_gone"] is True, evidence
    assert evidence["share_writable_after_cleanup"] is True, evidence
    # The verdict was reached live, not only post-mortem.
    assert evidence["verdicts_judged"] >= 1, evidence


def test_slow_attack_caught_while_still_running(district):
    """The live proof: a slow attack is suspended mid-burst."""
    judge = _make_judge(district)
    try:
        evidence = _run_live(district, judge, "fast", delay="0.4")
        _assert_contained(evidence, alive_before=True, stopped_after=True)
        # A slow attack is caught quickly, long before it finishes.
        assert evidence["detection_latency_seconds"] < 20, evidence
    finally:
        judge.undo()


def test_fast_attack_reaches_incident(district):
    judge = _make_judge(district)
    try:
        evidence = _run_live(district, judge, "fast", delay="0")
        _assert_contained(evidence)
    finally:
        judge.undo()


def test_very_fast_attack_caught_by_the_final_drain(district):
    """Six files, no delay: the simulator can finish before the first live
    window is judged. The final drain still catches it, honestly."""
    root = _scratch_district(file_count=6)
    agent = _start_agent(root)
    judge = _make_judge(root)
    try:
        evidence = _run_live(root, judge, "fast", delay="0")
        _assert_contained(evidence)
    finally:
        judge.undo()
        _stop_agent(agent)


def test_recovery_killer_fires_s5_and_reaches_incident(district):
    judge = _make_judge(district)
    # While the attack runs, no dangerous binary may ever execute: the
    # recovery-killer shell must only echo the command text.
    stop = threading.Event()
    seen: list[str] = []

    def _scan() -> None:
        while not stop.is_set():
            for proc in psutil.process_iter(["name"]):
                name = (proc.info.get("name") or "").lower()
                base = name[:-4] if name.endswith(".exe") else name
                if base in {"vssadmin", "wbadmin", "bcdedit"}:
                    seen.append(name)
            time.sleep(0.2)

    scanner = threading.Thread(target=_scan, daemon=True)
    try:
        scanner.start()
        evidence = _run_live(
            district,
            judge,
            "recovery-killer",
            delay="0",
            extra=(
                # Deterministic S5: the echo shell is up before the first
                # live verdict, so no scheduler timing is involved.
                "--shell-first",
                *_recovery_killer_command_args(COMMANDS),
            ),
        )
        _assert_contained(evidence, alive_before=True, stopped_after=True)
        assert "S5" in evidence["signals"], evidence["signals"]
    finally:
        stop.set()
        scanner.join(timeout=10)
        judge.undo()
    assert seen == [], f"a real recovery command executed: {seen}"


def test_incident_raises_exactly_one_popup_with_honest_text(
    district, monkeypatch
):
    """The production wiring (server_alerts=True) invokes the display
    boundary exactly once per INCIDENT, with text that matches the Judge's
    actual actions. Only the display itself is mocked; everything else --
    the simulator, the watcher, the Judge, the verdict -- is real.

    Honest limit: this proves the Judge calls the popup exactly once with
    honest text. Whether the native Windows dialog actually renders is
    not verifiable on this Linux machine and is not claimed here.
    """
    from nightkeep import server_alert

    shown: list = []

    def _spy(alert) -> bool:
        shown.append(alert)
        return True  # the platform displayed it; nothing real is drawn

    monkeypatch.setattr(server_alert, "_platform_show", _spy)

    judge = Judge(
        root=district,
        habit=open_habit(district, 3.0, 5, 0.1),
        odd_score=0.5,
        rename_burst=10,
        entropy_jump=1.5,
        entropy_floor=7.0,
        recovery_commands=COMMANDS,
        canary_files=(TRAP,),
        server_alerts=True,
    )
    judge.plant_traps()
    _wait_for_log_quiet(district)
    try:
        evidence = _run_live(district, judge, "fast", delay="0")
        _assert_contained(evidence)
    finally:
        judge.undo()

    # Exactly one popup, on the one INCIDENT.
    assert len(shown) == 1, f"expected one popup, saw {len(shown)}"
    alert = shown[0]
    actions = evidence["actions"]
    # The popup text agrees with the Judge's actual actions: it lists
    # what was really done, then the standing guidance.
    assert list(alert.details[: len(actions)]) == list(actions), (
        alert.details
    )
    paused = any(action.startswith("paused") for action in actions)
    assert ("It was paused." in alert.headline) == paused, alert.headline
    # No Judge call after the INCIDENT: the history holds exactly the
    # verdicts the live loop judged, and the last one is the INCIDENT.
    history = judge.history()
    assert len(history) == evidence["verdicts_judged"], (
        len(history),
        evidence["verdicts_judged"],
    )
    assert history[-1][1].level == "INCIDENT"
    assert history[-1][1].level == evidence["level"]


def test_watcher_killer_reaches_no_incident(district, tmp_path):
    """The killer touches no files, so the Judge rightly sees NORMAL --
    while the Vault independently witnesses the silenced heartbeat (S6),
    records SUSPICIOUS, and enters Protect mode with the clean pin held.
    Two witnesses, two stories; neither borrows the other's conclusion.
    """
    judge = _make_judge(district)
    vault = Vault(
        tmp_path / "vault",
        district / "share",
        suspect_entropy=7.0,
        suspect_changed_fraction=0.5,
        suspect_record_drop_fraction=0.02,
        restore_folder_name="restored",
        watcher_silence_seconds=1.0,
        liveness_check_interval_seconds=0.2,
    )
    baseline = vault.pull()
    assert baseline.health == CLEAN
    states: list = []
    vault.start_liveness_monitor(on_state_change=states.append)
    try:
        # The monitor must have seen the healthy watcher first: a SILENT
        # reading before the first beat is startup, not S6 evidence.
        deadline = time.monotonic() + 15
        while not (
            vault.last_liveness is not None and vault.last_liveness.alive
        ):
            assert time.monotonic() < deadline, (
                "the vault monitor never saw the healthy agent"
            )
            time.sleep(0.1)
        assert vault.vault_verdict == NORMAL

        evidence = _run_live(district, judge, "watcher-killer", delay="0")
        assert evidence["level"] == "NORMAL", evidence
        assert evidence["simulator_alive_before_containment"] is False
        assert evidence["simulator_process_gone"] is True

        # The Vault detects the silence by its own clock: S6 ->
        # SUSPICIOUS + Protect mode, exactly one state change.
        deadline = time.monotonic() + 20
        while not (
            vault.vault_verdict == SUSPICIOUS and vault.protect_mode
        ):
            assert time.monotonic() < deadline, (
                "the vault never raised S6 for the killed watcher"
            )
            time.sleep(0.1)
        assert vault.last_liveness is not None
        assert vault.last_liveness.alive is False
        assert "S6" in vault.last_liveness.reason
        assert len(states) == 1
        assert states[0].verdict == SUSPICIOUS
        assert states[0].previous_verdict == NORMAL
        assert states[0].protect_mode is True

        # Protect mode holds the clean point: an unchanged pull stays
        # CLEAN data-wise (S6 says nothing about the data) but does not
        # advance the pin past the pre-S6 snapshot.
        again = vault.pull()
        assert again.health == CLEAN
        assert again.is_clean_point is False
        pinned = [s for s in vault.snapshots() if s.is_clean_point]
        assert [s.snapshot_id for s in pinned] == [baseline.snapshot_id]
    finally:
        vault.stop_liveness_monitor()
        judge.undo()


def test_back_to_back_runs_are_clean(district):
    """Two attacks in a row: the second is judged on its own evidence,
    with no stale actions or suspended PIDs leaking from the first."""
    judge = _make_judge(district)
    try:
        first = _run_live(district, judge, "fast", delay="0")
        _assert_contained(first)

        # Restore the district to a clean state, as the Vault restore
        # would: locked files go, originals and the trap come back.
        for locked in district.rglob("*.locked"):
            locked.unlink()
        for note in district.rglob(NOTE_NAME):
            note.unlink()
        exports = district / "share" / "exports"
        for index in range(20):
            (exports / f"day_end_{index:02d}.csv").write_text(
                "transaction_id,card_no,quantity_kg\n"
                + "".join(
                    f"{index},{1000 + row},5\n" for row in range(200)
                ),
                encoding="utf-8",
            )
        reports = district / "reports"
        (reports / "monthly_summary.csv").write_text(
            "month,total_kg\n2026-09,12345\n", encoding="utf-8",
        )
        judge.plant_traps()
        _wait_for_log_quiet(district)
        time.sleep(1.0)  # let the watcher settle on the restored files

        # The first incident's taken must be fully undone: no stale
        # descriptions or PIDs leak into the second run.
        assert judge._taken.descriptions == [], judge._taken.descriptions
        assert judge._taken.suspended == [], judge._taken.suspended

        second = _run_live(district, judge, "fast", delay="0")
        _assert_contained(second)
        # The second incident reports its own actions only: at most one
        # pause and the two folder locks, never a doubled list.
        assert len(second["actions"]) <= 3, second["actions"]
    finally:
        judge.undo()


def test_judge_exception_still_kills_simulator_and_undoes_lock(
    district, monkeypatch
):
    """If judging raises mid-attack, the simulator must not survive and the
    read-only lock must not survive either.

    Regression for the exception path in _judge_attack_live: the cleanup
    (kill the simulator tree, reap it, judge.undo()) runs in a finally, so
    a raising Judge cannot leave a suspended simulator behind or keep the
    share read-only.
    """
    judge = _make_judge(district)
    sim_pids: list[int] = []

    real_verdict = judge.verdict

    def _raising_verdict(run, events=None):
        raise RuntimeError("simulated judge failure")

    monkeypatch.setattr(judge, "verdict", _raising_verdict)

    argv = _simulator_argv(district, "fast", "0.4")
    said: list[str] = []
    with pytest.raises(RuntimeError, match="simulated judge failure"):
        _judge_attack_live(
            simulator_argv=argv,
            event_log=event_log_for(district),
            judge=judge,
            district_dir=district,
            variant="fast",
            day_no=4,
            settle_seconds=0.2,
            say=said.append,
        )
    # The simulator launch line names the real PID; it must be gone.
    launched = [m for m in said if m.startswith("simulator launched live: pid ")]
    assert launched, said
    sim_pid = int(launched[0].rsplit(" ", 1)[1])
    assert not psutil.pid_exists(sim_pid), f"simulator {sim_pid} survived"
    # The share must be writable again: no read-only lock left behind.
    probe = district / "share" / ".nightkeep-write-probe"
    probe.write_text("ok")
    probe.unlink()
    assert judge._taken.descriptions == [], judge._taken.descriptions
    assert judge._taken.suspended == [], judge._taken.suspended
