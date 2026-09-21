"""The shared types, and the invariants they refuse to let anyone break.

These dataclasses are the only thing that crosses the PDS server / Vault
boundary, so the cheapest place to enforce two of the three rules is in the
type itself: a Verdict cannot be constructed as an INCIDENT without a
tripwire, and a SUSPECT snapshot cannot be constructed as a clean point.
"""

from datetime import datetime, timedelta

import pytest

from nightkeep.types import (
    CLEAN,
    INCIDENT,
    NORMAL,
    SUSPECT,
    Check,
    Event,
    HabitScore,
    JobRun,
    RestoreResult,
    Signal,
    Snapshot,
    Verdict,
)

AT = datetime(2026, 9, 22, 3, 41, 12)

LEARNED = Signal(
    code="S1",
    title="Unusual job",
    reason="wrote 4,812 files, usually 240 give or take 60",
    is_canary=False,
)
TRIPWIRE = Signal(
    code="S2",
    title="Canary file changed",
    reason="a decoy export no job ever touches was renamed",
    is_canary=True,
)


def test_an_event_must_name_a_kind_the_watcher_can_actually_see():
    with pytest.raises(ValueError, match="event kind"):
        Event(path="share/exports/a.csv", kind="encrypted", at=AT)


def test_a_habit_score_outside_zero_to_one_is_refused():
    with pytest.raises(ValueError, match="0 to 1"):
        HabitScore(value=1.4)


def test_a_job_run_knows_how_long_it_took():
    run = JobRun(
        job="nightly_export",
        identity="python|jobs/nightly_export.py|abc123",
        started_at=AT,
        finished_at=AT + timedelta(seconds=90),
    )
    assert run.seconds == 90


def test_an_incident_without_a_tripwire_cannot_be_constructed():
    """Rule 1, at the boundary.

    The learned habit score never pauses, locks or deletes anything on its
    own. A caller who tried to raise an INCIDENT on S1 alone gets a
    TypeError-shaped refusal here, before judge is even reached.
    """
    with pytest.raises(ValueError, match="canary"):
        Verdict(level=INCIDENT, signals=(LEARNED,))


def test_an_incident_with_a_tripwire_is_fine():
    verdict = Verdict(
        level=INCIDENT,
        reasons=("a decoy export no job ever touches was renamed",),
        actions=("paused the program", "made the data folder read-only"),
        signals=(LEARNED, TRIPWIRE),
    )
    assert verdict.level == INCIDENT


def test_a_quiet_verdict_needs_no_signals_at_all():
    assert Verdict(level=NORMAL).signals == ()


def test_an_unknown_verdict_level_is_refused():
    with pytest.raises(ValueError, match="verdict level"):
        Verdict(level="PANIC")


def test_a_suspect_snapshot_can_never_be_pinned_as_a_clean_point():
    """A backup taken mid-attack must not be able to poison recovery."""
    with pytest.raises(ValueError, match="clean point"):
        Snapshot(
            snapshot_id="snap-0009",
            taken_at=AT,
            health=SUSPECT,
            file_count=12,
            total_bytes=4096,
            manifest_hash="deadbeef",
            is_clean_point=True,
        )


def test_a_clean_snapshot_may_be_pinned():
    snapshot = Snapshot(
        snapshot_id="snap-0008",
        taken_at=AT,
        health=CLEAN,
        file_count=12,
        total_bytes=4096,
        manifest_hash="deadbeef",
        is_clean_point=True,
    )
    assert snapshot.is_clean_point


def test_a_restore_reports_whether_every_record_came_back():
    result = RestoreResult(
        ok=True,
        snapshot_id="snap-0008",
        restored_to="demo/restored",
        records_verified=5000,
        records_expected=5000,
        checks=(Check("Every one of the 5,000 ration cards is present and readable.", True),),
    )
    assert result.all_records_verified

    short = RestoreResult(
        ok=False,
        snapshot_id="snap-0008",
        restored_to="demo/restored",
        records_verified=4963,
        records_expected=5000,
    )
    assert not short.all_records_verified


def test_every_shared_type_is_frozen():
    """Nothing handed across the boundary may be edited by the receiver."""
    verdict = Verdict(level=NORMAL)
    with pytest.raises(Exception):
        verdict.level = INCIDENT  # type: ignore[misc]
