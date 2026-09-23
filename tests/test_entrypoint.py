"""The entrypoint is the glue: it reads config once and hands values on.

What matters here is the failure. A bad config.yaml must stop Nightkeep at
start-up with a message naming the key, not three minutes into a demo run.
"""

import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
REPO_CONFIG = REPO / "nightkeep" / "config.yaml"


def _run(*arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "nightkeep", *arguments],
        cwd=REPO,
        capture_output=True,
        text=True,
    )


def test_starting_nightkeep_with_the_repo_config_succeeds():
    finished = _run()

    assert finished.returncode == 0, finished.stderr
    assert "5,000 ration cards" in finished.stdout
    assert "6 jobs configured" in finished.stdout


def test_a_broken_config_stops_nightkeep_at_startup(tmp_path):
    raw = yaml.safe_load(REPO_CONFIG.read_text(encoding="utf-8"))
    raw["clock"].pop("simulated_day_seconds")
    broken = tmp_path / "config.yaml"
    broken.write_text(yaml.safe_dump(raw), encoding="utf-8")

    finished = _run(str(broken))

    assert finished.returncode != 0
    assert "clock.simulated_day_seconds" in finished.stderr


def test_console_starts_a_live_session_on_loopback(tmp_path, monkeypatch):
    """python -m nightkeep --console: one command starts the live session
    beside Flask, on 127.0.0.1 only, and stops the session on the way out."""
    from flask import Flask

    from nightkeep import __main__ as entry
    from nightkeep.console.session import LiveSession

    calls = []
    monkeypatch.setattr(Flask, "run", lambda self, **kw: calls.append(("run", kw)))
    monkeypatch.setattr(LiveSession, "start",
                        lambda self, **kw: calls.append(("start", self._engine_cmd)))
    monkeypatch.setattr(LiveSession, "stop", lambda self: calls.append(("stop",)))

    out_dir = tmp_path / "live"
    assert entry.main(["--console", "--out-dir", str(out_dir),
                       "--day-seconds", "12"]) == 0

    start, run, stop = calls
    assert start[0] == "start"
    engine_cmd = start[1]
    assert engine_cmd[1:4] == ["-m", "nightkeep", str(REPO_CONFIG)]
    assert "--live-engine" in engine_cmd
    assert engine_cmd[engine_cmd.index("--out-dir") + 1] == str(out_dir.resolve())
    assert engine_cmd[engine_cmd.index("--day-seconds") + 1] == "12"
    assert run == ("run", {"host": "127.0.0.1", "port": 5000, "debug": False})
    assert stop == ("stop",)
