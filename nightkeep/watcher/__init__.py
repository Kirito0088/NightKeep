"""Notices file changes on the PDS server and which process caused them.

Public interface:
    Watcher(root, poll_seconds, settle_seconds)
    events_since(t) -> [Event]
    is_alive()

Hides watchdog wiring, psutil polling, file-to-process attribution and the
append-only log.

The constructor is the only addition to the interface CLAUDE.md lists:
something has to build the object, and a module-level `start()` returning a
handle would be the same function wearing a hat. Everything else stays
behind these two methods.

This module never opens logs/_truth/. It does not read file contents at all:
it records that a file changed, how big it now is, and who was running. What
is *inside* a file is judge's question, asked of the file on disk.
"""

import threading
from datetime import datetime, timezone
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from nightkeep.types import CREATED, DELETED, MODIFIED, RENAMED, Event
from nightkeep.watcher._log import LOG_NAME, EventLog
from nightkeep.watcher._processes import ProcessPoll

# The truth logs prove, after the fact, that learning was correct. Nightkeep
# must never be able to see them, not even as a filename. CLAUDE.md makes
# this a hard rail, and tests/test_rails.py holds it.
_TRUTH_FOLDER = "_truth"

_WATCHDOG_KINDS = {
    "created": CREATED,
    "modified": MODIFIED,
    "deleted": DELETED,
    "moved": RENAMED,
}


class _Handler(FileSystemEventHandler):
    """Turns watchdog's events into ours, and asks psutil who was writing."""

    def __init__(self, watcher: "Watcher") -> None:
        self._watcher = watcher

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        kind = _WATCHDOG_KINDS.get(event.event_type)
        if kind is None:
            return
        source = Path(str(event.src_path))
        destination = (
            Path(str(event.dest_path)) if kind == RENAMED and event.dest_path else None
        )
        # For a rename, the file that now exists is the destination.
        landed = destination or source
        self._watcher._record(kind, landed, source if destination else None)


class Watcher:
    """Watches one folder and remembers what changed in it, and who did it.

    Start it with `with Watcher(...) as watcher:` or call start() and stop()
    yourself. Events accumulate in memory and on disk; `events_since` answers
    from memory, which is what judge asks on every job run.
    """

    def __init__(
        self,
        root: Path,
        poll_seconds: float = 2.0,
        settle_seconds: float = 1.0,
    ) -> None:
        self.root = Path(root).resolve()
        self.settle_seconds = settle_seconds
        self._events: list[Event] = []
        self._lock = threading.Lock()
        self._log = EventLog(self.root / "logs" / LOG_NAME)
        self._poll = ProcessPoll(str(self.root), poll_seconds)
        self._observer = Observer()
        self._observer.schedule(_Handler(self), str(self.root), recursive=True)
        self._started = False

    # --- lifecycle --------------------------------------------------------

    def start(self) -> "Watcher":
        self._poll.start()
        # One sweep before any job runs, so the first file written already has
        # somebody to attribute it to.
        self._poll.poll_once()
        self._observer.start()
        self._started = True
        return self

    def stop(self) -> None:
        if not self._started:
            return
        self._observer.stop()
        self._observer.join(timeout=5)
        self._poll.stop()
        self._started = False

    def __enter__(self) -> "Watcher":
        return self.start()

    def __exit__(self, *_: object) -> None:
        self.stop()

    # --- the public interface --------------------------------------------

    def events_since(self, t: datetime) -> list[Event]:
        """Every change seen at or after `t`, oldest first.

        `t` is real wall-clock time, not simulated time: this is the moment a
        file actually changed on disk.
        """
        with self._lock:
            return [event for event in self._events if event.at >= t]

    def events_between(self, start: datetime, end: datetime) -> list[Event]:
        """The changes belonging to one job run.

        The end is stretched by settle_seconds, because a job's last writes
        can land a moment after its process has exited.
        """
        from datetime import timedelta

        limit = end + timedelta(seconds=self.settle_seconds)
        with self._lock:
            return [event for event in self._events if start <= event.at <= limit]

    def is_alive(self) -> bool:
        """Both halves running: the file observer and the process poll.

        This is what the Vault asks in S6. A watcher that has been killed
        answers False, and a watcher that cannot answer at all is the same
        thing from the Vault's side.
        """
        return self._started and self._observer.is_alive() and self._poll.is_alive()

    # --- internals --------------------------------------------------------

    def _ignored(self, path: Path) -> bool:
        if path.name == LOG_NAME:
            # Watching ourselves write would never stop.
            return True
        return _TRUTH_FOLDER in path.parts

    def _record(self, kind: str, path: Path, old: Path | None) -> None:
        if self._ignored(path):
            return
        at = datetime.now(timezone.utc)
        writer = self._poll.writer_at(at)
        if writer is None:
            # A job that finished between two polls would otherwise go
            # unattributed. Asking once more, right now, costs one sweep and
            # only happens on the path that was about to give up anyway.
            self._poll.poll_once()
            writer = self._poll.writer_at(datetime.now(timezone.utc))
        try:
            size = path.stat().st_size if kind != DELETED else 0
        except OSError:
            size = 0
        event = Event(
            path=self._relative(path),
            kind=kind,
            at=at,
            pid=writer.pid if writer else None,
            process=writer.name if writer else None,
            old_path=self._relative(old) if old else None,
            size=size,
        )
        with self._lock:
            self._events.append(event)
        self._log.append(event)

    def _relative(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.root).as_posix()
        except ValueError:
            return path.as_posix()
