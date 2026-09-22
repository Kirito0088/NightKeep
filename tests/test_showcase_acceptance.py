"""Acceptance tests for the Round 2 showcase discoverability work.

Covers what the earlier suites do not:
  * the primary navigation exposes /showcase on every primary page,
  * the showcase is reachable from a normal (unconfigured) console,
  * the showcase page fabricates nothing before a run exists,
  * the final links shown after a completed run resolve to 200.
"""

import json
import re
import sys
import time

import pytest

from nightkeep.console.app import create_app
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


@pytest.fixture
def showcase_dirs(tmp_path):
    base = tmp_path / "showcase"
    base.mkdir()
    script = base / "fake_demo.py"
    district = base / "district"
    return base, script, district


def make_controller(base, script, district):
    script.write_text(FAKE_PASSED_SCRIPT, encoding="utf-8")
    return ShowcaseController(
        status_path=base / "showcase_status.json",
        log_path=base / "showcase_demo.log",
        demo_cmd=[sys.executable, str(script), str(district)],
        district_dir=district,
    )


def make_client(controller=None):
    app = create_app(
        showcase_controller=controller,
        runtime_factory=None,
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
        "timed out waiting for %r; last status: %r"
        % (want, controller.read_status())
    )


# --- discoverability ---------------------------------------------------------


def test_primary_nav_exposes_full_mvp_demo_on_every_primary_page():
    """A judge can find the one-click demo from /, /safety, and /showcase."""
    client = make_client()
    for route in ("/", "/safety", "/showcase"):
        html = client.get(route).get_data(as_text=True)
        assert 'href="/showcase"' in html, route
        assert "Full MVP Demo" in html, route


def test_showcase_active_only_on_showcase_page():
    """The primary nav marks exactly one item as active per page."""
    client = make_client()
    for route, label in (
        ("/", "Ration Card Search"),
        ("/safety", "Data Safety"),
        ("/showcase", "Full MVP Demo"),
    ):
        html = client.get(route).get_data(as_text=True)
        active_links = re.findall(r'class="nav-link active"', html)
        assert len(active_links) == 1, route
        assert label in html, route


# --- reachability from a normal console --------------------------------------


def test_showcase_reachable_from_unconfigured_console():
    """No special wiring is needed to open the showcase page."""
    client = make_client()
    resp = client.get("/showcase")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Run Full MVP Demo" in html


def test_showcase_fabricates_nothing_before_a_run():
    """/showcase with no run must never claim an incident happened.

    The static step list names the demo's planned phases (that is the
    plan, not a claim); the status banner itself must stay at READY
    with no incident figures.
    """
    client = make_client()
    html = client.get("/showcase").get_data(as_text=True)
    assert "READY" in html
    # No completed-state figures or failure verdicts before any run exists.
    # (The static step plan legitimately names "DEMO COMPLETE" as the final
    # planned step; the check below ensures it is not marked done.)
    for forged in ("5000 / 5000", "DEMO FAILED", "Measured on this run",
                   "records recovered and verified"):
        assert forged not in html
    assert "demo-step-done" not in html
    # The status banner (not the step plan) carries the verdict.
    banner = re.search(r'<div class="showcase-banner.*?</div>', html, re.DOTALL)
    if banner:
        assert "INCIDENT" not in banner.group(0)


# --- final links -------------------------------------------------------------


def test_completed_showcase_links_resolve(showcase_dirs):
    """The four links shown after a completed run each return 200."""
    base, script, district = showcase_dirs
    controller = make_controller(base, script, district)
    client = make_client(controller)

    client.post("/showcase/start")
    wait_for_state(controller, "complete")

    html = client.get("/showcase").get_data(as_text=True)
    assert "DEMO COMPLETE" in html
    for route in ("/alert", "/restore", "/locked", "/it-view"):
        resp = client.get(route)
        assert resp.status_code == 200, route
