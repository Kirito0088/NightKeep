"""The safe ransomware simulator and its decrypt script.

Three Round-2 variants, each a real subprocess so the watcher can attribute
its file events and the judge can suspend it mid-run:

- ``fast_encrypt`` scrambles files in place and renames them to ``.locked``.
- ``impersonate`` stages a disposable malicious ``nightly_export.py`` and
  runs it with the scheduler's exact argv shape.
- ``recovery_killer`` does a short burst of encryption, then lingers as a
  shell whose command line only *echoes* recovery-killing text.
- ``watcher_killer`` terminates the Watcher agent process, so the Vault's
  S6 liveness check goes silent and no more events are recorded. It
  touches no files at all.

Safety rails. Every one is enforced in code and covered by tests, not just
promised in this docstring:

- The boundary is hard-coded, not configured: every variant resolves its
  target and refuses anything outside the repository's ``demo/`` folder.
  ``..`` escapes and symlink escapes fail closed.
- ``logs/`` and ``data/`` are never listed, read or written. The
  ground-truth logs and the live database (and the judge's own baseline
  database) are out of the blast radius. The database story belongs to the
  backup files in ``share/backups/``, which is where the Vault watches.
- Encryption is a SHA-256 counter-mode keystream XORed with the file bytes,
  under a known key, so ``decrypt.py`` always reverses it. A keyed magic
  header makes a wrong key fail closed instead of producing garbage.
- The strings ``vssadmin``, ``wbadmin`` and ``bcdedit`` appear only inside
  echoed text. The simulator never executes them, never spawns those
  binaries, never touches the network, and never leaves the demo folder.
- The tracked ``nightkeep/mock_pds/jobs/nightly_export.py`` is never
  written. The impersonator works on a disposable staged copy inside the
  demo folder and removes it afterwards.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import psutil

# The one folder the simulator may touch. Hard-coded, not a tunable: a
# boundary someone can configure away is not a boundary.
DEMO_DIR = Path(__file__).resolve().parent.parent.parent / "demo"

# Where the impersonator stages its disposable malicious job script.
_STAGING_DIR_NAME = ".nightkeep-sim"

# Nothing under here may ever be opened, by anything, for any reason.
_TRUTH_FOLDER = "_truth"

# Top-level folders inside the demo dir the simulator never enters.
_OFF_LIMITS = frozenset({"logs", "data", _STAGING_DIR_NAME})

_JOB_SCRIPT_NAME = "nightly_export.py"


class SimulatorRefused(Exception):
    """The boundary said no. Fail closed, and say why."""


class DecryptRefused(Exception):
    """decrypt.py will not touch this: wrong key, or not our file."""


@dataclass
class AttackReport:
    """What one variant did. The demo runner and the tests read this."""

    variant: str
    root: Path
    files_encrypted: int = 0
    files_renamed: int = 0
    notes_written: int = 0
    staging_dir: Path | None = None
    killed_pids: tuple[int, ...] = ()


@dataclass
class DecryptReport:
    """What decrypt.py put back."""

    root: Path
    files_restored: int = 0
    notes_removed: int = 0


# --- the boundary ----------------------------------------------------------


def guard_root(root: str | Path) -> Path:
    """Resolve ``root`` and prove it is inside the demo folder.

    Raises :class:`SimulatorRefused` for anything outside it, for ``..``
    escapes (``resolve()`` collapses them first, and also resolves symlinks),
    and for anything that is not a directory. Fail closed: when in doubt,
    refuse.
    """
    candidate = Path(root).resolve()
    try:
        candidate.relative_to(DEMO_DIR)
    except ValueError:
        raise SimulatorRefused(
            f"the simulator only runs inside the demo folder ({DEMO_DIR}); "
            f"refusing {candidate}"
        )
    if not candidate.is_dir():
        raise SimulatorRefused(f"not a directory: {candidate}")
    return candidate


def _targets(
    root: Path, locked_extension: str, ransom_note_name: str
) -> list[Path]:
    """Every file the simulator may touch, sorted for determinism.

    Skips the off-limits folders, the truth folder wherever it hides, ransom
    notes from a previous run, files that are already locked, and empty
    files (there is nothing to scramble in them).
    """
    found = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if relative.parts[0] in _OFF_LIMITS:
            continue
        if _TRUTH_FOLDER in relative.parts:
            continue
        if path.name == ransom_note_name:
            continue
        if path.name.endswith(locked_extension):
            continue
        if path.stat().st_size == 0:
            continue
        found.append(path)
    return found


# --- the cipher ------------------------------------------------------------

# A real sample would never ship its key. That is exactly the point: this is
# a rehearsal, and the drill is only useful if everything can be put back.


def _magic_for(key: str) -> bytes:
    """Eight keyed bytes prepended to every encrypted file.

    Keyed, not fixed, so decrypting with the wrong key fails the magic check
    and refuses instead of silently producing garbage.
    """
    return hashlib.sha256(b"nightkeep-sim-v1" + key.encode("utf-8")).digest()[:8]


def _keystream(key: bytes, tag: str, length: int) -> bytes:
    """Deterministic pseudo-random stream: SHA-256 in counter mode."""
    out = bytearray()
    tag_bytes = tag.encode("utf-8")
    counter = 0
    while len(out) < length:
        out += hashlib.sha256(
            key + b"\x00" + tag_bytes + b"\x00" + counter.to_bytes(8, "big")
        ).digest()
        counter += 1
    return bytes(out[:length])


def _crypt(data: bytes, key: str, tag: str) -> bytes:
    """XOR with the keystream. Encryption and decryption are the same call."""
    stream = _keystream(key.encode("utf-8"), tag, len(data))
    return bytes(first ^ second for first, second in zip(data, stream))


# --- the ransom note ---------------------------------------------------------


def _note_text(commands_echoed: tuple[str, ...] = ()) -> str:
    lines = [
        "NIGHTKEEP DRILL: SIMULATED RANSOMWARE",
        "====================================",
        "This is a rehearsal on invented data. No real system is affected.",
        "Every file was scrambled with a known key and can be restored with:",
        "  python -m nightkeep.simulator.decrypt --root <demo folder>",
    ]
    if commands_echoed:
        lines += [
            "",
            "The following recovery commands were echoed (never run):",
        ]
        lines += [f"  echo {command}" for command in commands_echoed]
    return "\n".join(lines) + "\n"


# --- variant 1: the fast encryptor -------------------------------------------


def _write_notes(
    locked_paths: list[Path],
    ransom_note_name: str,
    note_extra: tuple[str, ...],
) -> int:
    """A ransom note in every folder that was touched, as real ransomware does."""
    folders = sorted({path.parent for path in locked_paths})
    for folder in folders:
        (folder / ransom_note_name).write_text(_note_text(note_extra))
    return len(folders)


def fast_encrypt(
    root: str | Path,
    *,
    key: str,
    locked_extension: str,
    ransom_note_name: str,
    delay_between_files_seconds: float,
    limit: int | None = None,
    note_extra: tuple[str, ...] = (),
) -> AttackReport:
    """Scramble files in place, rename them to the locked extension.

    In-place rewrite plus rename is the combination the tripwires look for:
    S3 on the scrambled content, S4 on the rename burst, S2 if a planted
    trap file is caught in the blast radius. ``limit`` caps the run for the
    recovery-killer's short burst and for tests.
    """
    root = guard_root(root)
    targets = _targets(root, locked_extension, ransom_note_name)
    if limit is not None:
        targets = targets[:limit]

    magic = _magic_for(key)
    report = AttackReport(variant="fast", root=root)
    locked_paths: list[Path] = []
    for path in targets:
        tag = path.relative_to(root).as_posix()
        data = path.read_bytes()
        path.write_bytes(magic + _crypt(data, key, tag))
        locked = path.with_name(path.name + locked_extension)
        path.rename(locked)
        locked_paths.append(locked)
        report.files_encrypted += 1
        report.files_renamed += 1
        if delay_between_files_seconds:
            time.sleep(delay_between_files_seconds)

    report.notes_written = _write_notes(locked_paths, ransom_note_name, note_extra)
    return report


# --- variant 2: the impersonator -----------------------------------------------

# The malicious job cannot import nightkeep: the scheduler runs .py jobs
# under `python -I` (isolated mode), which keeps this repository off the
# import path. So the staging template is self-contained stdlib, with the
# encrypt/decrypt logic deliberately duplicated. @TOKENS@ are replaced when
# the copy is staged.


_MALICIOUS_JOB_TEMPLATE = '''"""Staged by nightkeep.simulator.impersonate(). A disposable stand-in.

