"""Watcher startup failure must not leak the agent process.

_start_watcher_agent() waits up to 30s for the agent's first heartbeat.
Before the hardening pass, a timeout raised out of the wait loop while the
agent subprocess was still alive: the leaked watcher then contaminated
later runs' watcher-killer/S6 behavior and broke back-to-back demos.
"""

import subprocess
import sys
from unittest import mock

import pytest

from nightkeep import demo_run


class _FakeClock:
    """Deterministic stand-in for the time module used by demo_run.

    sleep() advances the clock instead of waiting, so the 30s startup
    deadline fires after ~300 loop iterations with zero real waiting.
    Replacing the `time` name inside demo_run's namespace keeps the seam
    contained: the real time module is untouched.
    """

    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def _seam_no_beats(tmp_path, monkeypatch, proc):
    """The agent stays alive but never writes its heartbeat."""
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: proc)
    monkeypatch.setattr(
        demo_run, "heartbeat_path", lambda district_dir: tmp_path / "never"
    )
    monkeypatch.setattr(demo_run, "time", _FakeClock())


def test_startup_timeout_still_raises_and_cleans_up_agent(tmp_path, monkeypatch):
    """The timeout error is preserved AND the agent is stopped before it
    escapes: terminate is attempted on the live process."""
    proc = mock.MagicMock()
    proc.poll.return_value = None  # alive, just never beats
    _seam_no_beats(tmp_path, monkeypatch, proc)

    with pytest.raises(RuntimeError, match="never wrote its first beat"):
        demo_run._start_watcher_agent(tmp_path, 10.0, 0.5, 1.0)

    proc.terminate.assert_called_once_with()
    proc.wait.assert_called_once_with(timeout=5)


def test_startup_failure_when_agent_exited_early_is_safe(tmp_path, monkeypatch):
    """When the agent died on its own before the first beat, cleanup sees
    the exit and does not attempt a terminate on a dead process."""
    proc = mock.MagicMock()
    proc.poll.return_value = 1  # already exited
    _seam_no_beats(tmp_path, monkeypatch, proc)

    with pytest.raises(RuntimeError, match="exited before its first beat"):
        demo_run._start_watcher_agent(tmp_path, 10.0, 0.5, 1.0)

    proc.terminate.assert_not_called()


def test_stop_watcher_agent_really_terminates_a_live_process():
    """The cleanup helper itself works on a real process: not just a mock
    assertion, the OS process is gone afterwards."""
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"]
    )
    assert proc.poll() is None
    demo_run._stop_watcher_agent(proc)
    assert proc.poll() is not None


def test_stop_watcher_agent_is_safe_on_already_exited_process():
    """Cleanup must not raise merely because the process already exited."""
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()  # reaped: definitely gone
    demo_run._stop_watcher_agent(proc)  # must not raise
