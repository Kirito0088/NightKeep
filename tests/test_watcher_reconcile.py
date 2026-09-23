"""The reconciler: deterministic backstop for dropped native file events.

On Windows, ReadDirectoryChangesW can drop file events when a ransomware
burst changes dozens of files faster than the kernel buffer drains. These
tests prove the reconciliation fallback sees a rapid encrypt+rename burst
-- with no native events delivered at all -- and that the evidence it
synthesizes is enough for a real Judge to reach S2/S3/S4 -> INCIDENT.

The bursts here are real filesystem activity on a scratch tree; only the
*delivery* of native events is bypassed, by driving TreeReconciler (and,
in one test, Watcher._reconcile_once) directly instead of through
watchdog. Nothing is mocked, and no expectation is weakened: the Judge,
the thresholds and the verdict table are the production ones from
tests/test_live_attack.py.
"""

from __future__ import annotations

import random
import time
from datetime import datetime, timezone
from pathlib import Path

from nightkeep.habit import open_habit
from nightkeep.judge import Judge, TRAP_CONTENTS
from nightkeep.types import (
    CREATED,
    INCIDENT,
    MODIFIED,
    RENAMED,
    Event,
    JobRun,
)
from nightkeep.watcher import Watcher
from nightkeep.watcher._reconcile import TreeReconciler

TRAP = "share/exports/aaa_trap.csv"
NOTE_NAME = "HOW_TO_GET_YOUR_FILES_BACK.txt"
COMMANDS = (
    "vssadmin delete shadows",
    "wbadmin delete catalog",
)
FILE_COUNT = 12


def _plant_tree(root: Path) -> None:
    exports = root / "share" / "exports"
    exports.mkdir(parents=True)
    for index in range(FILE_COUNT):
        (exports / f"day_end_{index:02d}.csv").write_text(
            "transaction_id,card_no,quantity_kg\n"
            + "".join(f"{index},{1000 + row},5\n" for row in range(50)),
            encoding="utf-8",
        )
    reports = root / "reports"
    reports.mkdir(parents=True)
    (reports / "monthly_summary.csv").write_text(
        "month,total_kg\n2026-09,12345\n", encoding="utf-8"
    )


def _make_test_judge(root: Path) -> Judge:
    """The same Judge the live-attack tests use: same thresholds, same trap."""
    judge = Judge(
        root=root,
        habit=open_habit(root, 3.0, 5, 0.1),
        odd_score=0.5,
        rename_burst=10,
        entropy_jump=1.5,
        entropy_floor=7.0,
        recovery_commands=COMMANDS,
        canary_files=(TRAP,),
        server_alerts=False,
    )
    judge.plant_traps()
    assert (root / TRAP).read_bytes() == TRAP_CONTENTS
    return judge


def _ransomware_burst(root: Path) -> None:
    """Encrypt in place, rename to .locked, drop ransom notes.

    Synchronous and as fast as the disk goes: no sleeps, mirroring the
    fast simulator with --delay 0. Deterministic content via a fixed
    seed, high-entropy like real scrambled bytes.
    """
    rng = random.Random(20260923)
    targets = sorted(
        path
        for path in root.rglob("*.csv")
        if path.is_file()
    )
    assert len(targets) == FILE_COUNT + 2, [str(p) for p in targets]
    locked: list[Path] = []
    for path in targets:
        path.write_bytes(rng.randbytes(4096))
        renamed = path.with_name(path.name + ".locked")
        path.replace(renamed)
        locked.append(renamed)
    for folder in sorted({path.parent for path in locked}):
        (folder / NOTE_NAME).write_text(
            "NIGHTKEEP DRILL: SIMULATED RANSOMWARE\n", encoding="utf-8"
        )


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _changes_to_events(
    root: Path, changes: list, at: datetime
) -> list[Event]:
    """Reconciled changes as Judge input, with no attribution at all.

    pid=None is the point: requirement 6 says a missing pid must not
    block S2/S3/S4 detection.
    """
    return [
        Event(
            path=_relative(root, change.path),
            kind=change.kind,
            at=at,
            pid=None,
            process=None,
            old_path=(
                _relative(root, change.old_path)
                if change.old_path is not None
                else None
            ),
            size=0,
        )
        for change in changes
    ]


def test_reconciler_reports_a_rapid_encrypt_and_rename_burst(tmp_path):
    """No native events: the sweep alone must see the whole burst."""
    root = tmp_path / "district"
    _plant_tree(root)
    _make_test_judge(root)
    watcher = Watcher(root, reconcile_seconds=0)
    reconciler = TreeReconciler(root, watcher._reconcile_ignored)

    _ransomware_burst(root)
    changes = reconciler.sweep()

    renames = [c for c in changes if c.kind == RENAMED]
    locked = [c for c in renames if c.path.suffix == ".locked"]
    assert len(locked) >= 10, (
        f"expected the rename burst, got {len(locked)} renames: "
        f"{[(c.kind, c.path.name) for c in changes]}"
    )
    # The canary was caught in the blast radius, with its old name kept.
    assert any(
        c.old_path is not None and _relative(root, c.old_path) == TRAP
        for c in renames
    ), [(c.kind, str(c.old_path)) for c in changes]
    # Ransom notes were created.
    assert any(
        c.kind == CREATED and c.path.name == NOTE_NAME for c in changes
    ), [(c.kind, c.path.name) for c in changes]
    # Off-limits trees are never reported, even if walked.
    for change in changes:
        top = _relative(root, change.path).split("/")[0]
        assert top not in ("logs", "data", ".nightkeep-sim"), change