Accepts the scheduler's argv shape (--root, --day, --sim-start, --sim-end)
and then scrambles the demo folder instead of writing exports. Same
filename as the real job, different bytes: that is the impersonation the
SHA-256 identity check is for. Removed by cleanup_staging().
"""

import argparse
import hashlib
import time
from pathlib import Path

_KEY = "@KEY@"
_LOCKED = "@LOCKED@"
_NOTE = "@NOTE@"
_DELAY = @DELAY@
_MAGIC = "@MAGIC@"


def _keystream(tag, length):
    out = bytearray()
    tag_bytes = tag.encode("utf-8")
    counter = 0
    while len(out) < length:
        out += hashlib.sha256(
            _KEY.encode("utf-8") + b"\\x00" + tag_bytes + b"\\x00"
            + counter.to_bytes(8, "big")
        ).digest()
        counter += 1
    return bytes(out[:length])


def _crypt(data, tag):
    stream = _keystream(tag, len(data))
    return bytes(a ^ b for a, b in zip(data, stream))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--day", default="8")
    parser.add_argument("--sim-start", default="")
    parser.add_argument("--sim-end", default="")
    args = parser.parse_args()

    root = Path(args.root)
    locked_count = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if relative.parts[0] in ("logs", "data", ".nightkeep-sim"):
            continue
        if "_truth" in relative.parts:
            continue
        if path.name == _NOTE or path.name.endswith(_LOCKED):
            continue
        if path.stat().st_size == 0:
            continue
        tag = relative.as_posix()
        data = path.read_bytes()
        path.write_bytes(bytes.fromhex(_MAGIC) + _crypt(data, tag))
        path.rename(path.with_name(path.name + _LOCKED))
        locked_count += 1
        if _DELAY:
            time.sleep(_DELAY)
    print(f"impersonator locked {locked_count} files")


if __name__ == "__main__":
    main()
'''


def _malicious_job_source(
    *,
    key: str,
    locked_extension: str,
    ransom_note_name: str,
    delay_between_files_seconds: float,
) -> str:
    source = _MALICIOUS_JOB_TEMPLATE
    source = source.replace("@KEY@", key.replace("\\", "\\\\").replace('"', '\\"'))
    source = source.replace("@LOCKED@", locked_extension)
    source = source.replace("@NOTE@", ransom_note_name)
    source = source.replace("@DELAY@", repr(delay_between_files_seconds))
    source = source.replace("@MAGIC@", _magic_for(key).hex())
    return source


def impersonate(
    root: str | Path,
    *,
    day_no: int,
    sim_start: datetime,
    sim_end: datetime,
    key: str,
    locked_extension: str,
    ransom_note_name: str,
    delay_between_files_seconds: float,
) -> AttackReport:
    """Run the attack wearing the nightly export job's name.

    Stages a disposable malicious ``nightly_export.py`` inside the demo
    folder and launches it with the scheduler's exact argv shape for a .py
    job (``nightkeep/mock_pds/_day.py``): ``[sys.executable, "-I", script,
    "--root", ..., "--day", ..., "--sim-start", ..., "--sim-end", ...]``.
    Same executable flag, same script filename, different bytes, so the
    watcher attributes the damage to the familiar job name while the
    SHA-256 identity check sees a stranger. The tracked job script in the
    repository is never touched; the staged copy is removed by
    :func:`cleanup_staging`.
    """
    root = guard_root(root)
    staging = root / _STAGING_DIR_NAME
    staging.mkdir(parents=True, exist_ok=True)
    staged = staging / _JOB_SCRIPT_NAME
    staged.write_text(
        _malicious_job_source(
            key=key,
            locked_extension=locked_extension,
            ransom_note_name=ransom_note_name,
            delay_between_files_seconds=delay_between_files_seconds,
        )
    )

    before = _locked_count(root, locked_extension)
    command = [
        sys.executable, "-I", str(staged),
        "--root", str(root),
        "--day", str(day_no),
        "--sim-start", sim_start.isoformat(),
        "--sim-end", sim_end.isoformat(),
    ]
    subprocess.run(command, check=True)

    locked_now = [
        path
        for path in sorted(root.rglob(f"*{locked_extension}"))
        if path.is_file() and path.relative_to(root).parts[0] not in _OFF_LIMITS
    ]
    fresh = len(locked_now) - before
    report = AttackReport(
        variant="impersonator",
        root=root,
        files_encrypted=fresh,
        files_renamed=fresh,
        staging_dir=staging,
    )
    report.notes_written = _write_notes(locked_now, ransom_note_name, ())
    return report


def _locked_count(root: Path, locked_extension: str) -> int:
    return sum(
        1
        for path in root.rglob(f"*{locked_extension}")
        if path.is_file() and path.relative_to(root).parts[0] not in _OFF_LIMITS
    )


def cleanup_staging(root: str | Path) -> None:
    """Remove the impersonator's disposable staged copy. Nothing else."""
    root = guard_root(root)
    staging = root / _STAGING_DIR_NAME
    if staging.is_dir():
        shutil.rmtree(staging)


