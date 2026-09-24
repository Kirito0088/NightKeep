"""The console with a live session: demo controls, lock screen, restore report.

A fake session stands in for the engine: these tests pin what the console
does with a status, not what the engine does (tests/test_live.py covers
that). LiveSession itself is exercised against a real folder.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from nightkeep import live_protocol as lp
from nightkeep.config import load_config
from nightkeep.console.__main__ import create_console_app
from nightkeep.console.live_view import live_controls, stamp, surge_line
from nightkeep.console.session import LiveSession, SessionFolderRefused

CONFIG = load_config(Path(__file__).resolve().parent.parent / "nightkeep" / "config.yaml")
DISCLAIMER = "Prototype on invented data. Not a live government system."


class FakeSession:
    def __init__(self, root: Path, status: dict | None = None) -> None:
        self.paths = lp.SessionPaths(root)
        self._status = status or {}
        self.attacks: list[str] = []
        self.surge: list[bool] = []
        self.restores: list = []
        self.starts: list[dict] = []

    def status(self) -> dict:
        return self._status

    def report(self) -> dict:
        return {}

    def log_tail(self, lines: int = 40) -> str:
        return ""

    def is_running(self) -> bool:
        return bool(self._status)

    def request_attack(self, variant: str) -> None:
        self.attacks.append(variant)

    def set_harvest_surge(self, on: bool) -> None:
        self.surge.append(on)

    def record_restore(self, result) -> None:
        self.restores.append(result)

    def start(self, *, autopilot: bool = False, variant: str | None = None) -> None:
        self.starts.append({"autopilot": autopilot, "variant": variant})


def learning_status(**overrides) -> dict:
    status = {
        "version": 3,
        "phase": lp.LEARNING,
        "day": {"number": 2, "done": 1, "learning_days": 7, "guard_days": 3,
                "surge_tonight": False, "surge_why": None},
        "attack_readiness": lp.ATTACK_READY,
        "harvest_surge_requested": False,
        "lock_held": False,
        "attack": {"state": "none"},
        "jobs": [],
        "checks": {"nights_checked": 0, "odd": 0, "incidents": 0, "recent": []},
        "vault": {"snapshots": 1, "clean_point": "20260923-100000"},
    }
    status.update(overrides)
    return status


@pytest.fixture
def make_client(tmp_path):
    def make(status: dict | None = None):
        session = FakeSession(tmp_path / "live", status)
        app = create_console_app(CONFIG, session=session)
        app.config["TESTING"] = True
        return app.test_client(), session

    return make


# --- the session controls live on the Live Demo page, nowhere else ------------


@pytest.mark.parametrize("path", ["/", "/safety", "/night-jobs", "/alert",
                                  "/restore", "/it-view"])
def test_no_page_carries_a_floating_demo_window(make_client, path):
    """The office screens are the office's: no demo pop-up or dock over them,
    and no demo switch in the government utility strip."""
    client, _ = make_client(learning_status())
    html = client.get(path).get_data(as_text=True)
    assert 'aria-label="Demo controls"' not in html
    assert "demo-dock" not in html
    assert "Launch simulated attack" not in html
    assert "Harvest surge" not in html
    assert DISCLAIMER in html
    # The page still follows the live session.
    assert "data-live-url" in html


def test_live_demo_page_carries_the_session_controls(make_client):
    client, _ = make_client(learning_status())
    html = client.get("/showcase").get_data(as_text=True)
    assert "Step-by-step controls" in html
    assert "Launch simulated attack" in html
    assert "Harvest surge" in html
    assert "Restart from day 1" in html
    assert "Learning the night jobs. Day 2 of 7." in html
    assert DISCLAIMER in html


def test_a_console_without_a_session_has_no_demo_controls():
    app = create_console_app(None)
    client = app.test_client()
    html = client.get("/").get_data(as_text=True)
    assert "data-live-url" not in html
    showcase = client.get("/showcase").get_data(as_text=True)
    assert "Step-by-step controls" not in showcase
    assert "Launch simulated attack" not in showcase


def test_attack_button_is_disabled_until_there_is_a_clean_copy(make_client):
    client, _ = make_client(learning_status(
        attack_readiness=lp.ATTACK_WAIT_FOR_CLEAN_COPY))
    html = client.get("/showcase").get_data(as_text=True)
    assert 'data-live="attack" disabled' in html
    assert "Available after day 1" in html


def test_variant_picker_offers_the_three_round_two_variants(make_client):
    client, _ = make_client(learning_status())
    html = client.get("/showcase").get_data(as_text=True)
    for label in ("Fast scrambler", "Impersonator", "Recovery-killer"):
        assert label in html


# --- the controls reach the session ----------------------------------------------


def test_attack_post_asks_the_session_and_returns_to_the_page(make_client):
    client, session = make_client(learning_status())
    response = client.post("/live/attack",
                           data={"variant": "impersonator", "next": "/night-jobs"})
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/night-jobs")
    assert session.attacks == ["impersonator"]


def test_attack_post_refuses_an_unknown_variant(make_client):
    client, session = make_client(learning_status())
    client.post("/live/attack", data={"variant": "watcher-killer"})
    client.post("/live/attack", data={"variant": "rm -rf"})
    assert session.attacks == []


def test_controls_never_redirect_off_the_console(make_client):
    client, _ = make_client(learning_status())
    response = client.post("/live/harvest-surge",
                           data={"on": "1", "next": "//evil.example/"})
    assert response.headers["Location"] in ("/", "http://localhost/")


def test_harvest_surge_switch_flips_the_session(make_client):
    client, session = make_client(learning_status())
    client.post("/live/harvest-surge", data={"on": "1"})
    client.post("/live/harvest-surge", data={"on": "0"})
    assert session.surge == [True, False]


def test_surge_switch_shows_its_state(make_client):
    client, _ = make_client(learning_status(harvest_surge_requested=True))
    html = client.get("/showcase").get_data(as_text=True)
    assert 'aria-pressed="true"' in html
    assert "Harvest surge: <strong>On</strong>" in html


def test_fresh_run_restarts_the_session(make_client):
    client, session = make_client(learning_status())
    client.post("/live/reset", data={"next": "/safety"})
    assert session.starts == [{"autopilot": False, "variant": None}]


# --- the lock screen and the restore -------------------------------------------------


def test_search_shows_the_lock_screen_while_the_records_are_held(make_client):
    client, _ = make_client(learning_status(phase=lp.CONTAINED, lock_held=True,
                                            attack={"state": "contained"}))
    html = client.get("/").get_data(as_text=True)
    assert "Ration card records cannot be opened" in html
    assert "DEMONSTRATION DRILL" not in html


def test_search_is_open_again_after_the_restore(make_client):
    client, _ = make_client(learning_status(phase=lp.RECOVERED, lock_held=False))
    html = client.get("/").get_data(as_text=True)
    assert "Ration card records cannot be opened" not in html
    assert 'id="card_no"' in html


def test_a_supervisor_restore_is_reported_to_the_session(make_client, monkeypatch):
    result =SimpleNamespace(ok=True, snapshot_id="s1", restored_to="x",
                             records_verified=5000, records_expected=5000,
                             checks=())

    class Service:
        available = True

        def attempt(self, pin):
            return result

    from nightkeep.console import providers

    monkeypatch.setattr(providers, "presentation_for",
                        lambda runtime: {"restore_service": Service()})
    monkeypatch.setattr("nightkeep.console.__main__.build_runtime",
                        lambda **kwargs: object())
    session_client, session = make_client(learning_status(phase=lp.CONTAINED,
                                                          lock_held=True))
    html = session_client.post("/restore", data={"restore_pin": "246810"}).get_data(as_text=True)
    assert session.restores == [result]
    assert "data-live-url" not in html, "a POST result page must not reload itself"


# --- live refresh -------------------------------------------------------------------


def test_status_json_carries_the_dock_and_a_stamp(make_client):
    client, _ = make_client(learning_status())
    data = client.get("/live/status.json?scope=calm").get_json()
    assert data["line"] == "Learning the night jobs. Day 2 of 7."
    assert data["can_attack"] is True
    assert data["stamp"] == stamp(learning_status(), "calm")


def test_calm_pages_ignore_a_finished_day_but_not_the_lock():
    before = learning_status()
    next_day = learning_status(day={**before["day"], "done": 2}, version=9)
    locked = learning_status(phase=lp.CONTAINED, lock_held=True)
    assert stamp(before, "calm") == stamp(next_day, "calm")
    assert stamp(before, "calm") != stamp(locked, "calm")
    assert stamp(before, "day") != stamp(next_day, "day")


def test_surge_line_says_why_tonight_is_a_surge_night():
    switched = learning_status(day={"number": 5, "surge_tonight": True,
                                    "surge_why": "switched on"})
    seeded = learning_status(day={"number": 4, "surge_tonight": True,
                                  "surge_why": "scheduled"})
    assert surge_line(switched) == "Harvest surge tonight: yes (switched on)."
    assert surge_line(seeded) == "Harvest surge tonight: yes (seeded surge day)."
    assert surge_line(learning_status()) == "Harvest surge tonight: no."


def test_no_status_means_no_attack():
    controls = live_controls({}, ("fast",))
    assert controls.can_attack is False
    assert controls.line == "The live session is not running."


# --- LiveSession against a real folder --------------------------------------------


def test_session_refuses_to_wipe_a_folder_it_did_not_make(tmp_path):
    root = tmp_path / "live"
    (root / "district").mkdir(parents=True)
    (root / "precious.txt").write_text("keep me", encoding="utf-8")
    session = LiveSession(lp.SessionPaths(root), ["python", "-c", "pass"])
    with pytest.raises(SessionFolderRefused):
        session._wipe()
    assert (root / "precious.txt").exists()


def test_session_wipe_clears_read_only_leftovers(tmp_path):
    """An engine that died mid-incident leaves the Judge's lock behind."""
    import stat

    root = tmp_path / "live"
    locked = root / "district" / "share" / "exports" / "epos.csv"
    locked.parent.mkdir(parents=True)
    locked.write_text("x", encoding="utf-8")
    locked.chmod(stat.S_IREAD)
    LiveSession(lp.SessionPaths(root), ["python", "-c", "pass"])._wipe()
    assert not root.exists()


