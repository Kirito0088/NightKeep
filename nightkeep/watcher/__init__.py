"""Notices file changes on the PDS server and which process caused them.

Public interface:
    Watcher(root, poll_seconds, settle_seconds, reconcile_seconds=None)
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
import time
from datetime import datetime, timezone
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from nightkeep.types import (
    CREATED,
    DELETED,
    HEARTBEAT_FILENAME,
    MODIFIED,
    RENAMED,
    Event,
)
from nightkeep.watcher._log import LOG_NAME, EventLog
from nightkeep.watcher._processes import ProcessPoll
from nightkeep.watcher._reconcile import OFF_LIMITS_TOP_LEVELS, TreeReconciler


def event_log_for(root: Path) -> EventLog:
    """The agent's append-only event log for this folder.

    Lets another process (the demo runner, the console) read what the
    Watcher saw without joining the Watcher process.
    """
    return EventLog(Path(root) / "logs" / LOG_NAME)

# The truth logs prove, after the fact, that learning was correct. Nightkeep
# must never be able to see them, not even as a filename. CLAUDE.md makes
# this a hard rail, and tests/test_rails.py holds it.
_TRUTH_FOLDER = "_truth"

# Reconciliation default: opt-in. Reconciliation is a backstop for native
# file events dropped under burst load (on Windows, ReadDirectoryChangesW
# can drop events when a ransomware burst changes dozens of files faster
# than the kernel buffer drains), but it starts a background enumeration
# thread, so callers that need it must ask for it explicitly. The
# production watcher agent (nightkeep/watcher/__main__.py) enables it on
# Windows via its own CLI default.
DEFAULT_RECONCILE_SECONDS = 0.0

# The native-recorded (kind, relative path) hint cache is only a dedupe
# aid; bounding it keeps a long-lived watcher from growing it without
# limit when reconciliation is off.
_SEEN_HINT_CAP = 50000

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
        reconcile_seconds: float | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.settle_seconds = settle_seconds
        if reconcile_seconds is None:
            reconcile_seconds = DEFAULT_RECONCILE_SECONDS
        self.reconcile_seconds = reconcile_seconds
        self._events: list[Event] = []
        self._lock = threading.Lock()
        self._log = event_log_for(self.root)
        self._poll = ProcessPoll(str(self.root), poll_seconds)
        self._observer = Observer()
        self._observer.schedule(_Handler(self), str(self.root), recursive=True)
        self._started = False
        self._last_fallback_poll = 0.0
        self._reconciler: TreeReconciler | None = None
        self._reconcile_thread: threading.Thread | None = None
        self._reconcile_stop = threading.Event()
        # Native (kind, relative path) pairs recorded since the last
        # reconciliation sweep: the dedupe hint for synthesized events.
        self._seen_since_sweep: set[tuple[str, str]] = set()

    # --- lifecycle --------------------------------------------------------

    def start(self) -> "Watcher":
        self._poll.start()
        # One sweep before any job runs, so the first file written already has
        # somebody to attribute it to.
        self._poll.poll_once()
        self._observer.start()
        # The reconciliation baseline: everything already on disk is "seen",
        # so the first sweep only reports what changes from here on.
        self._reconciler = TreeReconciler(self.root, self._reconcile_ignored)
        if self.reconcile_seconds > 0:
            self._reconcile_stop.clear()
            self._reconcile_thread = threading.Thread(
                target=self._reconcile_loop,
                name="watcher-reconcile",
                daemon=True,
            )
            self._reconcile_thread.start()
        self._started = True
        return self

    def stop(self) -> None:
        if not self._started:
            return
        self._reconcile_stop.set()
        if self._reconcile_thread is not None:
            self._reconcile_thread.join(timeout=5)
            self._reconcile_thread = None
        self._reconciler = None
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

    # --- reconciliation ---------------------------------------------------

    def _reconcile_ignored(self, path: Path) -> bool:
        """What the enumeration backstop must never report.

        Everything the native handler ignores, plus the top-level folders
        the simulator can never enter (logs, data, .nightkeep-sim): the
        reconciler only fills gaps in attack evidence, so bookkeeping
        trees it cannot see an attack in are pruned, not walked.
        """
        if self._ignored(path):
            return True
        try:
            relative = path.relative_to(self.root)
        except ValueError:
            return True
        return bool(relative.parts) and relative.parts[0] in OFF_LIMITS_TOP_LEVELS

    def _reconcile_loop(self) -> None:
        while not self._reconcile_stop.wait(self.reconcile_seconds):
            try:
                self._reconcile_once()
            except Exception:
                # The reconciler is a backstop: a failed sweep must never
                # take the watcher down with it. The next sweep retries.
                continue

    def _reconcile_once(self) -> list[Event]:
        """One enumeration sweep: synthesize what native events missed.

        Diffs the tree against the previous sweep and records each change
        the native handler has not already reported since that sweep, so a
        change is never recorded twice for the same window. Returns the
        synthesized events.
        """
        if self._reconciler is None:
            return []
        changes = self._reconciler.sweep()
        with self._lock:
            seen = self._seen_since_sweep
            self._seen_since_sweep = set()
        synthesized: list[Event] = []
        for change in changes:
            if (change.kind, self._relative(change.path)) in seen:
                continue
            event = self._record(change.kind, change.path, change.old_path)
            if event is not None:
                synthesized.append(event)
        return synthesized

    # --- internals --------------------------------------------------------

    def _ignored(self, path: Path) -> bool:
        if path.name == LOG_NAME:
            # Watching ourselves write would never stop.
            return True
        if path.name == HEARTBEAT_FILENAME or path.name.startswith(
            HEARTBEAT_FILENAME + "."
        ):
            # The liveness heartbeat is the Vault's business, not the
            # Judge's: its writes -- including the atomic temp file the
            # worker renames into place -- must never become events, habit
            # observations or judge input.
            return True
        return _TRUTH_FOLDER in path.parts

    def _record(self, kind: str, path: Path, old: Path | None) -> Event | None:
        if self._ignored(path):
            return None
        at = datetime.now(timezone.utc)
        writer = self._poll.writer_at(at)
        if writer is None:
            # A job that finished between two polls would otherwise go
            # unattributed. We do a synchronous sweep, but rate-limit it:
            # on Windows, a fast ransomware simulator can generate dozens
            # of file events in under a second, and a synchronous process
            # sweep per event (100-300ms each) makes the watcher fall so
            # far behind that the live Judge sees only 1 event instead of
            # 80+. At most one fallback sweep per second; the background
            # ProcessPoll thread (0.2s interval) remains the primary
            # attribution mechanism.
            now = time.monotonic()
            if now - self._last_fallback_poll >= 1.0:
                self._last_fallback_poll = now
                self._poll.poll_once()
                writer = self._poll.writer_at(datetime.now(timezone.utc))
        try:
            size = path.stat().st_size if kind != DELETED else 0
        except OSError:
            size = 0
        relative = self._relative(path)
        event = Event(
            path=relative,
            kind=kind,
            at=at,
            pid=writer.pid if writer else None,
            process=writer.name if writer else None,
            old_path=self._relative(old) if old else None,
            size=size,
        )
        with self._lock:
            self._events.append(event)
            # Dedupe hint for the reconciler: a change the native handler
            # already reported must not be synthesized again. Attribution
            # stays independent -- a missing pid never blocks this.
            if self._reconciler is not None:
                if len(self._seen_since_sweep) >= _SEEN_HINT_CAP:
                    self._seen_since_sweep.clear()
                self._seen_since_sweep.add((kind, relative))
        self._log.append(event)
        return event

    def _relative(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.root).as_posix()
        except ValueError:
            return path.as_posix()
