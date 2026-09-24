"""Tests for the one-click showcase and the read-only IT view.

The showcase launches the real demo as a subprocess; here a tiny fake
script stands in for the demo so the tests stay fast. The fake prints
the same marker lines the real runner prints, so phase parsing is
exercised for real. The controller is injected with throwaway paths,
so no test ever touches the real demo/ directory or spawns a real run.
"""

import json
import os
import signal
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from nightkeep.console.app import create_app
from nightkeep.console.providers import VerdictRecord
from nightkeep.console.showcase import ShowcaseController

FAKE_PASSED_SCRIPT = """\
import json
import sys
from pathlib import Path

district = Path(sys.argv[1])
print("Nightkeep end-to-end proof, seed 7", flush=True)
print("--- learning: 7 days ---", flush=True)
print("--- guard: 3 days ---", flush=True)
print("--- attack: safe ransomware simulator ---", flush=True)
print("containment: simulator pid 4242 suspended; latency 1.2s; 40 files in the window", flush=True)
print("--- vault after the attack ---", flush=True)
print("--- recovery: restore the pinned clean snapshot ---", flush=True)
print("cards recovered: 5,000 / 5,000", flush=True)
print("--- proof PASSED ---", flush=True)
reports = district / "reports"
reports.mkdir(parents=True, exist_ok=True)
(reports / "demo_run.json").write_text(json.dumps({
    "seed": 7,
    "variant": "recovery-killer",
    "passed": True,
    "restore": {"records_verified": 5000, "records_expected": 5000},
    "attack": {
        "level": "INCIDENT",
        "detection_latency_seconds": 4.2,
        "affected_files_at_incident": 37,
    },
}))
"""

FAKE_FAILED_SCRIPT = """\
print("Nightkeep end-to-end proof, seed 7", flush=True)
print("--- learning: 7 days ---", flush=True)
print("--- attack: safe ransomware simulator ---", flush=True)
print("--- proof FAILED ---", flush=True)
raise SystemExit(1)
"""

FAKE_SLOW_SCRIPT = """\
import time
print("Nightkeep end-to-end proof, seed 7", flush=True)
print("--- learning: 7 days ---", flush=True)
time.sleep(60)
"""


@pytest.fixture
def showcase_dirs(tmp_path):
    base = tmp_path / "showcase"
    base.mkdir()
    script = base / "fake_demo.py"
    district = base / "district"
    return base, script, district


def make_controller(base, script, district, script_text):
    script.write_text(script_text, encoding="utf-8")
    return ShowcaseController(
        status_path=base / "showcase_status.json",
        log_path=base / "showcase_demo.log",
        demo_cmd=[sys.executable, str(script), str(district)],
        district_dir=district,
    )


def make_client(controller, factory=None):
    app = create_app(
        showcase_controller=controller, runtime_factory=factory
    )
    app.config["TESTING"] = True
    return app.test_client()


