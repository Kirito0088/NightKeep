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
"""

import threading
import time
from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timezone

import psutil


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
        self._root = root.lower()
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
        """One sweep. Public so a test can drive it without a real timer."""
        now = datetime.now(timezone.utc)
        found: list[Sighting] = []
        for process in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                cmdline = process.info["cmdline"] or ()
                if any(self._root in str(part).lower() for part in cmdline):
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
