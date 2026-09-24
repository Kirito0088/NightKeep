"""One-click MVP showcase: launch the real demo, track it, show it.

Presentation/orchestration glue only. The demonstration itself is the
existing end-to-end runner -- ``python -m nightkeep --demo-run --variant
recovery-killer`` -- launched as a subprocess with the current Python
interpreter. This module never re-implements demo logic, never judges,
never touches the Vault, and never fabricates numbers: every figure on
the showcase page comes from the demo's own log or its on-disk report.

State lives in ``demo/showcase_status.json`` (outside ``demo/demo_run/``,
which the runner deletes and rebuilds, and outside ``logs/_truth``,
which the console must never read). A browser refresh re-reads that
file, so the page survives reloads, and a stale PID can never start a
second run.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_DIR = REPO_ROOT / "demo"
STATUS_PATH = DEMO_DIR / "showcase_status.json"
LOG_PATH = DEMO_DIR / "showcase_demo.log"

DEMO_VARIANT = "recovery-killer"
DEMO_RUN_DIR = REPO_ROOT / "demo" / "demo_run"
DISTRICT_DIR = DEMO_RUN_DIR / "district"

# Verbatim markers from demo_run.py's say() lines, latest phase first.
# The phase is the first marker found scanning the log from the end.
_PHASE_MARKERS: tuple[tuple[str, str], ...] = (
    ("complete", "--- proof PASSED ---"),
    ("failed", "--- proof FAILED ---"),
    ("recovery", "--- recovery: restore the pinned clean snapshot ---"),
    ("vault", "--- vault after the attack ---"),
    ("containment", "containment: simulator pid"),
    ("attack", "--- attack: safe ransomware simulator ---"),
    ("guard", "--- guard: 3 days ---"),
    ("learning", "--- learning: 7 days ---"),
    ("starting", "Nightkeep end-to-end proof, seed"),
)

# The runner's platform guard (demo_run.main catches the missing
# cscript.exe/cmd.exe and exits): the demo never really ran.
_CANNOT_RUN_MARKER = "Nightkeep cannot run the proof here."

# Truthful one-line copy per phase. No numbers here: figures only ever
# come from the run's own report (see report_figures()).
_PHASE_COPY: dict[str, tuple[str, str]] = {
    "ready": (
        "Ready",
        "Nothing is running on autopilot. Start the guided demo to watch "
        "the whole story from start to finish.",
    ),
    "starting": (
        "Starting",
        "Preparing the district and starting the demonstration.",
    ),
    "learning": (
        "Learn",
        "Nightkeep is learning what normal night work looks like on the "
        "district server.",
    ),
    "guard": (
        "Guard",
        "Nightkeep checks the district's normal night work against what "
        "it learned.",
    ),
    "attack": (
        "Attack",
        "A safe simulated ransomware attack is running. Nightkeep watches "
        "the files and only declares an incident when the evidence is "
        "clear.",
    ),
    "containment": (
        "Contain",
        "Nightkeep detected the attack and stopped it. The office "
        "computer is isolated.",
    ),
    "vault": (
        "Protect",
        "The Vault keeps the safe copies protected while the attack is "
        "being handled.",
    ),
    "recovery": (
        "Recover",
        "Records are being restored from the last clean copy and every "
        "record is checked.",
    ),
    "complete": (
        "Demo complete",
        "End-to-end proof complete. Every figure below came from this "
        "run's own report.",
    ),
    "failed": (
        "Demo failed",
        "The demonstration did not complete. The reason is shown below, "
        "with the run log.",
    ),
}

_STEPS: tuple[str, ...] = (
    "ready",
    "learning",
    "guard",
    "attack",
    "containment",
    "vault",
    "recovery",
    "complete",
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _pid_alive(pid: int) -> bool:
    """True if a process with this PID exists (no signal is sent).

    Asked of psutil, never os.kill(pid, 0): on Windows os.kill calls
    TerminateProcess for any signal but the two console ones, so that
    "probe" would end whatever process now holds a stale PID.

    A zombie child still exists as far as the OS is concerned, so our own
    children are reaped with waitpid(WNOHANG) first; anything reaped was
    dead.
    """
    import psutil

    def alive() -> bool:
        try:
            return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            return False
        except psutil.AccessDenied:
            # The process exists but belongs to another user.
            return True

    wnohang = getattr(os, "WNOHANG", None)
    if wnohang is None:
        return alive()
    try:
        done, _ = os.waitpid(pid, wnohang)
    except ChildProcessError:
        # Not our child: fall through to the kill probe.
        pass
    except OSError:
        return False
    else:
        if done == pid:
            # It had exited and is now reaped: definitely dead.
            return False
    return alive()


def default_demo_cmd() -> list[str]:
    """The real demo, run with the current interpreter (never hardcoded)."""
    return [
        sys.executable,
        "-m",
        "nightkeep",
        "--demo-run",
        "--variant",
        DEMO_VARIANT,
    ]


class ShowcaseController:
    """Launch and track one demo run. Read-only except for its own files.

    The only files this controller ever writes are its status JSON and
    the demo's log, both under ``demo/`` and both outside the runner's
    own output directory. It never writes to the district, the Vault,
    or ``logs/_truth``.
    """

    def __init__(
        self,
        *,
        status_path: Path | None = None,
        log_path: Path | None = None,
        demo_cmd: list[str] | None = None,
        district_dir: Path | None = None,
    ) -> None:
        self._status_path = Path(status_path) if status_path else STATUS_PATH
        self._log_path = Path(log_path) if log_path else LOG_PATH
        self._demo_cmd = list(demo_cmd) if demo_cmd else default_demo_cmd()
        self._district_dir = (
            Path(district_dir) if district_dir else DISTRICT_DIR
        )
        self._lock = threading.Lock()
        # The handle of the process this instance launched, if any.
        # poll() is the authoritative same-process liveness check (and
        # reaps the child); the PID probe covers fresh instances.
        self._proc: subprocess.Popen | None = None

    def _alive(self, pid: int) -> bool:
        """Liveness check that cannot be fooled by zombie children.

        Our own Popen handle is authoritative (poll() reaps); otherwise
        fall back to the PID probe, which reaps-then-probes.
        """
        proc = self._proc
        if proc is not None and proc.pid == pid:
            return proc.poll() is None
        return _pid_alive(pid)

    # -- public ---------------------------------------------------------

    def read_status(self) -> dict:
        """The current showcase state, re-read from disk every call.

        Finalises a run whose process has exited: the state becomes
        complete/failed based on the log's own markers, never on a guess.
        """
        with self._lock:
            status = self._load()
            if status.get("state") == "running" and not self._alive(
                int(status.get("pid", -1))
            ):
                status = self._finalise(status)
                self._proc = None
                self._save(status)
            return status

    def start(self) -> dict:
        """Launch the demo unless one is already running.

        Returns {"started": True, ...} or {"started": False,
        "reason": "already_running"}. Never starts a second process.
        """
        with self._lock:
            status = self._load()
            if status.get("state") == "running" and self._alive(
                int(status.get("pid", -1))
            ):
                return {"started": False, "reason": "already_running"}

            self._status_path.parent.mkdir(parents=True, exist_ok=True)
            log_file = open(self._log_path, "w", encoding="utf-8")
            try:
                proc = subprocess.Popen(
                    self._demo_cmd,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    cwd=REPO_ROOT,
                )
            except Exception:
                log_file.close()
                raise
            # The child inherits the file object; the parent closes its copy.
            log_file.close()
            self._proc = proc

            status = {
                "state": "running",
                "pid": proc.pid,
                "variant": DEMO_VARIANT,
                "started_at": _utcnow(),
            }
            self._save(status)
            return {"started": True, **status}

    def phase(self) -> str:
        """The current demo phase, from the log's own marker lines."""
        return self._phase_from_log(self._tail_lines(400))

    def progress_phase(self) -> str:
        """The furthest non-terminal phase reached, for the step list.

        When the run fails, the banner says FAILED but the steps still
        show how far the demo actually got.
        """
        text = "\n".join(self._tail_lines(400))
        for phase, marker in _PHASE_MARKERS:
            if phase in ("complete", "failed"):
                continue
            if marker in text:
                return phase
        return "ready"

    def phase_copy(self, phase: str) -> tuple[str, str]:
        """The (title, description) shown for a phase."""
        return _PHASE_COPY.get(phase, _PHASE_COPY["ready"])

    def steps(self) -> tuple[str, ...]:
        return _STEPS

    def log_tail(self, lines: int = 40) -> str:
        """The last lines of the demo's own output, unedited."""
        return "\n".join(self._tail_lines(lines))

    def report_figures(self) -> dict:
        """Real numbers from the run's own report -- or nothing.

        Only keys actually present in demo_run.json are returned, so the
        page can never show a figure the run did not produce.
        """
        from nightkeep.console.providers import load_report

        return figures_from_report(load_report(self._district_dir))

    # -- internals ------------------------------------------------------

    def _load(self) -> dict:
        try:
            data = json.loads(self._status_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"state": "ready"}
        if not isinstance(data, dict):
            return {"state": "ready"}
        if data.get("state") not in ("ready", "running", "complete", "failed"):
            return {"state": "ready"}
        return data

    def _save(self, status: dict) -> None:
        self._status_path.parent.mkdir(parents=True, exist_ok=True)
        self._status_path.write_text(
            json.dumps(status, indent=2), encoding="utf-8"
        )

    def _finalise(self, status: dict) -> dict:
        """A dead process ends the run; the log says how it ended."""
        tail = "\n".join(self._tail_lines(400))
        if "--- proof PASSED ---" in tail:
            state = "complete"
        elif "--- proof FAILED ---" in tail:
            state = "failed"
        elif _CANNOT_RUN_MARKER in tail:
            state = "failed"
            status["note"] = (
                "The demo cannot run on this machine "
                "(missing Windows scripting host)."
            )
        else:
            state = "failed"
            status["note"] = (
                "The demo process exited without writing a final verdict."
            )
        status["state"] = state
        status["finished_at"] = _utcnow()
        return status

    def _tail_lines(self, count: int) -> list[str]:
        try:
            text = self._log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        lines = text.splitlines()
        return lines[-count:]

    def _phase_from_log(self, lines: list[str]) -> str:
        text = "\n".join(lines)
        for phase, marker in _PHASE_MARKERS:
            if marker in text:
                return phase
        return "starting" if text.strip() else "ready"


