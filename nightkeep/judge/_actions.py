"""What judge is allowed to do, and how to put it all back.

Every action here is reversible by construction. Suspend, never kill: a
suspended process can be resumed and its work inspected, a killed one is
gone along with the evidence. Read-only, never delete: a wrong call costs a
few minutes of a clerk's time, not a district's records.

That is the whole point of the ODD verdict existing. Nightkeep is going to
be wrong sometimes, on an erratic system by design, and the cost of being
wrong has to stay small enough that nobody turns it off.
"""

import stat
from dataclasses import dataclass, field
from pathlib import Path

import psutil

from nightkeep.types import HEARTBEAT_FILENAME


@dataclass
class Taken:
    """The actions taken for one incident, and everything needed to undo them."""

    suspended: list[int] = field(default_factory=list)
    made_read_only: list[Path] = field(default_factory=list)
    descriptions: list[str] = field(default_factory=list)

    @property
    def undone(self) -> bool:
        return not self.suspended and not self.made_read_only


def suspend_process(pid: int, taken: Taken) -> bool:
    """Pause a process and the processes it started.

    Returns whether it was still there to pause. The children go too: a
    program that hands the writing to a child (a staged script, a shell)
    would otherwise keep changing files while only its parent sits paused.
    Children are paused first, so none of them keeps running under a
    parent that is already frozen.
    """
    try:
        process = psutil.Process(pid)
        name = process.name()
        try:
            family = process.children(recursive=True)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            family = []
        for child in reversed(family):
            try:
                child.suspend()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            taken.suspended.append(child.pid)
        process.suspend()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False
    taken.suspended.append(pid)
    taken.descriptions.append(f"paused the program that was changing files ({name})")
    return True


def make_read_only(folder: Path, taken: Taken) -> int:
    """Take the write bit off every file in a folder, and remember which.

    On Windows a read-only *folder* does not stop its contents being
    rewritten, so this walks the files. That is slower and it is the only
    version that actually holds.

    The Watcher's liveness heartbeat (and its atomic-write temp sibling)
    is never locked: on Windows the agent replaces that file with
    os.replace(), which fails against a read-only destination and would
    kill the agent right after containment, manufacturing a false S6.
    """
    folder = Path(folder)
    if not folder.is_dir():
        return 0
    changed = 0
    for path in sorted(folder.rglob("*")):
        if not path.is_file():
            continue
        if path.name == HEARTBEAT_FILENAME or path.name.startswith(
            HEARTBEAT_FILENAME + "."
        ):
            # The liveness heartbeat belongs to the Vault's S6 witness, not
            # to the data being protected. Locking it would silence the
            # agent that is still supposed to be watching.
            continue
        try:
            mode = path.stat().st_mode
            if not mode & stat.S_IWRITE:
                continue
            path.chmod(stat.S_IREAD)
        except OSError:
            continue
        taken.made_read_only.append(path)
        changed += 1
    if changed:
        taken.descriptions.append(
            f"locked the records folder so nothing else can change it "
            f"({changed:,} files)"
        )
    return changed


def undo(taken: Taken) -> list[str]:
    """Put everything back. Safe to call twice."""
    undone: list[str] = []

    for pid in list(taken.suspended):
        try:
            psutil.Process(pid).resume()
            undone.append(f"resumed the program that was paused (pid {pid})")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            undone.append(f"the paused program had already ended (pid {pid})")
        taken.suspended.remove(pid)

    restored = 0
    for path in list(taken.made_read_only):
        try:
            path.chmod(stat.S_IWRITE | stat.S_IREAD)
            restored += 1
        except OSError:
            pass
        taken.made_read_only.remove(path)
    if restored:
        undone.append(f"unlocked the records folder ({restored:,} files)")

    # The taken is now empty: the next incident starts with a clean slate
    # instead of re-reporting these actions.
    taken.descriptions.clear()

    return undone


def is_read_only(path: Path) -> bool:
    return not Path(path).stat().st_mode & stat.S_IWRITE
