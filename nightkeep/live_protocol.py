"""The files the live session's two sides talk through. Stateless.

The console (the Vault's screen) and the live engine (the district PDS
server, played by nightkeep.live) never share memory or code that carries
state. They share a folder:

    <root>/district/        the PDS server's own folder, built by mock_pds
    <root>/vault/           the Vault's store
    <root>/engine/status.json   written only by the engine: what is happening
    <root>/engine/report.json   written only by the engine: what was decided,
                                in the same shape as demo_run.json
    <root>/engine/control.json  written only by the console: demo commands
    <root>/engine/engine.log    the engine's own output, unedited

engine/ sits outside the district on purpose: the simulator walks the
district, and the Judge's read-only lock covers district/data and
district/share, so neither can reach the session's bookkeeping.

control.json carries demo-harness commands (the judge's menu in MVP.md
section 6), not Nightkeep decisions: switch the harvest surge, launch the
safe simulator, and tell the engine a restore has finished.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

STATUS_NAME = "status.json"
REPORT_NAME = "report.json"
CONTROL_NAME = "control.json"
LOG_NAME = "engine.log"

# The session's phases, in the order a run moves through them. The engine
# writes one of these; the console only reads it.
STARTING = "starting"
LEARNING = "learning"
GUARD = "guard"
ATTACK = "attack"
CONTAINMENT = "containment"
VAULT = "vault"
CONTAINED = "contained"
RECOVERY = "recovery"
RECOVERED = "recovered"
COMPLETE = "complete"
FAILED = "failed"
STOPPED = "stopped"

# Phases after which the engine is gone or will do nothing more by itself.
FINISHED_PHASES = frozenset({COMPLETE, FAILED, STOPPED})
# Phases in which the Judge's read-only lock is holding the records.
LOCKED_PHASES = frozenset({CONTAINMENT, VAULT, CONTAINED, RECOVERY})

# Why the simulated attack cannot be launched right now. Codes, not
# sentences: the console words them.
ATTACK_READY = "ready"
ATTACK_WAIT_FOR_CLEAN_COPY = "no_clean_copy"
ATTACK_ALREADY_RAN = "already_ran"
ATTACK_BUSY = "busy"
ATTACK_NOT_RUNNING = "not_running"


@dataclass(frozen=True)
class SessionPaths:
    """Where one live session keeps everything."""

    root: Path

    @property
    def district(self) -> Path:
        return self.root / "district"

    @property
    def vault(self) -> Path:
        return self.root / "vault"

    @property
    def engine(self) -> Path:
        return self.root / "engine"

    @property
    def status(self) -> Path:
        return self.engine / STATUS_NAME

    @property
    def report(self) -> Path:
        return self.engine / REPORT_NAME

    @property
    def control(self) -> Path:
        return self.engine / CONTROL_NAME

    @property
    def log(self) -> Path:
        return self.engine / LOG_NAME


def empty_control() -> dict:
    """A control file with no commands in it."""
    return {"harvest_surge": False, "attack": None, "restored": None, "stop": False}


def read_json(path: Path) -> dict:
    """The JSON object at path, or {} when it is missing or half-written."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_json(path: Path, data: dict) -> None:
    """Write atomically, so a reader never sees half a file.

    os.replace can briefly fail on Windows while another process has the
    destination open for reading; a few quick retries cover that.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    for attempt in range(20):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.05)


__all__ = [
    "SessionPaths", "empty_control", "read_json", "write_json",
    "STATUS_NAME", "REPORT_NAME", "CONTROL_NAME", "LOG_NAME",
    "STARTING", "LEARNING", "GUARD", "ATTACK", "CONTAINMENT", "VAULT",
    "CONTAINED", "RECOVERY", "RECOVERED", "COMPLETE", "FAILED", "STOPPED",
    "FINISHED_PHASES", "LOCKED_PHASES",
    "ATTACK_READY", "ATTACK_WAIT_FOR_CLEAN_COPY", "ATTACK_ALREADY_RAN",
    "ATTACK_BUSY", "ATTACK_NOT_RUNNING",
]
