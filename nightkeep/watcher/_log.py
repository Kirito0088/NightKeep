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
        events = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
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
