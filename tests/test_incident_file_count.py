"""The affected-file count uses one identity per physical file.

The simulator encrypts a file in place (MODIFIED on its original path)
and then renames it (RENAMED to the .locked name): two events, one file.
The rename's source path is the identity. These are pure unit tests on
the demo runner's report helper; the Judge's detection never sees it.
"""

from datetime import datetime, timezone

from nightkeep.demo_run import _canonical_affected_path
from nightkeep.types import CREATED, MODIFIED, RENAMED, Event


def _event(kind: str, path: str, old_path: str | None = None) -> Event:
    return Event(
        path=path,
        kind=kind,
        at=datetime.now(timezone.utc),
        old_path=old_path,
    )


def _count(events: list[Event]) -> int:
    return len({_canonical_affected_path(e) for e in events})


def test_modify_then_rename_counts_as_one_file():
    events = [
        _event(MODIFIED, "share/exports/day_end_00.csv"),
        _event(
            RENAMED,
            "share/exports/day_end_00.csv.locked",
            old_path="share/exports/day_end_00.csv",
        ),
    ]
    assert _count(events) == 1


def test_distinct_files_count_distinctly():
    events = [
        _event(MODIFIED, "share/exports/day_end_00.csv"),
        _event(
            RENAMED,
            "share/exports/day_end_00.csv.locked",
            old_path="share/exports/day_end_00.csv",
        ),
        _event(MODIFIED, "share/exports/day_end_01.csv"),
        _event(CREATED, "share/exports/HOW_TO_GET_YOUR_FILES_BACK.txt"),
    ]
    assert _count(events) == 3


def test_rename_without_source_falls_back_to_path():
    events = [_event(RENAMED, "share/exports/day_end_00.csv.locked")]
    assert _count(events) == 1
    assert _canonical_affected_path(events[0]) == (
        "share/exports/day_end_00.csv.locked"
    )