# --- variant 3: the recovery-killer --------------------------------------------


def _echo_shell_argv(commands: tuple[str, ...], linger_seconds: int) -> list[str]:
    """A shell whose command line carries the recovery-killing text.

    The text is echoed, never executed. It lingers so the judge's process
    scan (S5) can see it, and so there is something to suspend on INCIDENT.
    """
    echoed = "; ".join(f"echo {command}" for command in commands)
    if os.name == "nt":
        return ["cmd.exe", "/c", f"{echoed} & timeout /t {linger_seconds} >nul"]
    return ["sh", "-c", f"{echoed}; sleep {linger_seconds}"]


def recovery_killer(
    root: str | Path,
    *,
    key: str,
    locked_extension: str,
    ransom_note_name: str,
    delay_between_files_seconds: float,
    commands: tuple[str, ...],
    encrypt_limit: int = 12,
    linger_seconds: int = 600,
    shell_first: bool = False,
) -> AttackReport:
    """A short burst of encryption, then the recovery-killing echo.

    Real recovery-killers encrypt first and destroy the way back second.
    The burst trips S3/S4; the lingering echo shell trips S5; together the
    verdict table calls it INCIDENT. The shell only ever echoes the command
    text: ``vssadmin`` and friends appear in an argv, never in an exec.

    ``shell_first`` is a test seam, off by default: it spawns the echo
    shell before the burst so S5 is observable from the very first live
    verdict instead of racing the encryption burst. The default order --
    and therefore the real drill -- is unchanged.
    Blocks until the echo shell exits (or is suspended/killed from outside).
    """
    root = guard_root(root)
    shell = None
    if shell_first:
        shell = subprocess.Popen(_echo_shell_argv(commands, linger_seconds))
    report = fast_encrypt(
        root,
        key=key,
        locked_extension=locked_extension,
        ransom_note_name=ransom_note_name,
        delay_between_files_seconds=delay_between_files_seconds,
        limit=encrypt_limit,
        note_extra=commands,
    )
    report.variant = "recovery-killer"

    process = shell if shell is not None else subprocess.Popen(
        _echo_shell_argv(commands, linger_seconds)
    )
    try:
        process.wait()
    finally:
        if process.poll() is None:
            process.terminate()
    return report


