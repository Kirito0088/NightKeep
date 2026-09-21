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
import time
import uuid
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
    root = simulator.DEMO_DIR / ".sim-tests" / uuid.uuid4().hex
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
        trap_files=(TRAP,),
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
        share_dir=root / "share",
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
    assert evidence["files_at_incident"] >= 1, evidence
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
    try:
        evidence = _run_live(
            district,
            judge,
            "recovery-killer",
            delay="0",
            extra=_recovery_killer_command_args(COMMANDS),
        )
        _assert_contained(evidence, alive_before=True, stopped_after=True)
        assert "S5" in evidence["signals"], evidence["signals"]
    finally:
        judge.undo()


def test_watcher_killer_reaches_no_incident(district):
    """The killer touches no files: the Judge rightly sees NORMAL. (The
    Vault's S6 witness is a separate story, not exercised here.)"""
    judge = _make_judge(district)
    try:
        evidence = _run_live(district, judge, "watcher-killer", delay="0")
        assert evidence["level"] == "NORMAL", evidence
        assert evidence["simulator_alive_before_containment"] is False
        assert evidence["simulator_process_gone"] is True
    finally:
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
        exports = district / "share" / "exports"
        for locked in exports.glob("*.locked"):
            locked.unlink()
        for index in range(20):
            (exports / f"day_end_{index:02d}.csv").write_text(
                "transaction_id,card_no,quantity_kg\n"
                + "".join(
                    f"{index},{1000 + row},5\n" for row in range(200)
                ),
                encoding="utf-8",
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
