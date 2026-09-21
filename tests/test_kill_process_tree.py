"""_kill_process_tree() must survive the fast-exit cleanup race.

The demo resolves the simulator PID and *then* enumerates its process
tree. A simulator that exits in between makes psutil raise NoSuchProcess
from children() -- and before the hardening pass that exception escaped
_kill_process_tree(), aborting the finally block in _judge_attack_live
before proc.wait() and judge.undo() could run, potentially leaving the
share/data surfaces read-only.
"""

import subprocess
import sys
import time

import psutil
import pytest

from nightkeep import demo_run


def _sleeper(seconds=30):
    return subprocess.Popen(
        [sys.executable, "-c", f"import time; time.sleep({seconds})"]
    )


def test_fast_exit_race_during_tree_traversal_does_not_crash():
    """children() raising NoSuchProcess is the exact psutil behavior when
    the process dies between PID discovery and traversal. Cleanup must
    treat it as an expected race: no crash, and the (already resolved)
    root is still signaled."""
    proc = _sleeper()
    real_children = psutil.Process.children

    def racing_children(self, recursive=False):
        raise psutil.NoSuchProcess(self.pid)

    psutil.Process.children = racing_children
    try:
        signaled = demo_run._kill_process_tree(proc.pid)
    finally:
        psutil.Process.children = real_children
        # Belt and braces: the test must never leak the sleeper.
        proc.kill()
        proc.wait()
    assert proc.pid in signaled


def test_kill_process_tree_is_idempotent_on_gone_process():
    """A second cleanup pass over an already-reaped PID is a no-op that
    returns [], not an exception -- cleanup stays idempotent."""
    proc = _sleeper(seconds=1)
    proc.wait()  # reaped: the PID is now dead
    dead_pid = proc.pid
    assert not psutil.pid_exists(dead_pid)
    assert demo_run._kill_process_tree(dead_pid) == []
    assert demo_run._kill_process_tree(dead_pid) == []


def test_kill_process_tree_kills_descendants():
    """The non-race path is unchanged: children still die with the root."""
    parent = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import subprocess, sys, time; "
            "subprocess.Popen([sys.executable, '-c', "
            "'import time; time.sleep(30)']); "
            "time.sleep(30)",
        ]
    )
    try:
        child_pid = None
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                kids = psutil.Process(parent.pid).children(recursive=True)
            except psutil.NoSuchProcess:
                kids = []
            if kids:
                child_pid = kids[0].pid
                break
            time.sleep(0.1)
        assert child_pid is not None, "child process never appeared"

        signaled = demo_run._kill_process_tree(parent.pid)

        assert parent.pid in signaled
        assert child_pid in signaled
        # Reap the direct child (the caller's proc.wait() job in the real
        # cleanup path); then both must be truly gone.
        parent.wait(timeout=10)
        assert not psutil.pid_exists(parent.pid)
        deadline = time.monotonic() + 10
        while psutil.pid_exists(child_pid) and time.monotonic() < deadline:
            time.sleep(0.1)
        assert not psutil.pid_exists(child_pid)
    finally:
        # The kill tree should have handled this; never leak on failure.
        for pid in (parent.pid,):
            try:
                demo_run._kill_process_tree(pid)
            except Exception:
                pass
        try:
            parent.wait(timeout=5)
        except Exception:
            pass


def test_unexpected_errors_still_propagate():
    """Only process-lifecycle exceptions are tolerated. An unexpected
    failure inside the kill loop must not be swallowed."""
    proc = _sleeper()
    real_kill = psutil.Process.kill

    def boom(self):
        raise RuntimeError("unexpected kill failure")

    psutil.Process.kill = boom
    try:
        with pytest.raises(RuntimeError, match="unexpected kill failure"):
            demo_run._kill_process_tree(proc.pid)
    finally:
        psutil.Process.kill = real_kill
        proc.kill()
        proc.wait()