def figures_from_report(report) -> dict:
    """Real numbers from a run's own report, or nothing.

    Only keys actually present are returned, so the page can never show a
    figure the run did not produce.
    """
    figures: dict = {}
    if not isinstance(report, dict):
        return figures
    restore = report.get("restore")
    if isinstance(restore, dict):
        if isinstance(restore.get("records_verified"), int):
            figures["records_verified"] = restore["records_verified"]
        if isinstance(restore.get("records_expected"), int):
            figures["records_expected"] = restore["records_expected"]
    attack = report.get("attack")
    if isinstance(attack, dict):
        latency = attack.get("detection_latency_seconds")
        if isinstance(latency, (int, float)):
            figures["detection_latency_seconds"] = latency
        affected = attack.get("affected_files_at_incident")
        if isinstance(affected, int):
            figures["affected_files_at_incident"] = affected
        if isinstance(attack.get("level"), str):
            figures["attack_level"] = attack["level"]
    if isinstance(report.get("variant"), str):
        figures["variant"] = report["variant"]
    if isinstance(report.get("seed"), int):
        figures["seed"] = report["seed"]
    return figures


# The live engine's phases, as the showcase's steps.
_LIVE_PHASE_STEP = {
    "starting": "starting",
    "learning": "learning",
    "guard": "guard",
    "attack": "attack",
    "containment": "containment",
    "vault": "vault",
    "contained": "vault",
    "recovery": "recovery",
    "recovered": "recovery",
    "complete": "complete",
    "failed": "failed",
}


