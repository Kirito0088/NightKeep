"""Tests for Feature 3: Filesystem Watcher."""

import ast
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from nightkeep.config import District, Span
from nightkeep.mock_pds import build_district
from nightkeep.mock_pds.clock import SimulatedClock
from nightkeep.mock_pds.scheduler import Scheduler
from nightkeep.types import Event, FileEvent
from nightkeep.watcher import Watcher, events_since, is_alive, set_default_watcher

WATCHER_DIR = Path(__file__).resolve().parent.parent / "nightkeep" / "watcher"

DISTRICT = District(
    ration_cards=30,
    fps_count=5,
    members_per_card=Span(low=1, high=3),
    transactions_per_card_per_month=Span(low=1, high=2),
)


@pytest.fixture(autouse=True)
def cleanup_default_watcher():
    yield
    set_default_watcher(None)


def test_event_dataclass_properties():
    now = datetime(2026, 9, 22, 10, 0, 0)
    evt = Event(
        timestamp=now,
        event_type="created",
        path="exports/transactions.csv",
        is_directory=False,
        extension=".csv",
        size_bytes=1024,
        old_path=None,
    )
    assert evt.timestamp == now
    assert evt.event_type == "created"
    assert evt.path == "exports/transactions.csv"
    assert evt.extension == ".csv"
    assert evt.size_bytes == 1024
    assert FileEvent is Event

    with pytest.raises(Exception):
        evt.event_type = "modified"  # Frozen / immutable


def test_watcher_initialization_and_is_alive(tmp_path):
    watcher = Watcher(root_dir=tmp_path)
    assert not watcher.is_alive()
    assert watcher.log_path == tmp_path / "logs" / "watcher_events.jsonl"

    watcher.start()
    assert watcher.is_alive()

    watcher.stop()
    assert not watcher.is_alive()


def test_file_lifecycle_events(tmp_path):
    watcher = Watcher(root_dir=tmp_path)
    t0 = datetime(2026, 9, 22, 1, 0, 0)

    # 1. Created
    evt1 = Event(
        timestamp=t0,
        event_type="created",
        path="exports/test.csv",
        is_directory=False,
        extension=".csv",
        size_bytes=500,
    )
    watcher.record_event(evt1)

    # 2. Modified
    t1 = t0 + timedelta(minutes=5)
    evt2 = Event(
        timestamp=t1,
        event_type="modified",
        path="exports/test.csv",
        is_directory=False,
        extension=".csv",
        size_bytes=750,
    )
    watcher.record_event(evt2)

    # 3. Moved / Renamed
    t2 = t1 + timedelta(minutes=5)
    evt3 = Event(
        timestamp=t2,
        event_type="moved",
        path="archive/test_old.csv",
        is_directory=False,
        extension=".csv",
        size_bytes=750,
        old_path="exports/test.csv",
    )
    watcher.record_event(evt3)

    # 4. Deleted
    t3 = t2 + timedelta(minutes=5)
    evt4 = Event(
        timestamp=t3,
        event_type="deleted",
        path="archive/test_old.csv",
        is_directory=False,
        extension=".csv",
        size_bytes=0,
    )
    watcher.record_event(evt4)

    all_events = watcher.events_since(t0)
    assert len(all_events) == 4
    assert [e.event_type for e in all_events] == ["created", "modified", "moved", "deleted"]
    assert all_events[2].old_path == "exports/test.csv"
    assert all_events[2].path == "archive/test_old.csv"


def test_events_since_filtering(tmp_path):
    watcher = Watcher(root_dir=tmp_path)
    base = datetime(2026, 9, 22, 2, 0, 0)

    for i in range(5):
        watcher.record_event(
            Event(
                timestamp=base + timedelta(minutes=i * 10),
                event_type="created",
                path=f"file_{i}.txt",
                is_directory=False,
                extension=".txt",
                size_bytes=100 + i,
            )
        )

    # All 5 events
    assert len(watcher.events_since(base)) == 5

    # Events from 2:20 onwards (indices 2, 3, 4)
    cutoff = base + timedelta(minutes=20)
    sub = watcher.events_since(cutoff)
    assert len(sub) == 3
    assert sub[0].path == "file_2.txt"

    # Subsequent queries don't lose events
    sub2 = watcher.events_since(cutoff)
    assert len(sub2) == 3

    # Future cutoff gives empty list
    future = base + timedelta(hours=5)
    assert watcher.events_since(future) == []


