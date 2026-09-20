"""What one job run looks like, reduced to numbers a card can hold.

The unit everywhere here is the **file**, not the event. Watchdog fires
several `modified` events for a single write, so counting events would make
a job's habit depend on how the operating system buffered it. Counting
distinct paths is both stable and the thing a person actually means by "it
changed 37 files".
"""

from dataclasses import dataclass
from pathlib import PurePosixPath

from nightkeep.types import CREATED, DELETED, MODIFIED, RENAMED, JobRun

MINUTES_IN_A_DAY = 24 * 60

# The numbers a habit card keeps a median and a MAD for. Anything not in
# here is categorical and handled as a novelty flag instead.
NUMERIC_FEATURES = (
    "files_created",
    "files_modified",
    "files_renamed",
    "files_deleted",
    "folders_touched",
    "bytes_written",
    "start_minute",
)

# How each one reads on a screen. `habit` writes its own reasons, and these
# are the words it uses.
FEATURE_WORDS = {
    "files_created": "created {value:,.0f} files",
    "files_modified": "changed {value:,.0f} files",
    "files_renamed": "renamed {value:,.0f} files",
    "files_deleted": "deleted {value:,.0f} files",
    "folders_touched": "touched {value:,.0f} folders",
    "bytes_written": "wrote {value:,.0f} bytes",
    "start_minute": "started at {clock}",
}


@dataclass(frozen=True)
class Features:
    """One run, as numbers and as sets."""

    numbers: dict[str, float]
    extensions: frozenset[str]
    folders: frozenset[str]
    identity: str


def clock_of(minute: float) -> str:
    """1265.0 -> "21:05". Used in reasons, so it has to read like a clock."""
    minute = int(round(minute)) % MINUTES_IN_A_DAY
    return f"{minute // 60:02d}:{minute % 60:02d}"


def circular_distance(a: float, b: float) -> float:
    """Minutes between two times of day, the short way round the clock.

    The allotment job starts between 23:15 and 00:45. Without this, a run at
    00:20 would look 1,385 minutes away from a median of 23:15 instead of
    the 65 minutes it actually is, and every month-start would be an alarm.
    """
    straight = abs(a - b) % MINUTES_IN_A_DAY
    return min(straight, MINUTES_IN_A_DAY - straight)


def extract(run: JobRun) -> Features:
    """Reduce one job run to its habit features."""
    created: set[str] = set()
    modified: set[str] = set()
    renamed: set[str] = set()
    deleted: set[str] = set()
    folders: set[str] = set()
    extensions: set[str] = set()
    sizes: dict[str, int] = {}

    for event in run.events:
        path = PurePosixPath(event.path)
        folders.add(path.parent.as_posix())
        if path.suffix:
            extensions.add(path.suffix.lower())

        if event.kind == CREATED:
            created.add(event.path)
            sizes[event.path] = event.size
        elif event.kind == MODIFIED:
            modified.add(event.path)
            sizes[event.path] = event.size
        elif event.kind == RENAMED:
            renamed.add(event.path)
            if event.old_path:
                folders.add(PurePosixPath(event.old_path).parent.as_posix())
        elif event.kind == DELETED:
            deleted.add(event.path)

    # A file created and then written to is one created file, not one of each.
    modified -= created

    numbers = {
        "files_created": float(len(created)),
        "files_modified": float(len(modified)),
        "files_renamed": float(len(renamed)),
        "files_deleted": float(len(deleted)),
        "folders_touched": float(len(folders)),
        "bytes_written": float(sum(sizes.values())),
        "start_minute": _start_minute(run),
    }
    return Features(
        numbers=numbers,
        extensions=frozenset(extensions),
        folders=frozenset(folders),
        identity=run.identity,
    )


def _start_minute(run: JobRun) -> float:
    """The simulated time of day the run began, in minutes past midnight.

    Simulated, not real: "later than usual" is a statement about 03:40 on
    the district's clock, not about the wall clock in the demo room.
    """
    when = run.sim_started_at or run.started_at
    return float(when.hour * 60 + when.minute)