# --- variant 4: the watcher-killer -------------------------------------------

# The dedicated marker the watcher agent runs with, plus the demo root.
# A process is only ever touched when its command line carries all of
# these; anything else -- this process, its parent, a pytest run, another
# demo -- is left alone.
_WATCHER_MODULE = "nightkeep.watcher"
_WATCHER_RUN_FLAG = "--run"


def _is_watcher_agent(cmdline: list[str], root: str) -> bool:
    """The dedicated marker plus the correct demo root, nothing less.

    Exact argv-element matching, not substring: a demo rooted at
    ``.../district`` must never match an agent for ``.../district2``.
    """
    return (
        _WATCHER_MODULE in cmdline
        and _WATCHER_RUN_FLAG in cmdline
        and root in cmdline
    )


def watcher_killer(root: str | Path) -> AttackReport:
    """Terminate the Watcher agent for this demo root.

    What an attacker with admin rights does first: stop the security tool,
    then work in the dark. The kill is real -- SIGTERM to the agent
    process -- which is why the agent runs as its own process rather than
    inside the demo: killing it must not kill the demonstration. Both the
    watching and the heartbeats stop with it.

    Safety: only a process whose command line carries the dedicated
    ``--run`` marker *and* this demo root is touched. This process
    and its parent are never candidates, no matter what they are called.
    Touches no files; the demo-folder boundary still applies to the root.
    """
    root = guard_root(root)
    me, parent = os.getpid(), os.getppid()
    root_text = str(root)

    targets: list[psutil.Process] = []
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            pid = proc.info["pid"]
            if pid in (me, parent):
                continue
            cmdline = proc.info["cmdline"] or []
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if _is_watcher_agent([str(part) for part in cmdline], root_text):
            targets.append(proc)

    killed: list[int] = []
    for proc in targets:
        try:
            proc.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        try:
            proc.wait(timeout=5)
        except psutil.TimeoutExpired:
            try:
                proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        killed.append(proc.pid)

    report = AttackReport(variant="watcher-killer", root=root)
    report.killed_pids = tuple(killed)
    return report


