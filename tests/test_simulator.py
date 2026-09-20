"""Tests for the safe ransomware simulator (F10).

Proves the safety rails by behaviour: the boundary refuses, the truth
folder survives, the tracked job script is never modified, and the
recovery-killing commands are only ever echoed. Proves the drill by
round-trip: encrypt, then decrypt, and every byte comes back.
"""

import hashlib
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import psutil
import pytest

from nightkeep import simulator
from nightkeep.judge import entropy_signal

REPO_ROOT = simulator.DEMO_DIR.parent
KEY = "nightkeep-demo-key-not-a-secret"
LOCKED = ".locked"
NOTE = "HOW_TO_GET_YOUR_FILES_BACK.txt"
COMMANDS = (
    "vssadmin delete shadows",
    "wbadmin delete catalog",
    "bcdedit /set recoveryenabled no",
)
# The trap path from config.yaml's judge.trap_files. The simulator does not
# know it: the fast encryptor just encrypts everything it finds, and the
# trap is caught in the blast radius like a real attack would catch it.
TRAP = "share/exports/epos_day_end_20240101.csv"

CSV_BODY = (
    "transaction_id,card_no,fps_id,occurred_at,allotment_month,"
    "commodity,quantity_kg,auth_mode,status\n"
)
CSV_ROW = "48291011,112233445566,7,2026-09-21T02:14:00,2026-09,rice,5.0,otp,ok\n"


def _csv_rows(count: int) -> bytes:
    return (CSV_BODY + CSV_ROW * count).encode("utf-8")


@pytest.fixture
def demo_root():
    """A disposable district inside the demo folder.

    The boundary is hard-coded to demo/, so the fixture must live under it:
    this also proves the guard accepts a real demo dir. Removed afterwards.
    """
    base = simulator.DEMO_DIR / ".sim-tests" / uuid4().hex
    (base / "share" / "exports").mkdir(parents=True)
    (base / "share" / "allocations").mkdir(parents=True)
    (base / "share" / "backups").mkdir(parents=True)
    (base / "reports").mkdir(parents=True)
    (base / "archive").mkdir(parents=True)
    (base / "logs" / "_truth").mkdir(parents=True)
    (base / "data").mkdir(parents=True)

    for i in range(14):
        (base / "share" / "exports" / f"quota_2024_{i:02d}.csv").write_bytes(
            _csv_rows(20 + i)
        )
    (base / TRAP).write_bytes(_csv_rows(10))
    (base / "share" / "allocations" / "fps_quota.csv").write_bytes(_csv_rows(15))
    (base / "share" / "backups" / "district_backup.db").write_bytes(
        b"SQLite format 3\x00" + bytes(range(256)) * 40
    )
    (base / "reports" / "day_end.csv").write_bytes(_csv_rows(30))
    (base / "archive" / "old_export.csv").write_bytes(_csv_rows(5))
    (base / "logs" / "_truth" / "nightly_export.truth.log").write_bytes(
        b"ground truth: the job wrote 14 files\n"
    )
    (base / "data" / "district.db").write_bytes(
        b"SQLite format 3\x00" + bytes(range(256)) * 100
    )
    yield base
    shutil.rmtree(base, ignore_errors=True)


def _encrypt_kwargs(**overrides):
    kwargs = dict(
        key=KEY,
        locked_extension=LOCKED,
        ransom_note_name=NOTE,
        delay_between_files_seconds=0,
    )
    kwargs.update(overrides)
    return kwargs


# --- the boundary ------------------------------------------------------------


def test_guard_refuses_outside_demo(tmp_path):
    with pytest.raises(simulator.SimulatorRefused):
        simulator.guard_root(tmp_path)


def test_guard_refuses_dotdot_escape():
    with pytest.raises(simulator.SimulatorRefused):
        simulator.guard_root(simulator.DEMO_DIR / ".." / "outside-demo")


