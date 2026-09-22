"""The demo runner, end to end: the four proofs, from one real seeded run.

Slow, because it starts a real Watcher, runs the six jobs as subprocesses
across the learning and guard nights, runs the simulator, and pulls and
restores from a real Vault. That is the point: nothing here is faked, so if
this passes, the numbers the console shows are numbers a run produced.

Kept small: a 40-card district, seven learning nights (the fewest that give
every nightly job a habit card), one guard night, a one-second day. Skip it
in the fast pre-commit gate with `-m "not slow"`.
"""

from dataclasses import replace
from pathlib import Path

import shutil
from uuid import uuid4

import pytest

from nightkeep import demo, simulator
from nightkeep.config import District, Span, load_config

CONFIG = Path(__file__).resolve().parent.parent / "nightkeep" / "config.yaml"


@pytest.fixture(scope="module")
def result():
    base = load_config(CONFIG)
    config = replace(
        base,
        district=replace(base.district, ration_cards=40, fps_count=4),
        clock=replace(base.clock, learning_days=7, guard_days=1, simulated_day_seconds=1),
        watcher=replace(base.watcher, settle_seconds=0.2),
    )
    out = simulator.DEMO_DIR / ".sim-tests" / f"test-demo-{uuid4().hex}"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)
    try:
        res = demo.run_demo(config=config, out_dir=out, variant="fast")
        res._test_out_dir = out
        yield res
    finally:
        shutil.rmtree(out, ignore_errors=True)


@pytest.mark.slow
def test_p1_no_false_incidents_over_the_guard_nights(result):
    """Weird legacy jobs do not raise a single INCIDENT."""
    assert result.proofs["p1_false_incidents"] == 0
    assert all(v["level"] != "INCIDENT" for v in result.guard_verdicts)


@pytest.mark.slow
def test_p1_the_weird_but_fine_beat_reads_as_odd(result):
    """The catch-up upload is unusual but harmless: exactly one ODD, no block."""
    assert result.proofs["p1_odd_beat"] is True
    assert result.proofs["p1_odd_cards"] >= 1
    odd = [v for v in result.guard_verdicts if v["level"] == "ODD"]
    assert any(v.get("surprise") for v in odd), "the legit surprise should be an ODD"


@pytest.mark.slow
def test_p2_the_threat_test_is_caught_fast_and_early(result):
    """INCIDENT, well under the MVP's 50 files and 10 seconds."""
    assert result.proofs["p2_verdict"] == "INCIDENT"
    assert 1 <= result.proofs["p2_files_before_incident"] < 50
    assert result.proofs["p2_detection_seconds"] < 10
    assert {"S3", "S4"} & {s["code"] for s in result.attack["signals"]}


@pytest.mark.slow
def test_detection_stops_the_scramble_where_it_stood(result):
    """The reversible pause halts the damage rather than watching it finish.

    Because the demo stops the simulator the moment it is caught, the number
    of files scrambled equals the number touched before the incident: there
    is no further damage after detection.
    """
    assert result.attack["files_scrambled"] == result.proofs["p2_files_before_incident"]


@pytest.mark.slow
def test_p3_the_scrambled_copy_is_suspect_and_a_clean_point_is_pinned(result):
    """The backup survives: the bad pull is SUSPECT, the last clean one pinned."""
    assert result.proofs["p3_attack_snapshot_health"] == "SUSPECT"
    assert result.proofs["p3_clean_point"] is not None
    pinned = [s for s in result.snapshots if s["is_clean_point"]]
    assert len(pinned) == 1
    assert pinned[0]["health"] == "CLEAN"


@pytest.mark.slow
def test_p4_every_record_is_verified_after_restore(result):
    """Recovery is proven: 40 of 40 cards, every check passed."""
    assert result.proofs["p4_ok"] is True
    assert result.proofs["p4_records_verified"] == 40
    assert result.proofs["p4_records_verified"] == result.proofs["p4_records_expected"]
    assert all(check["passed"] for check in result.restore["checks"])


@pytest.mark.slow
def test_the_run_writes_a_report_the_console_can_read(result):
    """The result carries a console-ready line per night task."""
    assert len(result.night_tasks) == 6
    assert all(task["task_name"] for task in result.night_tasks)
    assert set(result.habit_cards).issubset(set(demo.FRIENDLY_NAMES))


@pytest.mark.slow
def test_the_report_file_is_valid_json_on_disk(result):
    """The file the console reads is real JSON, not just the in-memory result."""
    import json

    # The module-scoped run wrote under its own out_dir; find run.json there.
    # (run_demo writes <out_dir>/pds/reports/run.json.)
    found = list(result._test_out_dir.rglob(demo.REPORT_NAME))
    assert found, "run.json was not written anywhere"
    on_disk = json.loads(found[0].read_text(encoding="utf-8"))
    assert on_disk["proofs"]["p4_ok"] is True
    assert on_disk["variant"] == "fast"
