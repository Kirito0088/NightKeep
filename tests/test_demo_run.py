"""The demo runner enables the F9 server pop-up for the attack INCIDENT.

Covers the wiring inside nightkeep/demo_run.py: the guard Judge is built
with server_alerts=True, so when the fast simulator's run is judged
INCIDENT the office computer's own pop-up fires. The Windows-only day loop
(cscript.exe/cmd.exe jobs) is stubbed out: it cannot run on Linux and is
irrelevant to the alert path. Marked slow: real filesystem, subprocess and
watcher, like the smoke run this mirrors.
"""

import shutil
from pathlib import Path

import pytest

from nightkeep import demo_run, server_alert
from nightkeep.config import load_config
from nightkeep.types import INCIDENT

pytestmark = pytest.mark.slow

REPO_ROOT = Path(__file__).resolve().parent.parent
DEMO_DIR = REPO_ROOT / "demo"


def _stub_run_day(day_no, *, seed, clock, jobs, harvest_surge, district_dir,
                  harvest_surge_override=None):
    """Stand in for the Windows-only day loop. The alert path under test
    starts at the simulator attack, which does not depend on it."""
    return None


def test_demo_runner_raises_the_server_pop_up_on_attack_incident(
    monkeypatch, tmp_path
):
    shown = []
    monkeypatch.setattr(
        server_alert, "_platform_show", lambda alert: shown.append(alert) or True
    )
    monkeypatch.setattr("nightkeep.mock_pds.run_day", _stub_run_day)

    # The safe simulator refuses to run outside the repo's demo folder.
    out_dir = DEMO_DIR / "test_demo_run_alert"
    try:
        config = load_config(REPO_ROOT / "nightkeep" / "config.yaml")
        report = demo_run.run_demo(config, out_dir, variant="fast")
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)

    assert report["attack"]["level"] == INCIDENT
    assert len(shown) == 1
    assert "paused" in shown[0].headline
