"""The watcher's append-only log.

One JSON object per line, opened in append mode and never rewritten. If
something later edits history, the file's own line order is the evidence.
The log lives inside the watched folder, so the writer skips its own path to
avoid watching itself write.
"""

import json
import threading
from datetime import datetime
from pathlib import Path

from nightkeep.types import Event

LOG_NAME = "watcher.jsonl"


class EventLog:
    """Appends events as JSON lines, and reads them back in order."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def append(self, event: Event) -> None:
        line = {
            "path": event.path,
            "kind": event.kind,
            "at": event.at.isoformat(),
            "pid": event.pid,
            "process": event.process,
            "old_path": event.old_path,
            "size": event.size,
        }
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(line) + "\n")

    def read_all(self) -> tuple[Event, ...]:
        if not self.path.exists():
            return ()
        text = self.path.read_text(encoding="utf-8")
        # The log is append-only and the writer is a separate process, so
        # the final line may be an in-flight write: present but not yet
        # newline-terminated, possibly torn mid-record. Only that trailing
        # unterminated line is treated as possibly-incomplete: it is
        # skipped for now (the next poll reads it once the write lands)
        # and never fabricated into an event. Every newline-terminated
        # line is a complete record -- malformed ones still fail loudly
        # rather than being silently hidden.
        lines = text.splitlines()
        terminated = text.endswith("\n")
        last_index = len(lines) - 1
        events = []
        for index, line in enumerate(lines):
            if not line.strip():
                continue
            if index == last_index and not terminated:
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    continue
            else:
                raw = json.loads(line)
            events.append(
                Event(
                    path=raw["path"],
                    kind=raw["kind"],
                    at=datetime.fromisoformat(raw["at"]),
                    pid=raw["pid"],
                    process=raw["process"],
                    old_path=raw["old_path"],
                    size=raw["size"],
                )
            )
        return tuple(events)
