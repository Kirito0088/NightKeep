"""The Full MVP Demo, driven through the console's live session.

With a live session, "Run Full MVP Demo" restarts that same session on
autopilot, so the showcase and every other screen show one run. The page
words the engine's status; the figures come from the engine's report.
"""

from __future__ import annotations

from pathlib import Path

from nightkeep import live_protocol as lp
from nightkeep.config import load_config
from nightkeep.console.__main__ import create_console_app
from nightkeep.console.showcase import LiveShowcase

from tests.test_console_live import FakeSession, learning_status

CONFIG = load_config(Path(__file__).resolve().parent.parent / "nightkeep" / "config.yaml")


class ReportingSession(FakeSession):
    def __init__(self, root, status=None, report=None, log=""):
        super().__init__(root, status)
        self._report = report or {}
        self._log = log

    def report(self) -> dict:
        return self._report

    def log_tail(self, lines: int = 40) -> str:
        return self._log


def client_for(session):
    app = create_console_app(CONFIG, session=session)
    app.config["TESTING"] = True
    return app.test_client()


def test_run_full_demo_restarts_the_live_session_on_autopilot(tmp_path):
    session = ReportingSession(tmp_path / "live", learning_status(mode="manual"))
    client = client_for(session)
    html = client.get("/showcase").get_data(as_text=True)
    assert "Run Full MVP Demo" in html
    assert "starting it" in html and "begins a fresh run" in html

    client.post("/showcase/start")
    assert session.starts == [{"autopilot": True,
                               "variant": CONFIG.console.full_demo_variant}]


def test_a_manual_session_leaves_the_showcase_ready(tmp_path):
    showcase = LiveShowcase(ReportingSession(tmp_path, learning_status(mode="manual")),
                            "recovery-killer")
    assert showcase.read_status() == {"state": "ready"}
    assert showcase.phase() == "ready"


def test_autopilot_phases_map_onto_the_showcase_steps(tmp_path):
    expectations = {
        lp.LEARNING: "learning", lp.GUARD: "guard", lp.ATTACK: "attack",
        lp.CONTAINMENT: "containment", lp.VAULT: "vault",
        lp.CONTAINED: "vault", lp.RECOVERY: "recovery",
    }
    for phase, step in expectations.items():
        session = ReportingSession(tmp_path, learning_status(mode="autopilot", phase=phase))
        showcase = LiveShowcase(session, "recovery-killer")
        assert showcase.read_status()["state"] == "running", phase
        assert showcase.phase() == step, phase


def test_a_running_autopilot_is_not_started_twice(tmp_path):
    session = ReportingSession(tmp_path, learning_status(mode="autopilot", phase=lp.GUARD))
    assert LiveShowcase(session, "recovery-killer").start() == {
        "started": False, "reason": "already_running"}
    assert session.starts == []


def test_completed_autopilot_shows_the_engines_own_figures(tmp_path):
    report = {
        "seed": 20260922, "variant": "recovery-killer",
        "attack": {"level": "INCIDENT", "detection_latency_seconds": 1.734,
                   "affected_files_at_incident": 41},
        "restore": {"records_verified": 5000, "records_expected": 5000},
    }
    session = ReportingSession(
        tmp_path / "live",
        learning_status(mode="autopilot", phase=lp.COMPLETE),
        report=report, log="--- proof PASSED ---",
    )
    html = client_for(session).get("/showcase").get_data(as_text=True)
    assert "DEMO COMPLETE" in html
    assert "5000 / 5000" in html
    assert "1.7s" in html
    assert "--- proof PASSED ---" in html
    assert '<meta http-equiv="refresh"' not in html


def test_a_failed_autopilot_says_so(tmp_path):
    session = ReportingSession(
        tmp_path / "live",
        learning_status(mode="autopilot", phase=lp.FAILED,
                        error="RuntimeError: a simulated day failed"),
        report={"learning_days": [{"day": 1}]},
    )
    html = client_for(session).get("/showcase").get_data(as_text=True)
    assert "DEMO FAILED" in html
    assert "a simulated day failed" in html