def test_variants_refuse_outside_demo(tmp_path):
    with pytest.raises(simulator.SimulatorRefused):
        simulator.fast_encrypt(tmp_path, **_encrypt_kwargs())
    with pytest.raises(simulator.SimulatorRefused):
        simulator.decrypt_tree(
            tmp_path, key=KEY, locked_extension=LOCKED, ransom_note_name=NOTE
        )


def test_guard_accepts_demo_subdir(demo_root):
    assert simulator.guard_root(demo_root) == demo_root.resolve()


# --- the fast encryptor --------------------------------------------------------


def test_fast_encrypt_locks_everything_it_finds(demo_root):
    report = simulator.fast_encrypt(demo_root, **_encrypt_kwargs())
    assert report.files_encrypted == 19
    assert report.files_renamed == 19
    remaining = [
        p for p in demo_root.rglob("*.csv")
        if p.is_file() and not p.name.endswith(LOCKED)
    ]
    assert remaining == []
    assert (demo_root / "share" / "backups" / "district_backup.db.locked").exists()


def test_fast_encrypt_never_touches_truth_or_data(demo_root):
    truth = demo_root / "logs" / "_truth" / "nightly_export.truth.log"
    live_db = demo_root / "data" / "district.db"
    truth_before = truth.read_bytes()
    db_before = live_db.read_bytes()
    simulator.fast_encrypt(demo_root, **_encrypt_kwargs())
    assert truth.read_bytes() == truth_before
    assert live_db.read_bytes() == db_before
    assert not (demo_root / "logs" / "_truth" / "nightly_export.truth.log.locked").exists()


def test_fast_encrypt_catches_trap_in_blast_radius(demo_root):
    """S2's precondition: a planted trap file modified and renamed."""
    simulator.fast_encrypt(demo_root, **_encrypt_kwargs())
    assert (demo_root / (TRAP + LOCKED)).exists()
    assert not (demo_root / TRAP).exists()


def test_fast_encrypt_reaches_rename_burst(demo_root):
    """S4's precondition: >= 10 renames to an extension no job produces."""
    report = simulator.fast_encrypt(demo_root, **_encrypt_kwargs())
    assert report.files_renamed >= 10


def test_encrypted_csv_trips_s3_preconditions(demo_root):
    """The real signal helpers, on real simulator output."""
    target = demo_root / "share" / "exports" / "quota_2024_00.csv"
    before = target.read_bytes()
    simulator.fast_encrypt(demo_root, **_encrypt_kwargs())
    data = target.with_name(target.name + LOCKED).read_bytes()
    assert entropy_signal.entropy(data) >= 7.0
    assert entropy_signal.header_state(data, ".csv") == "broken"
    result = entropy_signal.inspect(
        data=data,
        extension=".csv",
        was_existing=True,
        entropy_before=entropy_signal.entropy(before),
        entropy_jump=1.5,
        entropy_floor=7.0,
    )
    assert result.fired


def test_ransom_note_in_every_touched_folder(demo_root):
    report = simulator.fast_encrypt(demo_root, **_encrypt_kwargs())
    notes = list(demo_root.rglob(NOTE))
    assert len(notes) == report.notes_written > 0
    assert (demo_root / "share" / "exports" / NOTE).exists()
    assert (demo_root / "reports" / NOTE).exists()


def test_second_run_skips_locked_files(demo_root):
    first = simulator.fast_encrypt(demo_root, **_encrypt_kwargs())
    second = simulator.fast_encrypt(demo_root, **_encrypt_kwargs())
    assert second.files_encrypted == 0
    assert first.files_encrypted > 0


# --- decrypt -------------------------------------------------------------------


