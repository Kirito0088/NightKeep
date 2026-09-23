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


# --- the Night Jobs screen ----------------------------------------------------

# What each night job does, in the office's words. Labels only: which job is
# which comes from the engine's status, never from here.
JOB_PURPOSES = {
    "nightly_export": "Sends the day's ration shop sales to the state server.",
    "allocation_gen": "Makes next month's grain quota file for each shop. "
                      "Sometimes runs twice.",
    "db_backup": "Saves a copy of the ration card database for the Vault.",
    "archive_old": "Zips old upload files and removes the originals, "
                   "on nights the folder gets full.",
    "fix_dat": "An old script nobody documented. Renames and rewrites "
               "allotment files, some nights only.",
    "operator_activity": "Counter clerks updating records in office hours. "
                         "Never on a Sunday.",
}

_LEVEL_TEXT = {
    "NORMAL": ("Normal", "safe"),
    "ODD": ("Odd, not blocked", "review"),
    "SUSPICIOUS": ("Under review", "review"),
    "INCIDENT": ("Incident", "incident"),
}


@dataclass(frozen=True)
class NightJobRow:
    name: str
    purpose: str
    learning: str
    usually: str
    last_run: str
    last_check: str
    last_check_tone: str  # "safe" | "review" | "incident" | "none"


@dataclass(frozen=True)
class NightCheckRow:
    day: str
    name: str
    result: str
    tone: str
    why: str


@dataclass(frozen=True)
class NightJobsPresentation:
    headline: str
    detail: str
    tone: str  # "safe" | "review" | "incident"
    badge: str
    figures: tuple[tuple[str, str], ...]
    running_now: str
    rows: tuple[NightJobRow, ...]
    recent: tuple[NightCheckRow, ...]


def _learning_text(job: Mapping, learning_done: bool) -> str:
    seen = job.get("runs_seen") or 0
    if seen == 0:
        return "Not seen yet"
    times = "time" if seen == 1 else "times"
    if not job.get("has_card"):
        return f"Learning: seen {seen} {times}"
    if learning_done:
        return f"Learned from {seen} runs"
    return f"Habit card ready: seen {seen} {times}"


def _headline(status: Mapping) -> tuple[str, str, str, str]:
    """(headline, detail, tone, badge) for the top of the screen."""
    phase = status.get("phase")
    day = status.get("day") or {}
    checks = status.get("checks") or {}
    learning_days = day.get("learning_days") or 0
    if not status or phase == lp.STARTING:
        return ("Nightkeep is getting ready to watch the night jobs.",
                "The district is being prepared. The first day starts in a moment.",
                "safe", "STATUS: STARTING")
    if phase == lp.LEARNING:
        return ("Nightkeep is learning the office's night jobs.",
                f"Day {day.get('number', 0)} of {learning_days}. Nothing is judged "
                "while it learns. The tripwires are live from minute one.",
                "safe", "STATUS: LEARNING")
    if phase == lp.GUARD:
        alarms = checks.get("incidents", 0)
        odd = checks.get("odd", 0)
        return ("Nightkeep has learned the night jobs and is checking every run.",
                f"{checks.get('nights_checked', 0)} night job runs checked since "
                f"day {learning_days + 1}. {alarms} alarms. {odd} odd runs, "
                "none of them blocked.",
                "safe" if alarms == 0 else "incident", "STATUS: WATCHING")
    if phase == lp.ATTACK:
        return ("A safe simulated attack is running.",
                "The night jobs are held while Nightkeep handles it.",
                "incident", "STATUS: ATTACK")
    if phase in lp.LOCKED_PHASES:
        return ("Night jobs are stopped while the records are protected.",
                "Someone tried to lock the files and was stopped. Restore the "
                "records from the Vault to finish.",
                "incident", "STATUS: ATTACK STOPPED")
    if phase == lp.RECOVERED:
        return ("Night jobs are stopped. The records were restored.",
                "Start a fresh run to watch the office learn again.",
                "safe", "STATUS: RECOVERED")
    if phase == lp.COMPLETE:
        return ("The full demonstration is complete.",
                "The night jobs ran, the attack was stopped and the records "
                "were restored.", "safe", "STATUS: COMPLETE")
    if phase == lp.FAILED:
        return ("The live session stopped with a problem.",
                str(status.get("error") or status.get("note")
                    or "Start a fresh run to try again."),
                "review", "STATUS: STOPPED")
    return ("The live session has stopped.",
            "Start a fresh run to watch the night jobs again.",
            "review", "STATUS: STOPPED")


def night_jobs(status: Mapping, labels: Mapping[str, str],
               usually) -> NightJobsPresentation:
    """The Night Jobs screen from the engine's status. Decides nothing.

    `labels` is the console's plain name for each job; `usually` turns a
    habit card into one sentence (the same wording Data Safety uses).
    """
    day = status.get("day") or {}
    checks = status.get("checks") or {}
    learning_days = day.get("learning_days") or 0
    learning_done = learning_days > 0 and (day.get("done") or 0) >= learning_days
    headline, detail, tone, badge = _headline(status)

    rows = []
    for job in status.get("jobs") or []:
        name = job.get("job", "?")
        card = {feature: tuple(values)
                for feature, values in (job.get("card") or {}).items()}
        check_text, check_tone = _LEVEL_TEXT.get(job.get("last_level"), (None, "none"))
        if check_text is None:
            check_text = ("Learning, not judged" if job.get("last_day")
                          else "Not run yet")
        last_run = (f"Day {job['last_day']} at {job.get('last_sim_start', '?')}"
                    if job.get("last_day") else "Not run yet")
        rows.append(NightJobRow(
            name=labels.get(name, name),
            purpose=JOB_PURPOSES.get(name, ""),
            learning=_learning_text(job, learning_done),
            usually=usually(card) if card else "Not learned yet",
            last_run=last_run,
            last_check=check_text,
            last_check_tone=check_tone,
        ))

    recent = []
    for record in checks.get("recent") or []:
        level = record.get("level")
        text, check_tone = _LEVEL_TEXT.get(level, (str(level), "none"))
        reasons = record.get("reasons") or []
        recent.append(NightCheckRow(
            day=f"Day {record.get('day', '?')}",
            name=labels.get(record.get("job"), record.get("job", "?")),
            result=text,
            tone=check_tone,
            why=reasons[0] if reasons else "Nothing unusual.",
        ))

    running = status.get("running_job")
    if isinstance(running, Mapping):
        running_now = (
            f"Running now: {labels.get(running.get('job'), running.get('job'))}, "
            f"started {running.get('sim_start', '?')} on day {running.get('day', '?')}."
        )
    else:
        running_now = "No night job is running right now."

    jobs = status.get("jobs") or []
    learned = sum(1 for job in jobs if job.get("has_card"))
    figures = (
        (f"{min(day.get('done') or 0, learning_days)} of {learning_days}",
         "learning days done"),
        (f"{learned} of {len(jobs)}", "night jobs with a habit card"),
        (str(checks.get("nights_checked", 0)), "night job runs checked"),
        (str(checks.get("incidents", 0)), "alarms"),
    )
    return NightJobsPresentation(
        headline=headline, detail=detail, tone=tone, badge=badge,
        figures=figures, running_now=running_now,
        rows=tuple(rows), recent=tuple(recent),
    )


__all__ = [
    "LiveControlsPresentation", "VARIANT_LABELS", "live_controls",
    "session_line", "surge_line", "is_locked", "stamp",
    "JOB_PURPOSES", "NightJobsPresentation", "night_jobs",
]