def test_reconciled_evidence_with_no_attribution_still_reaches_incident(
    tmp_path,
):
    """Synthesized events, pid=None throughout: S2/S3/S4 -> INCIDENT."""
    root = tmp_path / "district"
    _plant_tree(root)
    judge = _make_test_judge(root)
    watcher = Watcher(root, reconcile_seconds=0)
    reconciler = TreeReconciler(root, watcher._reconcile_ignored)

    _ransomware_burst(root)
    changes = reconciler.sweep()
    assert changes, "the burst left no reconciled changes at all"

    now = datetime.now(timezone.utc)
    events = _changes_to_events(root, changes, now)
    assert all(e.pid is None for e in events)
    run = JobRun(
        job="simulator",
        identity="simulator|fast|external-process",
        started_at=now,
        finished_at=now,
        events=(),
    )
    verdict = judge.verdict(run, events=events)
    codes = {s.code for s in verdict.signals if s.is_canary}
    assert verdict.level == INCIDENT, (
        verdict.level,
        [(s.code, s.reason) for s in verdict.signals],
    )
    assert "S2" in codes, codes  # the canary was renamed
    assert "S4" in codes, codes  # the .locked rename burst
    assert "S3" in codes, codes  # scrambled in place


def test_reconciler_dedupes_against_native_events(tmp_path):
    """A change the native handler already reported is not synthesized."""
    root = tmp_path / "district"
    _plant_tree(root)
    watcher = Watcher(root, poll_seconds=0.2, reconcile_seconds=0)
    watcher.start()
    try:
        t0 = datetime.now(timezone.utc)
        first = root / "share" / "exports" / "day_end_00.csv"
        first.write_text("changed\n", encoding="utf-8")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if any(
                e.path == "share/exports/day_end_00.csv"
                for e in watcher.events_since(t0)
            ):
                break
            time.sleep(0.05)
        else:
            raise AssertionError("no native event arrived for the write")

        # Silence the native stream: from here only the reconciler speaks.
        watcher._observer.stop()
        watcher._observer.join(timeout=5)

        # Fresh baseline: day_end_00.csv is settled, day_end_01.csv not yet.
        watcher._reconciler = TreeReconciler(
            root, watcher._reconcile_ignored
        )
        second = root / "share" / "exports" / "day_end_01.csv"
        second.write_text("changed\n", encoding="utf-8")
        # Simulate the native handler having reported the modification.
        watcher._record(MODIFIED, second, None)

        synthesized = watcher._reconcile_once()
        assert synthesized == [], [
            (e.kind, e.path) for e in synthesized
        ]

        paths = [
            e.path
            for e in watcher.events_since(t0)
            if e.path.startswith("share/exports/day_end_0")
        ]
        # The native stream may deliver a write twice (inotify does); the
        # point is the reconciler added nothing on top: day_end_01.csv was
        # reported once by the simulated native record, and the sweep --
        # run after the observer was silenced -- synthesized nothing.
        assert paths.count("share/exports/day_end_01.csv") == 1, paths
        assert "share/exports/day_end_00.csv" in paths, paths
    finally:
        watcher.stop()


def test_live_watcher_with_reconciler_catches_a_burst(tmp_path):
    """End to end through a real Watcher: burst -> events -> INCIDENT.

    On Linux the native stream usually delivers; on Windows it may drop
    most of the burst. Either way the Watcher must surface enough
    evidence for the Judge, which is exactly the regression this guards.
    """
    root = tmp_path / "district"
    _plant_tree(root)
    judge = _make_test_judge(root)
    with Watcher(root, poll_seconds=0.2, reconcile_seconds=0.1) as watcher:
        t0 = datetime.now(timezone.utc)
        _ransomware_burst(root)

        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            events = watcher.events_since(t0)
            renames = [
                e
                for e in events
                if e.kind == RENAMED and e.path.endswith(".locked")
            ]
            canary = [
                e
                for e in events
                if e.old_path == TRAP or e.path == TRAP
            ]
            if len(renames) >= 10 and canary:
                break
            time.sleep(0.05)
        else:
            raise AssertionError(
                "the watcher never saw the burst: "
                f"{len(renames)} renames, canary={bool(canary)}"
            )

        run = JobRun(
            job="simulator",
            identity="simulator|fast|external-process",
            started_at=t0,
            finished_at=datetime.now(timezone.utc),
            events=(),
        )
        verdict = judge.verdict(run, events=events)
        codes = {s.code for s in verdict.signals if s.is_canary}
        assert verdict.level == INCIDENT, (
            verdict.level,
            [(s.code, s.reason) for s in verdict.signals],
        )
        assert {"S2", "S4"} <= codes, codes
