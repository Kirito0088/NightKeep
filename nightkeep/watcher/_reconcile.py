"""Deterministic filesystem reconciliation for the Watcher.

Native file notifications -- ReadDirectoryChangesW on Windows, delivered
through watchdog -- can drop events when a burst of activity changes
dozens of files faster than the kernel buffer drains. A fast ransomware
simulator encrypting and renaming a whole export folder in under a second
is exactly that burst: the Judge then sees one stray event instead of
eighty and a real attack reads as NORMAL.

The reconciler is the deterministic backstop for that loss. It
periodically enumerates the watched tree, diffs the enumeration against
the previous one, and reports the create / modify / rename / delete
activity the native stream missed. Native events stay the low-latency
path; the Watcher deduplicates reconciled changes against what the native
handler already recorded, so a change is never reported twice for the
same sweep window.

Nothing here reads file contents and nothing here touches logs/_truth/:
it records that a path appeared, changed, or disappeared, and how big it
is now -- the same facts the native handler records. Rename pairing is
deliberately narrow (same directory, created name starts with the deleted
name, e.g. quota.csv -> quota.csv.locked): that is the shape a
file-locking threat's rename burst takes, and guessing beyond it would
manufacture evidence rather than recover it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from nightkeep.types import CREATED, DELETED, MODIFIED, RENAMED

# Top-level folders inside the watched root the simulator never enters.
# The reconciler skips them exactly as it skips the truth folder and the
# heartbeat: reconciling them could only synthesize bookkeeping noise,
# never attack evidence, because the threat model cannot write there.
OFF_LIMITS_TOP_LEVELS = frozenset({"logs", "data", ".nightkeep-sim"})

# One entry per relative posix path: (mtime_ns, size).
Snapshot = dict[str, tuple[int, int]]


@dataclass(frozen=True)
class Change:
    """One tree difference between two enumerations.

    `path` is absolute; for a rename it is the destination -- the file
    that exists now -- and `old_path` is the absolute source.
    """

    kind: str
    path: Path
    old_path: Path | None = None


def take_snapshot(
    root: Path, is_ignored: Callable[[Path], bool]
) -> Snapshot:
    """Enumerate every non-ignored file under `root`.

    Directories are pruned through `is_ignored` too, so off-limits trees
    are never descended into.
    """
    snapshot: Snapshot = {}
    _walk(root, root, is_ignored, snapshot)
    return snapshot


def _walk(
    current: Path,
    root: Path,
    is_ignored: Callable[[Path], bool],
    snapshot: Snapshot,
) -> None:
    try:
        entries = list(os.scandir(current))
    except OSError:
        return
    for entry in entries:
        path = Path(entry.path)
        try:
            if entry.is_dir(follow_symlinks=False):
                if is_ignored(path):
                    continue
                _walk(path, root, is_ignored, snapshot)
            elif entry.is_file(follow_symlinks=False):
                if is_ignored(path):
                    continue
                try:
                    stat = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                snapshot[path.relative_to(root).as_posix()] = (
                    stat.st_mtime_ns,
                    stat.st_size,
                )
        except OSError:
            continue


def _split(relative: str) -> tuple[str, str]:
    parent, _, name = relative.rpartition("/")
    return parent, name


def diff_snapshots(old: Snapshot, new: Snapshot, root: Path) -> list[Change]:
    """The deterministic diff: created, modified, renamed, deleted.

    A delete paired with a create in the same directory, where the
    created name starts with the deleted name, is reported as one rename
    (quota.csv -> quota.csv.locked). Each side of a pair is used at most
    once, and pairing is greedy over sorted names so it is stable.
    """
    changes: list[Change] = []
    for relative in sorted(new):
        if relative in old and new[relative] != old[relative]:
            changes.append(Change(MODIFIED, root / relative))

    created = sorted(rel for rel in new if rel not in old)
    deleted = sorted(rel for rel in old if rel not in new)
    unmatched = list(created)
    for relative in deleted:
        parent, name = _split(relative)
        match: str | None = None
        for candidate in unmatched:
            candidate_parent, candidate_name = _split(candidate)
            if (
                candidate_parent == parent
                and candidate_name != name
                and candidate_name.startswith(name)
            ):
                match = candidate
                break
        if match is None:
            changes.append(Change(DELETED, root / relative))
        else:
            unmatched.remove(match)
            changes.append(
                Change(RENAMED, root / match, old_path=root / relative)
            )
    for relative in unmatched:
        changes.append(Change(CREATED, root / relative))
    return changes


class TreeReconciler:
    """Periodic enumeration diffing, driven by the Watcher.

    Holds the previous enumeration; each `sweep()` takes a new one and
    returns the changes since the last sweep. The Watcher calls this from
    its reconciliation thread and deduplicates the result against native
    events before recording.
    """

    def __init__(
        self, root: Path, is_ignored: Callable[[Path], bool]
    ) -> None:
        self._root = root
        self._is_ignored = is_ignored
        self._snapshot = take_snapshot(root, is_ignored)

    def sweep(self) -> list[Change]:
        """Enumerate now and return the changes since the previous sweep."""
        new = take_snapshot(self._root, self._is_ignored)
        changes = diff_snapshots(self._snapshot, new, self._root)
        self._snapshot = new
        return changes