class LiveShowcase:
    """The Live Demo page, driven through the console's live session.

    "Start guided demo" restarts the live session on autopilot: the same
    engine the step-by-step controls steer, so every screen shows this one run. The
    engine learns, guards, attacks with the configured variant, restores and
    writes the same proof lines demo_run prints. This class only words its
    status: the phase, the figures and the log all come from the engine.
    """

    def __init__(self, session, variant: str) -> None:
        self._session = session
        self._variant = variant

    def _autopilot_status(self) -> dict:
        status = self._session.status()
        return status if status.get("mode") == "autopilot" else {}

    def read_status(self) -> dict:
        status = self._autopilot_status()
        if not status:
            if self._session.is_running() and not self._session.status().get("mode"):
                # Just restarted: the engine has not written its mode yet.
                return {"state": "running"}
            return {"state": "ready"}
        phase = status.get("phase")
        if phase == "complete":
            return {"state": "complete"}
        if phase in ("failed", "stopped"):
            return {"state": "failed",
                    "note": status.get("error") or status.get("note")}
        return {"state": "running"}

    def start(self) -> dict:
        if self.read_status().get("state") == "running":
            return {"started": False, "reason": "already_running"}
        self._session.start(autopilot=True, variant=self._variant)
        return {"started": True, "variant": self._variant}

    def phase(self) -> str:
        status = self._autopilot_status()
        if not status:
            return "starting" if self.read_status()["state"] == "running" else "ready"
        return _LIVE_PHASE_STEP.get(status.get("phase"), "starting")

    def progress_phase(self) -> str:
        """How far a failed run got, from what its report records."""
        report = self._session.report()
        if report.get("restore"):
            return "recovery"
        if report.get("attack"):
            return "vault"
        if report.get("guard_days"):
            return "guard"
        if report.get("learning_days"):
            return "learning"
        return "ready"

    def phase_copy(self, phase: str) -> tuple[str, str]:
        return _PHASE_COPY.get(phase, _PHASE_COPY["ready"])

    def steps(self) -> tuple[str, ...]:
        return _STEPS

    def log_tail(self, lines: int = 40) -> str:
        return self._session.log_tail(lines)

    def report_figures(self) -> dict:
        return figures_from_report(self._session.report())
