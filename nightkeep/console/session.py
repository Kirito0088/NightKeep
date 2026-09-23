"""The console's handle on the live session. Glue only.

Starts and stops the live engine (nightkeep.live, the district PDS server)
as its own process, writes the demo controls to control.json and reads
status.json back. It never judges, never learns and never touches the
Vault: the only files it writes are the control file and the engine's log,
and the only thing it deletes is the session folder it owns, on a fresh
start.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import threading
import time
from pathlib import Path

from nightkeep import live_protocol as lp

# The only things a session folder may hold. A fresh start deletes the
# folder, so anything else in it means the path is wrong: refuse.
_SESSION_CHILDREN = frozenset({"district", "vault", "engine"})


class SessionFolderRefused(Exception):
    """The session folder holds something a live session never writes."""


def _remove_readonly(func, path, _):
    # The Judge may have left files read-only if an engine died mid-incident.
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError:
        pass


def _kill_tree(pid: int) -> None:
    import psutil

    try:
        root = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return
    try:
        family = root.children(recursive=True)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        family = []
    for process in [root, *family]:
        try:
            process.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue


class LiveSession:
    """One live session at a time: start it, steer it, stop it."""

    def __init__(self, paths: lp.SessionPaths, engine_cmd: list[str], *,
                 stop_timeout: float = 20.0) -> None:
        self.paths = paths
        self._engine_cmd = list(engine_cmd)
        self._stop_timeout = stop_timeout
        self._lock = threading.RLock()
        self._proc: subprocess.Popen | None = None
        self._control = lp.empty_control()
        self._next_id = 0

    # --- lifecycle ---------------------------------------------------------

    def start(self, *, autopilot: bool = False, variant: str | None = None) -> None:
        """Stop any running session, wipe its folder and start a fresh one."""
        with self._lock:
            self.stop()
            self._wipe()
            self.paths.engine.mkdir(parents=True, exist_ok=True)
            self._control = lp.empty_control()
            lp.write_json(self.paths.control, self._control)
            command = [*self._engine_cmd, "--parent-pid", str(os.getpid())]
            if autopilot:
                command.append("--autopilot")
            if variant:
                command += ["--variant", variant]
            log = open(self.paths.log, "w", encoding="utf-8")
            try:
                self._proc = subprocess.Popen(
                    command, stdout=log, stderr=subprocess.STDOUT,
                )
            finally:
                # The child holds its own handle to the log.
                log.close()

    def stop(self) -> None:
        """Ask the engine to stop cleanly; end it if it does not."""
        with self._lock:
            proc = self._proc
            if proc is None:
                return
            if proc.poll() is None:
                self._write_control(stop=True)
                try:
                    proc.wait(timeout=self._stop_timeout)
                except subprocess.TimeoutExpired:
                    _kill_tree(proc.pid)
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        pass
            self._proc = None

    def is_running(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    def _wipe(self) -> None:
        root = self.paths.root
        if not root.exists():
            return
        stray = {child.name for child in root.iterdir()} - _SESSION_CHILDREN
        if stray:
            raise SessionFolderRefused(
                f"{root} holds {sorted(stray)}, which a live session never "
                "writes; refusing to delete it"
            )
        # A file still held open (a pop-up's or a job's last handle) makes
        # one pass leave things behind, and Windows can report the tree gone
        # a moment before it is. Try again for a short while; a fresh run
        # must never be built on top of the old one's leftovers.
        for _ in range(20):
            shutil.rmtree(root, onerror=_remove_readonly)
            if not root.exists():
                return
            time.sleep(0.1)
        raise SessionFolderRefused(
            f"{root} could not be cleared; something still holds files in it"
        )

    # --- what the engine says -------------------------------------------

    def status(self) -> dict:
        """The engine's latest status, honest about an engine that died."""
        status = lp.read_json(self.paths.status)
        if not status:
            return {"phase": lp.STARTING} if self.is_running() else {}
        if (not self.is_running()
                and status.get("phase") not in lp.FINISHED_PHASES):
            status = {**status, "phase": lp.FAILED,
                      "note": "The live session ended unexpectedly.",
                      "attack_readiness": lp.ATTACK_NOT_RUNNING}
        return status

    def report(self) -> dict:
        return lp.read_json(self.paths.report)

    def log_tail(self, lines: int = 40) -> str:
        try:
            text = self.paths.log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        return "\n".join(text.splitlines()[-lines:])

    # --- the demo controls ------------------------------------------------

    def request_attack(self, variant: str) -> None:
        self._write_control(attack={"id": self._new_id(), "variant": variant})

    def set_harvest_surge(self, on: bool) -> None:
        self._write_control(harvest_surge=bool(on))

    def record_restore(self, result) -> None:
        """Tell the engine the supervisor restored from the Vault."""
        self._write_control(restored={
            "id": self._new_id(),
            "ok": bool(result.ok),
            "snapshot_id": result.snapshot_id,
            "records_verified": result.records_verified,
            "records_expected": result.records_expected,
            "checks": [{"statement": c.statement, "passed": c.passed}
                       for c in result.checks],
            "restored_to": result.restored_to,
        })

    def _new_id(self) -> int:
        with self._lock:
            self._next_id += 1
            return self._next_id

    def _write_control(self, **changes) -> None:
        with self._lock:
            self._control = {**self._control, **changes}
            if self.paths.engine.is_dir():
                lp.write_json(self.paths.control, self._control)


__all__ = ["LiveSession", "SessionFolderRefused"]