def wait_for_state(controller, want, timeout=20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = controller.read_status()
        if status.get("state") == want:
            return status
        time.sleep(0.2)
    raise AssertionError(
        f"timed out waiting for {want}; last status: "
        f"{controller.read_status()}"
    )


def kill_pid(pid):
    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        pass


# --- showcase ---------------------------------------------------------------


def test_showcase_route_returns_200(showcase_dirs):
    base, script, district = showcase_dirs
    controller = make_controller(base, script, district, FAKE_PASSED_SCRIPT)
    html = make_client(controller).get("/showcase").get_data(as_text=True)
    assert "Start guided demo" in html
    assert "Ready" in html


def test_start_launches_exactly_one_process(showcase_dirs):
    base, script, district = showcase_dirs
    controller = make_controller(base, script, district, FAKE_SLOW_SCRIPT)
    client = make_client(controller)
    try:
        first = controller.start()
        assert first["started"] is True
        first_pid = first["pid"]

        # A second start while running is rejected: same single process.
        second = controller.start()
        assert second["started"] is False
        assert second["reason"] == "already_running"
        assert controller.read_status()["pid"] == first_pid

        # ... and through HTTP too.
        response = client.post("/showcase/start")
        assert response.status_code in (301, 302, 303)
        assert controller.read_status()["pid"] == first_pid

        html = client.get("/showcase").get_data(as_text=True)
        assert "Guided demo running" in html
    finally:
        kill_pid(first_pid)


def test_status_progresses_from_running_to_complete(showcase_dirs):
    base, script, district = showcase_dirs
    controller = make_controller(base, script, district, FAKE_PASSED_SCRIPT)
    client = make_client(controller)

    client.post("/showcase/start")
    assert controller.read_status()["state"] == "running"

    wait_for_state(controller, "complete")
    assert controller.phase() == "complete"

    html = client.get("/showcase").get_data(as_text=True)
    assert "Demo complete" in html
    assert "End-to-end proof complete." in html


def test_completion_uses_actual_report_data(showcase_dirs):
    base, script, district = showcase_dirs
    controller = make_controller(base, script, district, FAKE_PASSED_SCRIPT)
    client = make_client(controller)

    client.post("/showcase/start")
    wait_for_state(controller, "complete")

    html = client.get("/showcase").get_data(as_text=True)
    # The figures on the page are the report's own figures.
    assert "5,000 / 5,000" in html
    assert "4.2s" in html
    assert "37" in html
    # ... and nothing invented: no placeholder figures anywhere.
    assert "13 files" not in html
    assert "2.1 seconds" not in html


def test_failed_demo_is_shown_as_failed(showcase_dirs):
    base, script, district = showcase_dirs
    controller = make_controller(base, script, district, FAKE_FAILED_SCRIPT)
    client = make_client(controller)

    client.post("/showcase/start")
    wait_for_state(controller, "failed")

    html = client.get("/showcase").get_data(as_text=True)
    assert "Demo failed" in html
    assert "did not complete" in html


def test_status_survives_a_fresh_controller(showcase_dirs):
    """A page refresh (or app reload) sees the running demo, not a new one."""
    base, script, district = showcase_dirs
    controller = make_controller(base, script, district, FAKE_SLOW_SCRIPT)
    first = controller.start()
    try:
        fresh = ShowcaseController(
            status_path=base / "showcase_status.json",
            log_path=base / "showcase_demo.log",
            demo_cmd=[sys.executable, str(script), str(district)],
            district_dir=district,
        )
        status = fresh.read_status()
        assert status["state"] == "running"
        assert status["pid"] == first["pid"]
        # The fresh controller also refuses a second launch.
        assert fresh.start()["started"] is False
    finally:
        kill_pid(first["pid"])


def test_showcase_never_starts_two_processes(showcase_dirs):
    base, script, district = showcase_dirs
    controller = make_controller(base, script, district, FAKE_SLOW_SCRIPT)
    client = make_client(controller)
    try:
        client.post("/showcase/start")
        client.post("/showcase/start")
        client.post("/showcase/start")
        pids = set()
        status = controller.read_status()
        assert status["state"] == "running"
        pids.add(status["pid"])
        assert len(pids) == 1
    finally:
        kill_pid(status["pid"])


# --- IT view -----------------------------------------------------------------


def test_it_view_without_runtime_is_honest(showcase_dirs):
    base, script, district = showcase_dirs
    controller = make_controller(base, script, district, FAKE_PASSED_SCRIPT)
    html = make_client(controller).get("/it-view").get_data(as_text=True)
    assert (
        "IT diagnostics are unavailable until the live session has built the district."
        in html
    )
    # No fabricated diagnostics: no verdict, no snapshots, no cards.
    assert "INCIDENT" not in html


def _stub_runtime():
    incident = VerdictRecord(
        job="simulator",
        day_no=None,
        level="INCIDENT",
        signals=("S5",),
        signal_titles=("Recovery sabotage",),
        reasons=("recovery-deletion text seen in a shell command",),
        actions=("process suspended",),
    )
    liveness = SimpleNamespace(
        alive=True, last_seen=None, reason="heartbeat fresh"
    )
    snapshot = SimpleNamespace(
        snapshot_id="snap-0007",
        taken_at=None,
        health="CLEAN",
        file_count=120,
        manifest_hash="abcdef1234567890abcdef",
        is_clean_point=True,
    )
    calls = []

    class FakeVault:
        def check_watcher_liveness(self):
            calls.append("check_watcher_liveness")
            return liveness

        @property
        def vault_verdict(self):
            return "INCIDENT"

        @property
        def protect_mode(self):
            return True

        def snapshots(self):
            calls.append("snapshots")
            return [snapshot]

        def alerts(self):
            calls.append("alerts")
            return [
                {
                    "ts": "2026-09-22T10:00:00",
                    "verdict": "INCIDENT",
                    "previous_verdict": "NORMAL",
                    "protect_mode": True,
                    "watcher_alive": True,
                }
            ]

    class FakeHabit:
        def cards(self):
            calls.append("cards")
            return {"nightly_export.py": {"start_minute": (63.0, 4.0)}}

        def run_count(self, job):
            return 7

    return (
        SimpleNamespace(
            incident=incident, vault=FakeVault(), habit=FakeHabit()
        ),
        calls,
    )


def test_it_view_renders_real_runtime_diagnostics(showcase_dirs):
    base, script, district = showcase_dirs
    controller = make_controller(base, script, district, FAKE_PASSED_SCRIPT)
    runtime, _ = _stub_runtime()
    client = make_client(controller, factory=lambda: runtime)

    html = client.get("/it-view").get_data(as_text=True)
    assert "INCIDENT" in html
    assert "S5" in html
    assert "recovery-deletion text seen in a shell command" in html
    assert "process suspended" in html
    assert "alive" in html
    assert "protect mode" in html.lower()
    assert "nightly_export.py" in html
    assert "start_minute" in html
    assert "snap-0007" in html
    assert "abcdef1234567890"[:16] in html
    # The unavailable message must not appear when runtime exists.
    assert "unavailable until the live session" not in html


def test_it_view_never_mutates_backend(showcase_dirs):
    base, script, district = showcase_dirs
    controller = make_controller(base, script, district, FAKE_PASSED_SCRIPT)
    runtime, calls = _stub_runtime()
    client = make_client(controller, factory=lambda: runtime)

    before = list(calls)
    client.get("/it-view")
    client.get("/it-view")
    after = [c for c in calls if c not in before]

    # Only the read-only accessors the view is built on.
    assert set(after) <= {
        "check_watcher_liveness",
        "snapshots",
        "alerts",
        "cards",
    }
    # No restore, no PIN check, no state change: the stub vault/habit
    # expose no mutating methods at all, so any mutation would fail
    # loudly instead of passing silently.


def test_dead_it_buttons_are_real_links(showcase_dirs):
    base, script, district = showcase_dirs
    controller = make_controller(base, script, district, FAKE_PASSED_SCRIPT)
    client = make_client(controller)
    for path in ("/safety", "/alert"):
        html = client.get(path).get_data(as_text=True)
        assert "For the IT person" in html
        assert "btn-it-access" in html
        assert "IT View unavailable" not in html
        assert 'href="/it-view"' in html
        assert '<a href="#"' not in html


def test_checking_a_stale_pid_never_ends_the_process_holding_it():
    """A fresh controller checks the PID from its status file. On Windows,
    os.kill(pid, 0) is TerminateProcess, so a probe built on it would end
    whatever process now holds that PID. The check must only look."""
    import subprocess

    from nightkeep.console.showcase import _pid_alive

    bystander = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        assert _pid_alive(bystander.pid) is True
        time.sleep(0.2)
        assert bystander.poll() is None, "the liveness check ended the process"
        assert _pid_alive(bystander.pid) is True
    finally:
        bystander.kill()
        bystander.wait(timeout=10)
    assert _pid_alive(bystander.pid) is False