def test_decrypt_roundtrip_is_byte_identical(demo_root):
    originals = {
        p.relative_to(demo_root).as_posix(): p.read_bytes()
        for p in demo_root.rglob("*")
        if p.is_file()
    }
    simulator.fast_encrypt(demo_root, **_encrypt_kwargs())
    report = simulator.decrypt_tree(
        demo_root, key=KEY, locked_extension=LOCKED, ransom_note_name=NOTE
    )
    assert report.files_restored == 19
    assert report.notes_removed > 0
    assert list(demo_root.rglob(f"*{LOCKED}")) == []
    assert list(demo_root.rglob(NOTE)) == []
    for relative, data in originals.items():
        assert (demo_root / relative).read_bytes() == data, relative


def test_decrypt_wrong_key_refuses(demo_root):
    simulator.fast_encrypt(demo_root, **_encrypt_kwargs())
    with pytest.raises(simulator.DecryptRefused):
        simulator.decrypt_tree(
            demo_root,
            key="some-other-key",
            locked_extension=LOCKED,
            ransom_note_name=NOTE,
        )


def test_decrypt_refuses_foreign_locked_file(demo_root):
    (demo_root / "share" / "exports" / f"plain{LOCKED}").write_bytes(b"not ours")
    with pytest.raises(simulator.DecryptRefused):
        simulator.decrypt_tree(
            demo_root, key=KEY, locked_extension=LOCKED, ransom_note_name=NOTE
        )


# --- the impersonator ------------------------------------------------------------


def _tracked_job() -> Path:
    return (
        Path(simulator.__file__).resolve().parent.parent
        / "mock_pds" / "jobs" / "nightly_export.py"
    )


def test_impersonator_uses_scheduler_argv_shape(demo_root, monkeypatch):
    """The exact argv the scheduler builds for a .py job in _day.py."""
    seen: list[list[str]] = []
    real_run = subprocess.run

    def fake_run(command, **kwargs):
        seen.append(command)
        return real_run(["true"], **kwargs)

    monkeypatch.setattr(subprocess, "run", fake_run)
    sim_start = datetime(2026, 9, 22, 2, 14, 0)
    sim_end = datetime(2026, 9, 22, 6, 0, 0)
    simulator.impersonate(
        demo_root,
        day_no=8,
        sim_start=sim_start,
        sim_end=sim_end,
        **_encrypt_kwargs(),
    )
    assert len(seen) == 1
    staged = demo_root / ".nightkeep-sim" / "nightly_export.py"
    assert seen[0] == [
        sys.executable, "-I", str(staged),
        "--root", str(demo_root),
        "--day", "8",
        "--sim-start", sim_start.isoformat(),
        "--sim-end", sim_end.isoformat(),
    ]


def test_impersonator_never_modifies_tracked_job(demo_root):
    tracked = _tracked_job()
    digest_before = hashlib.sha256(tracked.read_bytes()).hexdigest()
    mtime_before = tracked.stat().st_mtime

    report = simulator.impersonate(
        demo_root,
        day_no=8,
        sim_start=datetime(2026, 9, 22, 2, 14, 0),
        sim_end=datetime(2026, 9, 22, 6, 0, 0),
        **_encrypt_kwargs(),
    )

    assert hashlib.sha256(tracked.read_bytes()).hexdigest() == digest_before
    assert tracked.stat().st_mtime == mtime_before
    assert report.files_encrypted == 19

    # Same filename as the real job, different bytes: that is the
    # impersonation the SHA-256 identity check is for.
    staged = demo_root / ".nightkeep-sim" / "nightly_export.py"
    assert staged.name == tracked.name
    assert hashlib.sha256(staged.read_bytes()).hexdigest() != digest_before

    simulator.cleanup_staging(demo_root)
    assert not (demo_root / ".nightkeep-sim").exists()


def test_impersonator_staged_script_parses_scheduler_args(demo_root):
    """The staged copy really accepts the scheduler's argv and runs alone."""
    simulator.impersonate(
        demo_root,
        day_no=8,
        sim_start=datetime(2026, 9, 22, 2, 14, 0),
        sim_end=datetime(2026, 9, 22, 6, 0, 0),
        **_encrypt_kwargs(),
    )
    assert (demo_root / "reports" / f"day_end.csv{LOCKED}").exists()


