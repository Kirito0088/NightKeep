"""F9: the PDS server raises its own pop-up when the Judge fires INCIDENT.

The Vault console only *renders* the alert afterwards (GET /server-alert,
on the Vault's screen). This is the other half of F9: the office computer
shows its own pop-up the moment the verdict is decided, with nobody opening
anything. The display is always injected here, so the suite never pops a
real dialog.
"""

from datetime import datetime, timedelta

import pytest

from nightkeep import server_alert
from nightkeep.habit import Habit
from nightkeep.judge import Judge
from nightkeep.server_alert import ServerAlert
from nightkeep.types import (
    INCIDENT,
    MODIFIED,
    NORMAL,
    ODD,
    SUSPICIOUS,
    Event,
    JobRun,
    Verdict,
)

AT = datetime(2026, 9, 22, 3, 41, 12)
TRAPS = ("share/exports/epos_day_end_20240101.csv",)


@pytest.fixture
def root(tmp_path):
    for folder in ("data", "share/exports", "share/backups", "allocations"):
        (tmp_path / folder).mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture
def habit(tmp_path):
    return Habit(tmp_path / "habit.db", 3.0, 3, 0.10)


def make_judge(root, habit, **kwargs):
    made = Judge(
        root=root,
        habit=habit,
        odd_score=0.5,
        rename_burst=10,
        entropy_jump=1.5,
        entropy_floor=7.0,
        recovery_commands=("vssadmin delete shadows", "wbadmin delete catalog"),
        canary_files=TRAPS,
        **kwargs,
    )
    made.plant_traps()
    yield made
    made.undo()


@pytest.fixture
def judge(root, habit):
    yield from make_judge(root, habit)


@pytest.fixture
def alerting_judge(root, habit):
    yield from make_judge(root, habit, server_alerts=True)


def job_run(events=()):
    return JobRun(
        job="nightly_export",
        identity="python|jobs/nightly_export.py|abc123",
        started_at=AT,
        finished_at=AT + timedelta(seconds=30),
        events=tuple(events),
        sim_started_at=AT,
        day_no=8,
    )


def trap_touch():
    return job_run([Event(path=TRAPS[0], kind=MODIFIED, at=AT, size=1)])


def test_only_an_incident_verdict_builds_a_server_alert(judge):
    incident = judge.verdict(trap_touch())
    assert incident.level == INCIDENT

    alert = server_alert.alert_for(incident)
    assert isinstance(alert, ServerAlert)
    assert alert.title == "Nightkeep Security Alert"
    # trap_touch() carries no PID, so nothing was paused: the headline must
    # not claim otherwise.
    assert alert.headline == "A program tried to lock your files. It was not paused."
    assert any("Do not restart this computer." == line for line in alert.details)


def test_incident_with_no_pid_says_not_paused(judge):
    """No PID in the events means the Judge never attempted a pause. The
    pop-up must be truthful about that."""
    incident = judge.verdict(trap_touch())
    assert incident.level == INCIDENT
    assert not any(action.startswith("paused") for action in incident.actions)

    alert = server_alert.alert_for(incident)
    assert "not paused" in alert.headline


def test_incident_with_a_paused_process_says_paused(judge):
    """A real process behind the events gets suspended, and only then does
    the pop-up say it was paused."""
    import subprocess
    import sys

    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        incident = judge.verdict(
            job_run([
                Event(path=TRAPS[0], kind=MODIFIED, at=AT, size=1,
                      pid=sleeper.pid),
            ])
        )
        assert incident.level == INCIDENT
        assert any(
            action.startswith("paused") for action in incident.actions
        ), incident.actions

        alert = server_alert.alert_for(incident)
        assert alert.headline == (
            "A program tried to lock your files. It was paused."
        )
    finally:
        judge.undo()
        sleeper.terminate()
        sleeper.wait()


def test_quiet_verdicts_build_no_server_alert():
    for level in (NORMAL, ODD, SUSPICIOUS):
        assert server_alert.alert_for(Verdict(level=level)) is None


def test_raise_for_verdict_shows_the_alert(judge):
    incident = judge.verdict(trap_touch())
    shown = []
    shown_ok = server_alert.raise_for_verdict(
        incident, show=lambda alert: shown.append(alert) or True
    )
    assert shown_ok is True
    assert shown == [server_alert.alert_for(incident)]


def test_raise_for_verdict_is_quiet_without_an_incident():
    shown = []
    shown_ok = server_alert.raise_for_verdict(
        Verdict(level=NORMAL), show=lambda alert: shown.append(alert) or True
    )
    assert shown_ok is False
    assert shown == []


def test_raise_alert_never_raises(judge, capsys):
    incident = judge.verdict(trap_touch())

    def no_desktop(alert):
        raise RuntimeError("no display on this machine")

    assert server_alert.raise_for_verdict(incident, show=no_desktop) is False
    assert "Nightkeep Security Alert" in capsys.readouterr().err


def test_failed_popup_falls_back_to_stderr(judge, capsys):
    incident = judge.verdict(trap_touch())
    assert server_alert.raise_for_verdict(incident, show=lambda alert: False) is False
    assert "paused" in capsys.readouterr().err


def test_judge_raises_the_server_pop_up_on_incident(alerting_judge, monkeypatch):
    shown = []
    monkeypatch.setattr(
        server_alert, "_platform_show", lambda alert: shown.append(alert) or True
    )
    verdict = alerting_judge.verdict(trap_touch())
    assert verdict.level == INCIDENT
    assert len(shown) == 1
    assert isinstance(shown[0], ServerAlert)
    assert "paused" in shown[0].headline


def test_judge_does_not_pop_up_by_default(judge, monkeypatch):
    shown = []
    monkeypatch.setattr(
        server_alert, "_platform_show", lambda alert: shown.append(alert) or True
    )
    verdict = judge.verdict(trap_touch())
    assert verdict.level == INCIDENT
    assert shown == []


def test_judge_does_not_pop_up_for_quiet_verdicts(alerting_judge, monkeypatch):
    shown = []
    monkeypatch.setattr(
        server_alert, "_platform_show", lambda alert: shown.append(alert) or True
    )
    verdict = alerting_judge.verdict(job_run([]))
    assert verdict.level != INCIDENT
    assert shown == []
