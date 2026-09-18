"""Notices file changes on the PDS server and which process caused them.

Public interface:
    events_since(t) -> [Event]
    is_alive()

Hides watchdog wiring, psutil polling, file-to-process attribution and the
append-only log.
"""

from datetime import datetime
from pathlib import Path

from nightkeep.types import Event, FileEvent
from nightkeep.watcher.watcher import Watcher

_DEFAULT_WATCHER: Watcher | None = None


def get_watcher(
    root_dir: Path | str | None = None,
    log_path: Path | str | None = None,
) -> Watcher:
    """Get or initialize the default Watcher instance."""
    global _DEFAULT_WATCHER
    if _DEFAULT_WATCHER is None:
        if root_dir is None:
            root_dir = Path.cwd()
        _DEFAULT_WATCHER = Watcher(root_dir, log_path)
    elif root_dir is not None and Path(root_dir).resolve() != _DEFAULT_WATCHER.root_dir:
        _DEFAULT_WATCHER.stop()
        _DEFAULT_WATCHER = Watcher(root_dir, log_path)
    return _DEFAULT_WATCHER


def set_default_watcher(watcher: Watcher | None) -> None:
    """Set or reset the default watcher instance (used in tests and life-cycle management)."""
    global _DEFAULT_WATCHER
    _DEFAULT_WATCHER = watcher


def events_since(t: datetime) -> list[Event]:
    """Return all filesystem events recorded at or after timestamp t."""
    watcher = get_watcher()
    return watcher.events_since(t)


def is_alive() -> bool:
    """Return whether the default watcher is currently running and healthy."""
    if _DEFAULT_WATCHER is None:
        return False
    return _DEFAULT_WATCHER.is_alive()


__all__ = [
    "Event",
    "FileEvent",
    "Watcher",
    "get_watcher",
    "set_default_watcher",
    "events_since",
    "is_alive",
]
