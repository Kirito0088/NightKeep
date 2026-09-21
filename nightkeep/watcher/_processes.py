"""Who is writing right now, asked of psutil on a timer.

Attribution here is "active writer in window", which is the fallback MVP
section 14 names for exactly this problem: linking a file change to a process
is unreliable on Windows without ETW or Sysmon, and both are out of scope.
It is sound in this demo because the scheduler runs one job at a time and
waits for it, so at any instant at most one job process is alive.

A process counts as a candidate writer when its command line mentions the
folder being watched. Every job is launched with `--root <district_dir>`, and
the simulator is pointed at the same folder, so both show up honestly. This
module never reads a file; it only asks the operating system what is running.

Two hard rules keep attribution honest:

1. The watcher agent itself is never a candidate. It runs as
   ``python -m nightkeep.watcher --run --root <district_dir>``, so its
   argv mentions the root -- but it only writes the liveness heartbeat
   and its own event log. Without the exclusion, an attack's events could
   resolve to the agent's pid and the Judge would suspend the wrong
   process. The markers are the agent's actual command-line markers (the
   module name and the dedicated ``--run`` flag, as exact argv elements),
   never a hard-coded pid.
2. The root matches in every spelling a caller can put in its argv: the
   absolute path, the path relative to the current working directory (a
   caller launched with a relative ``--root`` would otherwise degrade to
   pid=None), with case and separators folded so a mixed-case Windows
   drive letter still matches. The match must land on a real path
   boundary, so a sibling directory (``.../district2``) never claims to
   be ``.../district``.
"""

import os
import threading
import time
from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timezone

import psutil


# --- the watcher agent is never a writer --------------------------------------

# The markers the watcher agent actually runs with. The simulator's
# watcher-killer finds the agent by these same markers; here they mean the
# opposite -- exclude, do not kill.
_WATCHER_MODULE = "nightkeep.watcher"
_WATCHER_RUN_FLAG = "--run"


def _is_watcher_agent(cmdline: tuple[str, ...]) -> bool:
    """True when these argv elements belong to the watcher agent.

    Exact element matching, the same markers the watcher-killer uses to
    find the agent. A substring match would be fragile: a folder or a log
    line that merely contains the text ``nightkeep.watcher`` is not the
    agent.
    """
    parts = [str(part) for part in cmdline]
    return _WATCHER_MODULE in parts and _WATCHER_RUN_FLAG in parts


# --- root spellings ------------------------------------------------------------


def _fold(text: str, _nt: bool | None = None) -> str:
    """Fold a path for comparison: case-insensitive, separators normalized.

    ``_nt`` forces the Windows behavior so the mixed-case drive-letter
    spelling is testable on any platform; it defaults to the real one.
    """
    nt = os.name == "nt" if _nt is None else _nt
    folded = str(text).lower()
    return folded.replace("/", "\\") if nt else folded


def _root_spellings(root: str, _nt: bool | None = None) -> tuple[str, ...]:
    """Every spelling the watched root can take inside a process argv.

    Always the absolute spelling. Plus the spelling relative to the
    current working directory, when the root sits under it -- a caller
    launched with a relative ``--root`` puts that spelling in its argv,
    and without it attribution would silently degrade to pid=None. Case
    and separators are folded so ``C:\\Demo`` still matches ``c:/demo``.
    """
    absolute = os.path.abspath(root)
    spellings = {_fold(absolute, _nt)}
    try:
        relative = os.path.relpath(absolute, os.getcwd())
    except ValueError:
        relative = ""
    if relative and relative != "." and not relative.startswith(".."):
        spellings.add(_fold(relative, _nt))
    return tuple(sorted(spellings))


def _mentions_root(
    cmdline: tuple[str, ...],
    spellings: tuple[str, ...],
    _nt: bool | None = None,
) -> bool:
    """The root appears in this argv, at a real path boundary.

    A plain substring match would let ``.../district2`` claim to be
    ``.../district``. The character before the match (if any) must be a
    separator, a drive-letter colon, or nothing, and the character after
    it (if any) must be a separator or the end of the element -- so
    ``--root=/x/district`` matches and ``/x/district2`` does not.
    """
    for part in cmdline:
        text = _fold(part, _nt).strip("\"'")
        for spelling in spellings:
            start = text.find(spelling)
            while start != -1:
                before = text[start - 1] if start > 0 else ""
                after = text[start + len(spelling):start + len(spelling) + 1]
                if before in ("", "/", "\\", ":") and after in ("", "/", "\\"):
                    return True
                start = text.find(spelling, start + 1)
    return False


@dataclass(frozen=True)
class Sighting:
    """One moment at which a process was seen alive and pointed at the root."""

    at: datetime
    pid: int
    name: str


class ProcessPoll:
    """Polls psutil on its own thread and remembers what it saw, in order.

    The list of sightings only grows, and it grows in time order, so looking
    up "who was writing at time t" is a binary search rather than a scan.
    """

    def __init__(self, root: str, poll_seconds: float) -> None:
        self._spellings = _root_spellings(root)
        self._poll_seconds = poll_seconds
        self._sightings: list[Sighting] = []
        self._times: list[datetime] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._polls = 0

    # --- lifecycle --------------------------------------------------------

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, name="nightkeep-process-poll", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self._poll_seconds * 4)

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def polls(self) -> int:
        """How many times psutil has actually been asked. For liveness."""
        return self._polls

    # --- the poll ---------------------------------------------------------

    def _run(self) -> None:
        while not self._stop.is_set():
            self.poll_once()
            self._stop.wait(self._poll_seconds)

    def poll_once(self) -> None:
        """One sweep. Public so a test can drive it without a real timer.

        The watcher agent is skipped before the root is even checked: its
        argv mentions the root (``--root <district_dir>``), but it is never
        a candidate writer.
        """
        now = datetime.now(timezone.utc)
        found: list[Sighting] = []
        for process in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                cmdline = tuple(process.info["cmdline"] or ())
                if _is_watcher_agent(cmdline):
                    continue
                if _mentions_root(cmdline, self._spellings):
                    found.append(
                        Sighting(at=now, pid=process.info["pid"],
                                 name=process.info["name"] or "unknown")
                    )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                # A process that died between listing and asking. Normal.
                continue
        with self._lock:
            for sighting in found:
                self._sightings.append(sighting)
                self._times.append(sighting.at)
            self._polls += 1

    # --- the question the watcher actually asks ---------------------------

    def writer_at(self, when: datetime) -> Sighting | None:
        """The last process seen at or before `when`, if there was one.

        Returns None rather than guessing when nothing was ever seen. An
        unattributed event is honest; a wrong pid is not.
        """
        with self._lock:
            index = bisect_right(self._times, when)
            if index == 0:
                # Nothing seen yet at that moment. The first poll may not have
                # landed before a very fast job wrote its first file, so fall
                # forward to the earliest sighting if one exists at all.
                return self._sightings[0] if self._sightings else None
            return self._sightings[index - 1]


def suspend(pid: int) -> None:
    """Pause a process. Reversible: this is suspend, never kill."""
    psutil.Process(pid).suspend()


def resume(pid: int) -> None:
    """Undo a suspend."""
    psutil.Process(pid).resume()


def is_running(pid: int) -> bool:
    try:
        return psutil.Process(pid).is_running()
    except psutil.NoSuchProcess:
        return False


def wait_for_exit(pid: int, timeout: float) -> None:
    """Best effort, used only to let a test tear down cleanly."""
    deadline = time.monotonic() + timeout
    while is_running(pid) and time.monotonic() < deadline:
        time.sleep(0.01)
