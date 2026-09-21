"""The console loader: real run.json and a real district become real screens.

The console has 82 tests over its rendering with the built-in sample. This
file covers the seam that feeds it a real demo run instead: that run.json
reaches the four Data Safety screens untouched, that the district database
reaches search and card detail, and that a console with no run behind it
still comes up on the sample.
"""

import json
from pathlib import Path

import pytest

from nightkeep.config import District, Span
from nightkeep.console._load import load
from nightkeep.console.app import create_app
from nightkeep.mock_pds import build_district

DISTRICT = District(
    ration_cards=25, fps_count=3,
    members_per_card=Span(low=1, high=4),
    transactions_per_card_per_month=Span(low=1, high=2),
)

RUN = {
    "seed": 20260922,
    "variant": "fast",
    "district": {"ration_cards": 25, "fps_count": 3},
    "learning_days": 7,
    "guard_days": 3,
    "proofs": {
        "p1_false_incidents": 0, "p2_verdict": "INCIDENT",
        "p4_records_verified": 25, "p4_records_expected": 25,
        "p3_clean_point": "snap-0007", "entries_to_recheck": 8,
    },
    "night_tasks": [
        {"job": "nightly_export", "task_name": "Day-end upload",
         "usually": "01:00 to 02:30, writes about 1 files",
         "last_night": "2 file changes", "status": "Normal"},
    ],
    "attack": {
        "variant": "fast", "files_scrambled": 16, "files_renamed": 16,
        "detection_seconds": 0.05, "verdict_level": "INCIDENT",
        "signals": [{"code": "S3", "title": "t", "reason": "r"}],
    },
    "snapshots": [
        {"id": "snap-0007", "taken_at": "2026-09-07T01:20:00", "health": "CLEAN",
         "is_clean_point": True, "file_count": 18, "reasons": ["All fine."]},
        {"id": "snap-0008", "taken_at": "2026-09-08T01:20:00", "health": "SUSPECT",
         "is_clean_point": False, "file_count": 20, "reasons": ["Scrambled."]},
    ],
    "restore": {
        "ok": True, "snapshot_id": "snap-0007",
        "records_verified": 25, "records_expected": 25,
        "checks": [
            {"statement": "Every one of the 25 ration cards is present.", "passed": True},
            {"statement": "All files match their safe copy.", "passed": True},
        ],
        "reasons": ["All checks passed."],
    },
    "timeline": [
        {"title": "Threat test caught", "detail": "Stopped after 1 file."},
    ],
}


@pytest.fixture
def demo_district(tmp_path):
    district = build_district(20260922, DISTRICT, tmp_path / "pds")
    reports = district / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "run.json").write_text(json.dumps(RUN), encoding="utf-8")
    return district


def test_load_returns_nothing_when_there_is_no_run(tmp_path):
    assert load(tmp_path / "nowhere") == {}


def test_a_district_with_no_run_json_still_loads_its_records(tmp_path):
    """The search screen works off the database even before a demo has run."""
    district = build_district(20260922, DISTRICT, tmp_path / "pds")
    kwargs = load(district)

    assert "sample_records" in kwargs
    assert len(kwargs["sample_records"]) == 25
    assert "safety_home_data" not in kwargs  # no run.json, so no Safety screens


def test_every_route_renders_on_a_real_run(demo_district):
    app = create_app(**load(demo_district))
    client = app.test_client()
    first = load(demo_district)["sample_records"][0].card_no

    for route in ("/", "/search", f"/card/{first}", "/locked",
                  "/safety", "/alert", "/restore", "/server-alert"):
        assert client.get(route).status_code == 200, route


def test_the_safety_screen_shows_the_runs_own_numbers(demo_district):
    app = create_app(**load(demo_district))
    page = app.test_client().get("/safety").get_data(as_text=True)

    assert "Your records are safe" in page
    assert "Day-end upload" in page
    assert "01:00 to 02:30" in page  # the learned/scheduled habit, passed through
    assert "1" in page  # one CLEAN snapshot counted as a safe copy


def test_the_restore_checks_come_straight_from_the_run(demo_district):
    app = create_app(**load(demo_district))
    page = app.test_client().get("/restore").get_data(as_text=True)

    assert "Every one of the 25 ration cards is present." in page
    assert "All files match their safe copy." in page


def test_the_clean_point_is_shown_as_a_time_not_a_snapshot_id(demo_district):
    app = create_app(**load(demo_district))
    page = app.test_client().get("/safety").get_data(as_text=True)

    assert "snap-0007" not in page  # never leak the internal id to a clerk
    assert "07 Sep" in page


def test_card_detail_reads_the_real_district(demo_district):
    kwargs = load(demo_district)
    card_no = kwargs["sample_records"][3].card_no

    detail = kwargs["card_details"].get(card_no)

    assert detail is not None
    assert detail.card_no == card_no
    assert detail.members  # a real card has members
    assert detail.mobile_masked.count("X") == 6  # masked, never a real number
    assert "aadhaar" not in detail.__dict__  # no Aadhaar number anywhere


def test_no_console_screen_carries_an_em_dash_on_a_real_run(demo_district):
    app = create_app(**load(demo_district))
    client = app.test_client()
    for route in ("/safety", "/alert", "/restore", "/server-alert"):
        assert "—" not in client.get(route).get_data(as_text=True), route