@pytest.mark.skipif(sys.platform != "win32",
                    reason="only Windows refuses to delete an open file")
def test_session_wipe_never_leaves_the_old_run_behind_silently(tmp_path):
    """A file something still holds open cannot be deleted on Windows. A
    fresh run must not be built on top of the old one's leftovers."""
    root = tmp_path / "live"
    held = root / "district" / "logs" / "watcher.jsonl"
    held.parent.mkdir(parents=True)
    with open(held, "w", encoding="utf-8"):
        session = LiveSession(lp.SessionPaths(root), ["python", "-c", "pass"])
        with pytest.raises(SessionFolderRefused):
            session._wipe()


def test_session_writes_controls_the_engine_can_read(tmp_path):
    paths = lp.SessionPaths(tmp_path / "live")
    paths.engine.mkdir(parents=True)
    session = LiveSession(paths, ["python", "-c", "pass"])
    session.set_harvest_surge(True)
    session.request_attack("fast")
    control = lp.read_json(paths.control)
    assert control["harvest_surge"] is True
    assert control["attack"]["variant"] == "fast"
    first_id = control["attack"]["id"]
    session.request_attack("fast")
    assert lp.read_json(paths.control)["attack"]["id"] != first_id


def test_a_dead_engine_is_not_shown_as_learning(tmp_path):
    paths = lp.SessionPaths(tmp_path / "live")
    lp.write_json(paths.status, {"phase": lp.LEARNING,
                                 "attack_readiness": lp.ATTACK_READY})
    session = LiveSession(paths, ["python", "-c", "pass"])
    status = session.status()
    assert status["phase"] == lp.FAILED
    assert status["attack_readiness"] == lp.ATTACK_NOT_RUNNING
