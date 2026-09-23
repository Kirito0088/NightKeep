"""The live session's status, worded for the console. Read-only.

The engine writes codes and numbers (a phase, a day, a readiness code); this
module turns them into the plain sentences the demo controls and the Night
Jobs screen show. It decides nothing: every fact comes from status.json.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Mapping

from nightkeep import live_protocol as lp

VARIANT_LABELS = {
    "fast": "Fast scrambler",
    "impersonator": "Impersonator",
    "recovery-killer": "Recovery-killer",
    "watcher-killer": "Agent-stopper",
}

_READINESS_TEXT = {
    lp.ATTACK_READY: "Launches the safe simulator against the office computer.",
    lp.ATTACK_WAIT_FOR_CLEAN_COPY: (
        "Available after day 1, once the Vault holds a clean copy to "
        "restore from."
    ),
    lp.ATTACK_BUSY: "An attack is already being handled.",
    lp.ATTACK_ALREADY_RAN: (
        "This run has had its attack. Start a fresh run to try another."
    ),
    lp.ATTACK_NOT_RUNNING: "Start a fresh run first.",
}


@dataclass(frozen=True)
class LiveControlsPresentation:
    """The demo controls in the page chrome."""

    line: str
    can_attack: bool
    attack_reason: str
    variants: tuple[tuple[str, str], ...]
    surge_requested: bool
    surge_line: str


def session_line(status: Mapping) -> str:
    """One sentence: what the live session is doing right now."""
    phase = status.get("phase")
    day = status.get("day") or {}
    number = day.get("number") or 0
    learning_days = day.get("learning_days") or 0
    if not status:
        return "The live session is not running."
    if phase == lp.STARTING:
        return "Preparing the district."
    if phase == lp.LEARNING:
        return f"Learning the night jobs. Day {number} of {learning_days}."
    if phase == lp.GUARD:
        return f"Checking every night job. Day {number}."
    if phase == lp.ATTACK:
        return "A safe simulated attack is running."
    if phase in (lp.CONTAINMENT, lp.VAULT, lp.CONTAINED):
        return "Attack stopped. Records are locked until they are restored."
    if phase == lp.RECOVERY:
        return "Restoring the records from the clean copy."
    if phase == lp.RECOVERED:
        return "Records restored and checked."
    if phase == lp.COMPLETE:
        return "The full demonstration is complete."
    if phase == lp.FAILED:
        return "The live session stopped with a problem."
    return "The live session has stopped."


def surge_line(status: Mapping) -> str:
    day = status.get("day") or {}
    if not day.get("number"):
        return "Harvest surge: waiting for the first day."
    if day.get("surge_tonight"):
        why = day.get("surge_why")
        reason = " (switched on)" if why == "switched on" else " (seeded surge day)"
        return f"Harvest surge tonight: yes{reason}."
    return "Harvest surge tonight: no."


def live_controls(status: Mapping, variants: tuple[str, ...]) -> LiveControlsPresentation:
    readiness = status.get("attack_readiness", lp.ATTACK_NOT_RUNNING)
    if not status:
        readiness = lp.ATTACK_NOT_RUNNING
    return LiveControlsPresentation(
        line=session_line(status),
        can_attack=readiness == lp.ATTACK_READY,
        attack_reason=_READINESS_TEXT.get(readiness, _READINESS_TEXT[lp.ATTACK_NOT_RUNNING]),
        variants=tuple((v, VARIANT_LABELS.get(v, v)) for v in variants),
        surge_requested=bool(status.get("harvest_surge_requested")),
        surge_line=surge_line(status),
    )


def is_locked(status: Mapping) -> bool:
    """True while the Judge's read-only lock is holding the records."""
    return bool(status.get("lock_held")) or status.get("phase") in lp.LOCKED_PHASES


# What each kind of page needs to notice. A page reloads only when its own
# stamp changes, so a clerk filling in the search form is not interrupted by
# a night job finishing.
_SCOPES = {
    # Search and card detail: only the lock matters.
    "calm": lambda s: (s.get("phase"), s.get("lock_held"),
                       (s.get("restore") or {}).get("ok")),
    # Data Safety, alert, restore, IT view: each finished day moves the
    # safe copies and the night-task table.
    "day": lambda s: (s.get("phase"), s.get("lock_held"),
                      (s.get("day") or {}).get("done"),
                      (s.get("attack") or {}).get("state"),
                      (s.get("restore") or {}).get("ok")),
    # Night Jobs and the Full MVP Demo: every change.
    "all": lambda s: s.get("version"),
}


def stamp(status: Mapping, scope: str) -> str:
    """A short fingerprint of what a page of this scope shows."""
    picked = _SCOPES.get(scope, _SCOPES["day"])(status or {})
    body = json.dumps(picked, sort_keys=True, default=str)
    return hashlib.sha1(body.encode("utf-8")).hexdigest()[:12]


__all__ = [
    "LiveControlsPresentation", "VARIANT_LABELS", "live_controls",
    "session_line", "surge_line", "is_locked", "stamp",
]