# --- the recovery-killer ---------------------------------------------------------


def test_recovery_killer_only_echoes(demo_root):
    """The command text appears in a shell's argv; the binaries never run."""
    errors: list[str] = []

    def run():
        try:
            simulator.recovery_killer(
                demo_root,
                commands=COMMANDS,
                encrypt_limit=2,
                linger_seconds=6,
                **_encrypt_kwargs(),
            )
        except Exception as exc:  # noqa: BLE001 - surfaced below
            errors.append(str(exc))

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    try:
        found = None
        deadline = time.time() + 15
        while time.time() < deadline and found is None:
            for proc in psutil.process_iter(["name", "cmdline"]):
                try:
                    name = (proc.info["name"] or "").lower()
                    cmdline = " ".join(proc.info["cmdline"] or [])
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
                assert name not in (
                    "vssadmin.exe", "wbadmin.exe", "bcdedit.exe",
                    "vssadmin", "wbadmin", "bcdedit",
                ), f"the real binary ran: {cmdline}"
                if name == "sh" and "echo vssadmin delete shadows" in cmdline:
                    found = cmdline
            time.sleep(0.05)

        assert found is not None, "no lingering echo shell found"
        assert "echo" in found
        for command in COMMANDS:
            assert command in found
    finally:
        thread.join(timeout=20)

    assert not errors, errors
    assert not thread.is_alive()


def test_recovery_killer_pairs_s5_with_encryption(demo_root):
    """S5 alone is only SUSPICIOUS: the burst makes it INCIDENT-worthy."""
    errors: list[str] = []

    def run():
        try:
            simulator.recovery_killer(
                demo_root,
                commands=COMMANDS,
                encrypt_limit=12,
                linger_seconds=1,
                **_encrypt_kwargs(),
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(timeout=20)
    assert not errors, errors
    locked = list(demo_root.rglob(f"*{LOCKED}"))
    assert len(locked) == 12
    note = (demo_root / "share" / "exports" / NOTE).read_bytes().decode()
    for command in COMMANDS:
        assert command in note


# --- the CLI ---------------------------------------------------------------------


def _cli_common_args():
    return [
        "--key", KEY,
        "--locked-extension", LOCKED,
        "--ransom-note-name", NOTE,
    ]


def _cli_simulator_args():
    return [*_cli_common_args(), "--delay", "0"]


def test_cli_fast_variant_end_to_end(demo_root):
    result = subprocess.run(
        [sys.executable, "-m", "nightkeep.simulator",
         "--variant", "fast", "--root", str(demo_root), *_cli_simulator_args()],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "encrypted 19 files" in result.stdout
    assert (demo_root / "reports" / f"day_end.csv{LOCKED}").exists()


def test_cli_decrypt_end_to_end(demo_root):
    originals = {
        p.relative_to(demo_root).as_posix(): p.read_bytes()
        for p in demo_root.rglob("*")
        if p.is_file()
    }
    subprocess.run(
        [sys.executable, "-m", "nightkeep.simulator",
         "--variant", "fast", "--root", str(demo_root), *_cli_simulator_args()],
        capture_output=True, text=True, cwd=REPO_ROOT, timeout=120,
        check=True,
    )
    result = subprocess.run(
        [sys.executable, "-m", "nightkeep.simulator.decrypt",
         "--root", str(demo_root), *_cli_common_args()],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "restored 19 files" in result.stdout
    for relative, data in originals.items():
        assert (demo_root / relative).read_bytes() == data, relative


def test_cli_refuses_outside_demo(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "nightkeep.simulator",
         "--variant", "fast", "--root", str(tmp_path), *_cli_common_args()],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=120,
    )
    assert result.returncode == 2
    assert "refused" in result.stderr
