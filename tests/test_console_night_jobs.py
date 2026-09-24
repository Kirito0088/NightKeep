"""The Night Jobs screen: the six jobs, what Nightkeep learned, how runs went.

Driven by an engine status of the shape nightkeep.live writes. The screen
words the status; it never judges or learns anything itself.
"""

from __future__ import annotations

from pathlib import Path

from nightkeep import live_protocol as lp
from nightkeep.config import load_config
from nightkeep.console.__main__ import create_console_app
from nightkeep.console.live_view import JOB_PURPOSES, night_jobs
from nightkeep.console.providers import JOB_LABELS, _usually

from tests.test_console_live import FakeSession, learning_status

CONFIG = load_config(Path(__file__).resolve().parent.parent / "nightkeep" / "config.yaml")
JOBS = tuple(vars(CONFIG.jobs))


def job(name, runs_seen=0, has_card=False, last_day=None, level=None, card=None):
    return {
        "job": name, "runs_seen": runs_seen, "has_card": has_card,
        "card": card or {}, "last_day": last_day,
        "last_sim_start": "01:42" if last_day else None,
        "last_level": level, "last_reasons": [],
    }


def present(status):
    return night_jobs(status, JOB_LABELS, _usually)


def test_every_configured_job_has_a_plain_name_and_purpose():
    for name in JOBS:
        assert name in JOB_LABELS
        assert JOB_PURPOSES.get(name)


def test_learning_status_moves_from_unseen_to_learned():
    status = learning_status(jobs=[
        job("nightly_export"),
        job("allocation_gen", runs_seen=2, last_day=2),
        job("db_backup", runs_seen=4, has_card=True, last_day=4,
            card={"start_minute": [95.0, 20.0], "files_created": [3.0, 1.0]}),
    ])
    rows = present(status).rows
    assert rows[0].learning == "Not seen yet"
    assert rows[0].last_run == "Not run yet"
    assert rows[1].learning == "Learning: seen 2 times"
    assert rows[1].last_check == "Learning, not judged"
    assert rows[2].learning == "Habit card ready: seen 4 times"
    assert rows[2].usually.startswith("around 01:35")
    assert rows[2].last_run == "Day 4 at 01:42"


def test_after_the_learning_days_jobs_read_as_learned_and_checked():
    status = learning_status(
        phase=lp.GUARD,
        day={"number": 9, "done": 8, "learning_days": 7, "guard_days": 3},
        jobs=[job("fix_dat", runs_seen=7, has_card=True, last_day=8, level="ODD",
                  card={"start_minute": [200.0, 60.0]})],
        checks={"nights_checked": 6, "odd": 1, "incidents": 0,
                "recent": [{"day": 8, "job": "fix_dat", "level": "ODD",
                            "reasons": ["started later than usual"]}]},
    )
    page = present(status)
    assert page.rows[0].learning == "Learned from 7 runs"
    assert page.rows[0].last_check == "Odd, not blocked"
    assert page.rows[0].last_check_tone == "review"
    assert page.headline == "Nightkeep has learned the night jobs and is checking every run."
    assert "6 night job runs checked since day 8. 0 alarms. 1 odd runs" in page.detail
    assert page.tone == "safe"
    assert page.recent[0].name == "Data format maintenance"
    assert page.recent[0].why == "started later than usual"


def test_running_job_is_named_plainly():
    status = learning_status(running_job={"job": "nightly_export", "day": 3,
                                          "sim_start": "01:42"})
    assert present(status).running_now == (
        "Running now: Day-end upload, started 01:42 on day 3."
    )


def test_an_attack_turns_the_screen_red():
    status = learning_status(phase=lp.CONTAINED, lock_held=True)
    page = present(status)
    assert page.tone == "incident"
    assert page.headline == "Night jobs are stopped while the records are protected."


def test_night_jobs_route_renders_the_live_status(tmp_path):
    session = FakeSession(tmp_path / "live", learning_status(jobs=[
        job(name, runs_seen=1, last_day=1) for name in JOBS
    ]))
    app = create_console_app(CONFIG, session=session)
    html = app.test_client().get("/night-jobs").get_data(as_text=True)
    assert "Nightkeep is learning the office" in html
    for name in JOBS:
        assert JOB_LABELS[name] in html
    assert 'aria-current="page">Night Jobs</a>' in html
    assert 'data-live-url="/live/status.json?scope=all"' in html


def test_night_jobs_is_in_the_nav_on_every_page(tmp_path):
    app = create_console_app(CONFIG, session=FakeSession(tmp_path / "live", learning_status()))
    client = app.test_client()
    for path in ("/", "/safety", "/showcase"):
        html = client.get(path).get_data(as_text=True)
        assert 'href="/night-jobs"' in html
        assert "Live Demo" in html


def test_night_jobs_without_a_session_is_honest():
    html = create_console_app(None).test_client().get("/night-jobs").get_data(as_text=True)
    assert "getting ready" in html
    assert "python -m nightkeep --console" in html


def test_no_em_dash_in_the_night_jobs_copy():
    template = (Path(__file__).resolve().parent.parent / "nightkeep" / "console"
                / "templates" / "night_jobs.html").read_text(encoding="utf-8")
    source = (Path(__file__).resolve().parent.parent / "nightkeep" / "console"
              / "live_view.py").read_text(encoding="utf-8")
    assert "—" not in template
    assert "—" not in source
