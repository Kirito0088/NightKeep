"""Filesystem watcher for the PDS server.

Monitors file creations, modifications, deletions, and moves.
Persists events to an append-only JSONL log and provides deterministic
events_since(t) retrieval. Contains zero classification or verdict logic.
"""

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from watchdog.events import (
    DirMovedEvent,
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    FileSystemEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer

from nightkeep.types import Event


def _serialize_event(event: Event) -> str:
    return json.dumps({
        "timestamp": event.timestamp.isoformat(),
        "event_type": event.event_type,
        "path": event.path,
        "is_directory": event.is_directory,
        "extension": event.extension,
        "size_bytes": event.size_bytes,
        "old_path": event.old_path,
        "process_id": event.process_id,
        "process_name": event.process_name,
    })


def _deserialize_event(line: str) -> Event:
    data = json.loads(line)
    return Event(
        timestamp=datetime.fromisoformat(data["timestamp"]),
        event_type=data["event_type"],
        path=data["path"],
        is_directory=data["is_directory"],
        extension=data["extension"],
        size_bytes=data["size_bytes"],
        old_path=data.get("old_path"),
        process_id=data.get("process_id"),
        process_name=data.get("process_name"),
    )


class NightkeepEventHandler(FileSystemEventHandler):
    """Bridges watchdog filesystem events to the Nightkeep Watcher."""

    def __init__(self, watcher: "Watcher") -> None:
        super().__init__()
        self._watcher = watcher

    def _should_ignore(self, path_str: str) -> bool:
        p = Path(path_str)
        # Never watch the watcher log itself (stops recursive write loops)
        if p.name == "watcher_events.jsonl":
            return True
        # Never watch hidden ground truth
        if "_truth" in p.parts:
            return True
        if ".git" in p.parts:
            return True
        return False

    def on_created(self, event: FileSystemEvent) -> None:
        if self._should_ignore(event.src_path):
            return
        self._watcher._handle_fs_event("created", event.src_path, event.is_directory)

    def on_modified(self, event: FileSystemEvent) -> None:
        if self._should_ignore(event.src_path):
            return
        self._watcher._handle_fs_event("modified", event.src_path, event.is_directory)

    def on_deleted(self, event: FileSystemEvent) -> None:
        if self._should_ignore(event.src_path):
            return
        self._watcher._handle_fs_event("deleted", event.src_path, event.is_directory)

    def on_moved(self, event: FileMovedEvent | DirMovedEvent) -> None:
        if self._should_ignore(event.src_path) and self._should_ignore(event.dest_path):
            return
        self._watcher._handle_fs_event(
            "moved", event.dest_path, event.is_directory, old_path_str=event.src_path
        )


class Watcher:
    """The PDS-side filesystem witness.

    Notices file changes, appends them to logs/watcher_events.jsonl,
    and returns events_since(t).
    """

    def __init__(
        self,
        root_dir: Path | str,
        log_path: Path | str | None = None,
    ) -> None:
        self._root_dir = Path(root_dir).resolve()
        if log_path:
            self._log_path = Path(log_path).resolve()
        else:
            self._log_path = self._root_dir / "logs" / "watcher_events.jsonl"

        self._lock = threading.Lock()
        self._events: list[Event] = []
        self._observer: Observer | None = None
        self._is_running = False

        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        self._load_existing_log()

    @property
    def root_dir(self) -> Path:
        return self._root_dir

    @property
    def log_path(self) -> Path:
        return self._log_path

    def _load_existing_log(self) -> None:
        """Rehydrate existing events from the JSONL log if present."""
        if self._log_path.is_file():
            with self._log_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            self._events.append(_deserialize_event(line))
                        except (json.JSONDecodeError, KeyError, ValueError):
                            pass

    def start(self) -> None:
        """Start monitoring the root directory with watchdog."""
        with self._lock:
            if self._is_running:
                return

            self._root_dir.mkdir(parents=True, exist_ok=True)
            self._observer = Observer()
            handler = NightkeepEventHandler(self)
            self._observer.schedule(handler, str(self._root_dir), recursive=True)
            self._observer.start()
            self._is_running = True

    def stop(self) -> None:
        """Stop watchdog monitoring gracefully."""
        with self._lock:
            if not self._is_running:
                return
            if self._observer:
                self._observer.stop()
                self._observer.join(timeout=2.0)
                self._observer = None
            self._is_running = False

    def is_alive(self) -> bool:
        """Return whether the watcher is running and healthy."""
        with self._lock:
            if not self._is_running or self._observer is None:
                return False
            return self._observer.is_alive()

    def record_event(self, event: Event) -> None:
        """Directly record an event in memory and append to the JSONL log."""
        with self._lock:
            self._events.append(event)
            with self._log_path.open("a", encoding="utf-8") as f:
                f.write(_serialize_event(event) + "\n")

    def _normalize_path(self, path_str: str) -> str:
        p = Path(path_str).resolve()
        try:
            return str(p.relative_to(self._root_dir))
        except ValueError:
            return str(p)

    def _handle_fs_event(
        self,
        event_type: str,
        path_str: str,
        is_directory: bool,
        old_path_str: str | None = None,
        timestamp: datetime | None = None,
    ) -> None:
        norm_path = self._normalize_path(path_str)
        norm_old_path = self._normalize_path(old_path_str) if old_path_str else None

        ext = Path(path_str).suffix.lower() if not is_directory else ""
        size_bytes = 0
        if not is_directory and event_type != "deleted":
            try:
                size_bytes = Path(path_str).stat().st_size
            except OSError:
                size_bytes = 0

        event = Event(
            timestamp=timestamp or datetime.now(),
            event_type=event_type,
            path=norm_path,
            is_directory=is_directory,
            extension=ext,
            size_bytes=size_bytes,
            old_path=norm_old_path,
        )
        self.record_event(event)

    def events_since(self, t: datetime) -> list[Event]:
        """Return all events recorded at or after timestamp t in chronological order.

        Does not modify event history or pop events.
        """
        with self._lock:
            return [e for e in self._events if e.timestamp >= t]