def test_events_persisted_to_jsonl(tmp_path):
    watcher = Watcher(root_dir=tmp_path)
    t = datetime(2026, 9, 22, 3, 0, 0)
    watcher.record_event(
        Event(
            timestamp=t,
            event_type="created",
            path="exports/run.csv",
            is_directory=False,
            extension=".csv",
            size_bytes=320,
        )
    )

    log_path = tmp_path / "logs" / "watcher_events.jsonl"
    assert log_path.is_file()
    lines = log_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["event_type"] == "created"
    assert data["path"] == "exports/run.csv"
    assert data["size_bytes"] == 320

    # Test rehydration into a new watcher instance
    watcher2 = Watcher(root_dir=tmp_path)
    loaded = watcher2.events_since(t)
    assert len(loaded) == 1
    assert loaded[0].path == "exports/run.csv"


def test_default_watcher_public_interface(tmp_path):
    watcher = Watcher(root_dir=tmp_path)
    set_default_watcher(watcher)

    assert not is_alive()
    watcher.start()
    assert is_alive()

    t = datetime(2026, 9, 22, 4, 0, 0)
    watcher.record_event(
        Event(
            timestamp=t,
            event_type="created",
            path="doc.pdf",
            is_directory=False,
            extension=".pdf",
            size_bytes=2048,
        )
    )

    evts = events_since(t)
    assert len(evts) == 1
    assert evts[0].path == "doc.pdf"

    watcher.stop()
    assert not is_alive()


def test_watcher_observes_nightly_export(tmp_path):
    out_dir = build_district(20260922, DISTRICT, tmp_path / "district")
    watcher = Watcher(root_dir=out_dir)
    watcher.start()

    clock = SimulatedClock(datetime(2026, 9, 13, 1, 0, 0))
    scheduler = Scheduler(clock, out_dir=out_dir, seed=20260922)

    jobs = scheduler.schedule_day(day_no=1, sim_date=datetime(2026, 9, 13).date())
    export_job = next(j for j in jobs if j.job_name == "nightly_export")

    start_time = datetime.now() - timedelta(seconds=1)
    run = scheduler.execute_job(export_job)
    assert run.exit_code == 0

    # Wait briefly for OS filesystem notification buffer (up to 1.5s max)
    deadline = time.time() + 2.0
    export_events = []
    while time.time() < deadline:
        export_events = [
            e for e in watcher.events_since(start_time)
            if "exports" in e.path and e.extension == ".csv"
        ]
        if export_events:
            break
        time.sleep(0.05)

    watcher.stop()

    assert len(export_events) > 0
    assert any(e.event_type in ("created", "modified") for e in export_events)


def test_watcher_observes_allocation_gen(tmp_path):
    out_dir = build_district(20260922, DISTRICT, tmp_path / "district")
    watcher = Watcher(root_dir=out_dir)
    watcher.start()

    clock = SimulatedClock(datetime(2026, 9, 13, 23, 15, 0))
    scheduler = Scheduler(clock, out_dir=out_dir, seed=20260922)

    jobs = scheduler.schedule_day(day_no=1, sim_date=datetime(2026, 9, 1).date())
    alloc_job = next(j for j in jobs if j.job_name == "allocation_gen")

    start_time = datetime.now() - timedelta(seconds=1)
    run = scheduler.execute_job(alloc_job)
    assert run.exit_code == 0

    # Wait briefly for OS filesystem events
    deadline = time.time() + 2.0
    alloc_events = []
    while time.time() < deadline:
        alloc_events = [
            e for e in watcher.events_since(start_time)
            if "allocations" in e.path and e.extension == ".csv"
        ]
        if alloc_events:
            break
        time.sleep(0.05)

    watcher.stop()

    assert len(alloc_events) > 0
    assert any(e.event_type in ("created", "modified") for e in alloc_events)


def test_no_classification_logic_in_watcher():
    """Verify watcher strictly observes and contains zero verdict classification logic."""
    forbidden_terms = {"NORMAL", "ODD", "SUSPICIOUS", "INCIDENT"}

    for py_file in WATCHER_DIR.glob("*.py"):
        code = py_file.read_text(encoding="utf-8")
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert node.value not in forbidden_terms, (
                    f"Forbidden verdict term '{node.value}' found in {py_file.name}"
                )
