"""The PDS server's own pop-up alert.

The Vault console (nightkeep/console) only *renders* the alert afterwards,
on the Vault's own screen. This module *raises* it, on the machine where
the Watcher and Judge run -- the PDS server -- the moment an INCIDENT
verdict is decided, so staff see the warning without opening anything.

Stateless by construction: it takes a Verdict, a plain dataclass from
nightkeep.types, and shows a native OS pop-up. It never imports the
console, the vault, or anything that carries state, per CLAUDE.md's
server/Vault split. Showing the pop-up is best effort and never raises:
the verdict path must survive a missing desktop.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable

from nightkeep.types import INCIDENT, Verdict


@dataclass(frozen=True)
class ServerAlert:
    """What the pop-up says. Plain language for the office computer."""

    title: str
    headline: str
    details: tuple[str, ...]


def alert_for(verdict: Verdict) -> ServerAlert | None:
    """Build the pop-up for an INCIDENT verdict; None for anything else.

    Reads the verdict only. The level, reasons and actions were all decided
    by the Judge; nothing is recomputed here. The headline claims "paused"
    only when the Judge actually paused something: Verdict.actions carries
    a "paused ..." entry exactly when suspend_process succeeded. When no
    PID was known, or the program was already gone, the headline says so
    instead of lying.
    """
    if verdict.level != INCIDENT:
        return None
    paused = any(action.startswith("paused") for action in verdict.actions)
    headline = (
        "A program tried to lock your files. It was paused."
        if paused
        else "A program tried to lock your files. It was not paused."
    )
    return ServerAlert(
        title="Nightkeep Security Alert",
        headline=headline,
        details=tuple(verdict.actions)
        + (
            "Do not restart this computer.",
            "Disconnect the network cable.",
        ),
    )


# A display takes the alert and reports whether a pop-up was really shown.
# The platform default is used unless a caller injects its own, which is
# what the tests do so the suite never pops a real dialog.
ShowAlert = Callable[[ServerAlert], bool]


def raise_for_verdict(verdict: Verdict, show: ShowAlert | None = None) -> bool:
    """Raise the pop-up for an INCIDENT verdict. False for anything else."""
    alert = alert_for(verdict)
    if alert is None:
        return False
    return raise_alert(alert, show=show)


def raise_alert(alert: ServerAlert, show: ShowAlert | None = None) -> bool:
    """Show the pop-up. Never raises; returns whether one was shown.

    If no pop-up could be shown (no desktop, no notifier), the alert is
    printed to stderr instead: an incident is never swallowed silently.
    """
    shown = False
    try:
        shown = bool((show or _platform_show)(alert))
    except Exception:
        shown = False
    if not shown:
        print(f"[{alert.title}] {alert.headline}", file=sys.stderr)
        for line in alert.details:
            print(f"  - {line}", file=sys.stderr)
    return shown


def _platform_show(alert: ServerAlert) -> bool:
    if sys.platform == "win32":
        return _windows_popup(alert)
    if sys.platform == "darwin":
        return _macos_popup(alert)
    return _linux_popup(alert)


def _alert_text(alert: ServerAlert) -> str:
    return "\n".join((alert.headline, *alert.details))


def _windows_popup(alert: ServerAlert) -> bool:
    """A system-modal message box. Blocks until dismissed, by design: the
    incident is the demo's beat, and staff must acknowledge it."""
    import ctypes

    MB_ICONWARNING = 0x30
    MB_SYSTEMMODAL = 0x1000
    pressed = ctypes.windll.user32.MessageBoxW(
        None, _alert_text(alert), alert.title, MB_ICONWARNING | MB_SYSTEMMODAL
    )
    return pressed != 0


def _macos_popup(alert: ServerAlert) -> bool:
    script = (
        f'display alert "{_applescript_escape(alert.title)}" '
        f'message "{_applescript_escape(_alert_text(alert))}" as critical'
    )
    completed = subprocess.run(
        ["osascript", "-e", script], capture_output=True, timeout=30
    )
    return completed.returncode == 0


def _applescript_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _linux_popup(alert: ServerAlert) -> bool:
    text = _alert_text(alert)
    if shutil.which("notify-send"):
        completed = subprocess.run(
            [
                "notify-send",
                "--urgency=critical",
                "--app-name=Nightkeep",
                alert.title,
                text,
            ],
            capture_output=True,
            timeout=30,
        )
        return completed.returncode == 0
    if shutil.which("zenity"):
        completed = subprocess.run(
            [
                "zenity",
                "--warning",
                "--title",
                alert.title,
                "--text",
                text,
                "--no-wrap",
            ],
            capture_output=True,
            timeout=30,
        )
        return completed.returncode == 0
    return False
