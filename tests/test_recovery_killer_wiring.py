"""Recovery-killer command wiring: config text reaches the simulator.

The audit found run_demo never passed --command, so the variant silently
exercised no S5 evidence. These tests pin the wiring at both levels: the
argv builder, and a real simulator subprocess launched with the demo's argv
plus the test-only --shell-first seam (the echo shell starts before the
encryption burst, so S5 is visible in the first verdict instead of depending
on scheduling), judged by a real Judge on events from a real watcher agent.
Real subprocesses throughout -- S5's process scan only means something
against a live shell.
"""

from __future__ import annotations

import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psutil
import pytest

from nightkeep import simulator
from nightkeep.demo_run import _recovery_killer_command_args
from nightkeep.habit import open_habit
from nightkeep.judge import Judge
from nightkeep.types import JobRun
from nightkeep.watcher import event_log_for
from nightkeep.watcher.__main__ import heartbeat_path

KEY = "nightkeep-demo-key-not-a-secret"
COMMANDS = (
    "vssadmin delete shadows",
    "wbadmin delete catalog",
    "bcdedit /set recoveryenabled no",
)
NOTE_NAME = "HOW_TO_GET_YOUR_FILES_BACK.txt"


def test_command_args_pass_each_configured_command_through():
    assert _recovery_killer_command_args(COMMANDS) == (
        "--command", "vssadmin delete shadows",
        "--command", "wbadmin delete catalog",
        "--command", "bcdedit /set recoveryenabled no",
    )


def test_command_args_reject_an_empty_configuration():
    """No silent no-op variant: empty commands would build a broken shell."""
    with pytest.raises(ValueError, match="at least one configured"):
        _recovery_killer_command_args(())


def _scratch_district() -> Path:
    """A disposable district inside the demo folder, like test_simulator."""
    root = simulator.DEMO_DIR / ".sim-tests" / uuid.uuid4().hex
    exports = root / "share" / "exports"
    exports.mkdir(parents=True)
    for index in range(6):
        (exports / f"day_end_{index}.csv").write_text(
            "transaction_id,card_no,quantity_kg\n"
            + "".join(
                f"{index},{1000 + row},5\n" for row in range(200)),
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


def _demo_simulator_argv(root: Path) -> list[str]:
    """The argv the demo builds for the recovery-killer variant, plus the
    test-only --shell-first seam: the echo shell starts before the burst so
    S5 evidence is present in the first live verdict instead of depending on
    the encryption finishing first."""
    return [
        sys.executable, "-m", "nightkeep.simulator",
        "--variant", "recovery-killer",
        "--root", str(root),
        "--key", KEY,
        "--locked-extension", ".locked",
        "--ransom-note-name", NOTE_NAME,
        "--delay", "0",
        "--shell-first",
        *_recovery_killer_command_args(COMMANDS),
    ]


def _kill_tree(proc: subprocess.Popen) -> None:
    """SIGKILL the process and any children (the lingering echo shell)."""
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
        proc.kill()
    except (ProcessLookupError, psutil.NoSuchProcess):
        pass
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass
    for child in children:
        try:
            child.wait(timeout=10)
        except (psutil.NoSuchProcess, psutil.TimeoutExpired):
            pass


def test_recovery_killer_produces_s5_through_the_demo_argv():
    """The full chain: demo argv -> echo shell -> S5 in the verdict."""
    root = _scratch_district()
    agent = _start_agent(root)
    sim = subprocess.Popen(
        _demo_simulator_argv(root),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    judge = Judge(
        root=root,
        habit=open_habit(root, 3.0, 5, 0.1),
        odd_score=0.5,
        rename_burst=10,
        entropy_jump=1.5,
        entropy_floor=7.0,
        recovery_commands=COMMANDS,
        trap_files=(),
        server_alerts=False,
    )
    try:
        # The echo shell starts before the burst (--shell-first), so S5
        # evidence is already live while the encryption runs. Waiting for
        # the ransom note still proves the burst finished, and the shell
        # lingers 600 s, so it is up by then either way.
        deadline = time.monotonic() + 60
        notes = list(root.rglob(NOTE_NAME))
        while not notes and time.monotonic() < deadline:
            time.sleep(0.2)
            notes = list(root.rglob(NOTE_NAME))
        assert notes, "the simulator never wrote its ransom note"
        assert sim.poll() is None, "the simulator exited before the shell"
        time.sleep(1.0)  # the agent's settle window

        attack_start = datetime.now(timezone.utc) - timedelta(seconds=120)
        events = tuple(
            event for event in event_log_for(root).read_all()
            if event.at >= attack_start
        )
        assert events, "the watcher logged no attack events"
        run = JobRun(
            job="simulator",
            identity="simulator|recovery-killer|external-process",
            started_at=attack_start,
            finished_at=datetime.now(timezone.utc),
            events=events,
            sim_started_at=None,
            day_no=99,
        )
        verdict = judge.verdict(run)
        codes = {signal.code for signal in verdict.signals}
        assert "S5" in codes, (
            f"no S5 from the recovery-killer; got {sorted(codes)}")
        assert any(
            "vssadmin delete shadows" in reason
            for signal in verdict.signals if signal.code == "S5"
            for reason in [signal.reason]
        ), "S5 fired but not on the configured command text"
    finally:
        judge.undo()
        _kill_tree(sim)
        if agent.poll() is None:
            agent.terminate()
            try:
                agent.wait(timeout=5)
            except subprocess.TimeoutExpired:
                agent.kill()
