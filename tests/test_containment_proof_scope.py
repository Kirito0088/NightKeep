"""The containment proof covers the simulator's real attack surface.

The simulator's blast radius is the whole demo root minus its off-limits
folders; share/ alone is not enough. These tests pin the proof helper to
that surface: it must catch a post-cutoff write anywhere eligible (even
outside share/) and must never flag the watcher's own bookkeeping or the
folders the simulator cannot enter.
"""

import os

from nightkeep import demo_run, simulator
from nightkeep.types import HEARTBEAT_FILENAME


def _district(tmp_path):
    root = tmp_path / "district"
    eligible = [
        root / "share" / "exports" / "day_end.csv",
        root / "reports" / "monthly_summary.csv",
    ]
    off_limits = [
        root / "logs" / "events.csv",
        root / "data" / "district.db",
        root / ".nightkeep-sim" / "staging.bin",
        root / "logs" / "_truth" / "nightly.truth.log",
        root / "share" / HEARTBEAT_FILENAME,
        root / "share" / (HEARTBEAT_FILENAME + ".tmp"),
        root / "logs" / "watcher.jsonl",
    ]
    for path in eligible + off_limits:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"data")
    return root, eligible, off_limits


def _touch_after(path, cutoff: float) -> None:
    os.utime(path, (cutoff + 10, cutoff + 10))


def test_proof_boundary_matches_the_simulators():
    """The proof walks exactly what the simulator can attack. If the
    simulator's boundary ever changes, this fails loudly instead of the
    proof silently covering the wrong surface."""
    assert demo_run._PROOF_OFF_LIMIT_TOP_LEVELS == simulator._OFF_LIMITS
    assert demo_run._PROOF_TRUTH_FOLDER == simulator._TRUTH_FOLDER


def test_write_outside_share_is_caught(tmp_path):
    root, eligible, off_limits = _district(tmp_path)
    cutoff = 1_700_000_000.0
    for path in eligible + off_limits:
        os.utime(path, (cutoff - 60, cutoff - 60))
    # A late write to an eligible file outside share/...
    _touch_after(root / "reports" / "monthly_summary.csv", cutoff)
    found = demo_run._eligible_files_modified_after(root, cutoff)
    assert [str(root / "reports" / "monthly_summary.csv")] == found


def test_off_limits_and_bookkeeping_are_ignored(tmp_path):
    root, eligible, off_limits = _district(tmp_path)
    cutoff = 1_700_000_000.0
    for path in eligible + off_limits:
        _touch_after(path, cutoff)
    found = demo_run._eligible_files_modified_after(root, cutoff)
    assert sorted(found) == sorted(str(p) for p in eligible)


def test_pre_cutoff_writes_are_not_flagged(tmp_path):
    root, eligible, off_limits = _district(tmp_path)
    cutoff = 1_700_000_000.0
    for path in eligible + off_limits:
        os.utime(path, (cutoff - 60, cutoff - 60))
    assert demo_run._eligible_files_modified_after(root, cutoff) == []