# --- decrypt -----------------------------------------------------------------


def decrypt_tree(
    root: str | Path, *, key: str, locked_extension: str, ransom_note_name: str
) -> DecryptReport:
    """Reverse the simulator: decrypt ``*.locked`` files, remove the notes.

    Fails closed: a file whose keyed magic does not match raises
    :class:`DecryptRefused` instead of writing garbage. Also removes the
    impersonator's staging directory, so the demo folder is left clean.
    """
    root = guard_root(root)
    magic = _magic_for(key)
    report = DecryptReport(root=root)

    locked_files = sorted(root.rglob(f"*{locked_extension}"))
    for locked in locked_files:
        if not locked.is_file():
            continue
        relative = locked.relative_to(root)
        if relative.parts[0] in _OFF_LIMITS:
            continue
        if _TRUTH_FOLDER in relative.parts:
            continue
        data = locked.read_bytes()
        if not data.startswith(magic):
            raise DecryptRefused(
                f"not a simulator-encrypted file (wrong key?): "
                f"{relative.as_posix()}"
            )
        tag = relative.as_posix()[: -len(locked_extension)]
        restored = locked.with_name(locked.name[: -len(locked_extension)])
        restored.write_bytes(_crypt(data[len(magic):], key, tag))
        locked.unlink()
        report.files_restored += 1

    for note in sorted(root.rglob(ransom_note_name)):
        if not note.is_file():
            continue
        relative = note.relative_to(root)
        if relative.parts[0] in _OFF_LIMITS or _TRUTH_FOLDER in relative.parts:
            continue
        note.unlink()
        report.notes_removed += 1

    cleanup_staging(root)
    return report


__all__ = [
    "DEMO_DIR",
    "AttackReport",
    "DecryptReport",
    "DecryptRefused",
    "SimulatorRefused",
    "cleanup_staging",
    "decrypt_tree",
    "fast_encrypt",
    "guard_root",
    "impersonate",
    "recovery_killer",
    "watcher_killer",
]
