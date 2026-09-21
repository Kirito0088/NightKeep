"""The canary signals: S2, S3, S4 and S5.

Every one of these is a fixed rule whose numbers arrive as arguments from
the entrypoint. None of them consults a habit card, and no learning path
reaches into this file.
That is rule 2, and `tests/test_judge.py` holds it by reading this module's
syntax tree rather than trusting the comment you are reading now.

They are live from minute one. On the very first learning night, before any
card exists, a canary file being renamed is still an INCIDENT.
"""

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from nightkeep.judge import entropy_signal
from nightkeep.types import DELETED, MODIFIED, RENAMED, Event, Signal

# Nothing under here may ever be opened, by anything, for any reason.
_TRUTH_FOLDER = "_truth"

# S5 looks inside files this size and under. A short note or a batch script
# is a few hundred bytes; a database is not, and reading one in to grep it
# would be both slow and pointless.
TEXT_SAMPLE_BYTES = 32 * 1024


@dataclass(frozen=True)
class Reading:
    """What judge measured when it looked at one file on disk."""

    path: str
    entropy: float
    existed_before: bool


def _safe_to_read(root: Path, relative: str) -> Path | None:
    """A path inside root, refusing anything under the truth folder.

    Checked lexically rather than with `Path.resolve()`. An attack produces
    thousands of events in a few seconds and resolving each one costs a
    round trip to the filesystem; the watcher already hands out paths
    relative to the root, so a `..` component is the only way out and
    rejecting it outright is both cheaper and stricter.
    """
    parts = PurePosixPath(relative).parts
    if _TRUTH_FOLDER in parts or ".." in parts:
        return None
    candidate = root / relative
    try:
        return candidate if candidate.is_file() else None
    except OSError:
        return None


def _read_sample(path: Path, limit: int = entropy_signal.SAMPLE_BYTES) -> bytes:
    try:
        with path.open("rb") as handle:
            return handle.read(limit)
    except OSError:
        return b""


# --- S2: a canary file was touched -------------------------------------------


def canary_touched(events: list[Event], canaries: tuple[str, ...]) -> Signal | None:
    """S2. A decoy that looks like a real export, that no job ever touches.

    Changing, renaming or deleting one fires. Reading one does not, which is
    why the watcher reporting only writes is the right input here.
    """
    watched = {name.strip().lower() for name in canaries}
    for event in events:
        if event.kind not in (MODIFIED, RENAMED, DELETED):
            continue
        for candidate in (event.old_path, event.path):
            if candidate and candidate.lower() in watched:
                did = {MODIFIED: "changed", RENAMED: "renamed",
                       DELETED: "deleted"}[event.kind]
                return Signal(
                    code="S2",
                    title="Canary file changed",
                    reason=(
                        f"a decoy file that no night task ever touches was "
                        f"{did} ({candidate})"
                    ),
                    is_canary=True,
                )
    return None


# --- S3: an existing file was scrambled in place ---------------------------


def scrambled_in_place(
    events: list[Event],
    root: Path,
    baseline,
    entropy_jump: float,
    entropy_floor: float,
) -> tuple[Signal | None, list[Reading]]:
    """S3, asked of `entropy_signal` for each rewritten file.

    Returns the signal and every reading taken, because judge folds the
    readings back into the baseline when the verdict turns out to be quiet.
    """
    readings: list[Reading] = []
    fired: list[str] = []

    for event in events:
        if event.kind not in (MODIFIED, RENAMED):
            continue
        path = _safe_to_read(root, event.path)
        if path is None:
            continue

        # The extension that MEANS something. A file renamed from quota.csv
        # to quota.csv.locked has not stopped being a CSV, and judging it as
        # a .locked file would prove nothing.
        original = event.old_path or event.path
        extension = PurePosixPath(original).suffix.lower()

        data = _read_sample(path)
        before = baseline.entropy_of(original) or baseline.entropy_of(event.path)
        existed = event.kind == RENAMED or before is not None

        result = entropy_signal.inspect(
            data=data,
            extension=extension,
            was_existing=existed,
            entropy_before=before,
            entropy_jump=entropy_jump,
            entropy_floor=entropy_floor,
        )
        readings.append(
            Reading(path=event.path, entropy=result.entropy_after,
                    existed_before=existed)
        )
        if result.fired:
            fired.append(event.path)

    if not fired:
        return None, readings

    first = fired[0]
    more = (
        f" and {len(fired) - 1:,} other file{'' if len(fired) == 2 else 's'}"
        if len(fired) > 1 else ""
    )
    return (
        Signal(
            code="S3",
            title="Files overwritten with scrambled content",
            reason=(
                f"{len(fired):,} existing file{'' if len(fired) == 1 else 's'} "
                f"were overwritten and can no longer be read ({first}{more})"
            ),
            is_canary=True,
        ),
        readings,
    )


# --- S4: a burst of renames to an extension nobody has ever produced -------


def mass_rename(
    events: list[Event], seen_extensions: frozenset[str], burst: int
) -> Signal | None:
    """S4. Renaming in bulk is how a file-locking threat announces itself.

    "Unseen" means no job on this machine has ever produced that extension.
    That is a fact about what has been observed, not a learned threshold, so
    consulting it does not make this canary signal learned: `burst` comes from
    config and nothing can move it.
    """
    unseen: dict[str, int] = {}
    for event in events:
        if event.kind != RENAMED:
            continue
        extension = PurePosixPath(event.path).suffix.lower()
        if not extension or extension in seen_extensions:
            continue
        unseen[extension] = unseen.get(extension, 0) + 1

    for extension, count in sorted(unseen.items(), key=lambda pair: -pair[1]):
        if count >= burst:
            return Signal(
                code="S4",
                title="Files renamed in bulk",
                reason=(
                    f"{count:,} files were renamed to {extension}, a file "
                    f"type no night task has ever produced"
                ),
                is_canary=True,
            )
    return None


# --- S5: system-restore-deletion command text -------------------------------------


def restore_deletion(
    events: list[Event],
    root: Path,
    commands: tuple[str, ...],
    command_lines: tuple[str, ...] = (),
) -> Signal | None:
    """S5. The text that destroys a Windows machine's own recovery.

    Nightkeep never runs these commands, and neither does the simulator: it
    echoes them, which is exactly what this looks for. Matched in the
    contents of small files that were just written, and in the command line
    of anything currently running.
    """
    needles = tuple(command.lower() for command in commands)

    for line in command_lines:
        lowered = line.lower()
        for needle in needles:
            if needle in lowered:
                return Signal(
                    code="S5",
                    title="Something tried to destroy the recovery options",
                    reason=(
                        f'a running program\'s instructions contain "{needle}", '
                        f"which deletes the computer's own ability to recover"
                    ),
                    is_canary=True,
                )

    for event in events:
        if event.kind == DELETED or event.size > TEXT_SAMPLE_BYTES:
            continue
        path = _safe_to_read(root, event.path)
        if path is None:
            continue
        try:
            text = _read_sample(path, TEXT_SAMPLE_BYTES).decode("utf-8", "ignore").lower()
        except OSError:
            continue
        for needle in needles:
            if needle in text:
                return Signal(
                    code="S5",
                    title="Something tried to destroy the recovery options",
                    reason=(
                        f'a file written tonight contains "{needle}", which '
                        f"deletes the computer's own ability to recover "
                        f"({event.path})"
                    ),
                    is_canary=True,
                )
    return None
