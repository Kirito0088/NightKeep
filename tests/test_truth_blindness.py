"""Nothing under watcher/, habit/, judge/ or vault/ may read logs/_truth/.

CLAUDE.md makes this a hard rail. It used to be a substring scan over module
source, which passed while those packages were empty docstrings and started
failing the moment the Watcher was written, because the Watcher has to name
the folder in order to refuse to touch it. A scan cannot tell "reads it"
from "refuses to read it".

So the rail is two tests now, and together they are strictly stronger than
the scan was:

1. `test_no_truth_blind_module_reads_the_truth_folder_at_runtime` patches
   every way Python opens a file, runs a real Watcher and a real Judge over
   a district that has ground-truth logs in it, and fails if anything so
   much as opens one. This is the rail that actually matters: it proves
   behaviour rather than inspecting prose.

2. `test_no_truth_blind_module_names_the_truth_folder_on_a_reading_line`
   keeps a text check, narrowed to lines that also perform a read. A
   constant or a docstring no longer trips it; `open(root / "_truth" / x)`
   still does.

The ground truth exists to prove, after the fact, that learning was correct.
The moment Nightkeep can see it, that proof is worthless.
"""

import builtins
import io
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from nightkeep.habit import Habit
from nightkeep.judge import Judge
from nightkeep.types import CREATED, MODIFIED, RENAMED, Event, JobRun
from nightkeep.vault import Vault
from nightkeep.vault import _manifest
from nightkeep.watcher import Watcher

PACKAGE = Path(__file__).resolve().parent.parent / "nightkeep"
TRUTH_BLIND = ("watcher", "habit", "judge", "vault")
TRUTH_FOLDER = "_truth"


class TruthWasRead(AssertionError):
    """Raised the instant anything opens a file under logs/_truth/."""


@pytest.fixture
def forbid_reading_the_truth(monkeypatch):
    """Make every route to the ground truth explode instead of returning it.

    Patched at every point Python actually uses. `io.open` matters as much
    as `builtins.open`: pathlib looks `io.open` up on the module at call
    time, so patching only builtins leaves Path.read_text wide open. The
    third test in this file exists because that hole was real.
    """
    opened: list[str] = []

    def _names_the_truth(target: object) -> str | None:
        text = os.fspath(target) if isinstance(target, (str, bytes, os.PathLike)) else ""
        if isinstance(text, bytes):
            text = text.decode("utf-8", "ignore")
        parts = text.replace("\\", "/").split("/")
        return text if TRUTH_FOLDER in parts else None

    def guard(target: object, mode: str = "r") -> None:
        """Block reads of the ground truth. Writing one is the jobs' business.

        The rail says Nightkeep may not READ logs/_truth/. A job writing its
        own truth line goes through this same patched `open`, and blocking
        that would stop the fixtures from building a district at all.
        """
        if any(letter in mode for letter in "wxa") and "+" not in mode:
            return
        text = _names_the_truth(target)
        if text is not None:
            opened.append(text)
            raise TruthWasRead(f"a truth-blind module read {text}")

    def guard_flags(target: object, flags: int) -> None:
        if flags & os.O_WRONLY:
            return
        text = _names_the_truth(target)
        if text is not None:
            opened.append(text)
            raise TruthWasRead(f"a truth-blind module read {text}")

    real_open = builtins.open
    real_io_open = io.open
    real_os_open = os.open
    real_scandir = os.scandir
    real_listdir = os.listdir

    def guarded_open(file, mode="r", *args, **kwargs):
        guard(file, mode)
        return real_open(file, mode, *args, **kwargs)

    def guarded_os_open(path, flags, *args, **kwargs):
        guard_flags(path, flags)
        return real_os_open(path, flags, *args, **kwargs)

    def guarded_scandir(path="."):
        guard(path)
        return real_scandir(path)

    def guarded_listdir(path="."):
        guard(path)
        return real_listdir(path)

    def guarded_io_open(file, mode="r", *args, **kwargs):
        guard(file, mode)
        return real_io_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(io, "open", guarded_io_open)
    monkeypatch.setattr(os, "open", guarded_os_open)
    monkeypatch.setattr(os, "scandir", guarded_scandir)
    monkeypatch.setattr(os, "listdir", guarded_listdir)
    return opened


@pytest.fixture
def district(tmp_path):
    """A district folder with real ground-truth logs sitting in it."""
    for folder in ("data", "share/exports", "share/backups", "allocations",
                   "logs/_truth"):
        (tmp_path / folder).mkdir(parents=True, exist_ok=True)

    # What a job really did. Nightkeep must never be able to see this.
    for job in ("nightly_export", "db_backup", "fix_dat"):
        (tmp_path / "logs" / "_truth" / f"{job}.jsonl").write_text(
            '{"job": "%s", "day": 8, "created": ["share/exports/secret.csv"], '
            '"bytes_written": 4242}\n' % job,
            encoding="utf-8",
        )
    return tmp_path


def _a_run(day: int, events: tuple[Event, ...]) -> JobRun:
    at = datetime(2026, 9, 22, 1, 30) + timedelta(days=day)
    return JobRun(
        job="nightly_export",
        identity="python|jobs/nightly_export.py|abc123",
        started_at=at,
        finished_at=at + timedelta(seconds=30),
        events=events,
        sim_started_at=at,
        day_no=day,
    )


# --- the rail that matters: behaviour --------------------------------------


@pytest.mark.slow
def test_no_truth_blind_module_reads_the_truth_folder_at_runtime(
    district, forbid_reading_the_truth
):
    """Run the real thing over a district that has truth logs, and watch.

    Watcher sees the truth files being written. Habit learns a week. Judge
    is handed events that point straight at a truth log. If any of them
    opens one, `guard` raises and this test fails with the path.
    """
    habit = Habit(district / "data" / "habit.db", 3.0, 3, 0.10)
    judge = Judge(
        root=district,
        habit=habit,
        odd_score=0.5,
        rename_burst=10,
        entropy_jump=1.5,
        entropy_floor=7.0,
        recovery_commands=("vssadmin delete shadows",),
        canary_files=("share/exports/epos_day_end_20240101.csv",),
    )
    judge.plant_canaries()

    # A week of learning, then a verdict, with events naming the truth logs
    # among ordinary ones. Judge reads file contents for S3 and S5, so this
    # is the path that would actually open one.
    truth_events = tuple(
        Event(path=f"logs/_truth/{job}.jsonl", kind=MODIFIED,
              at=datetime(2026, 9, 22, 1, 30), size=120)
        for job in ("nightly_export", "db_backup", "fix_dat")
    )

    for day in range(1, 8):
        ordinary = tuple(
            Event(path=f"share/exports/e{day}_{n}.csv", kind=CREATED,
                  at=datetime(2026, 9, 22, 1, 30), size=1000)
            for n in range(20)
        )
        habit.learn(_a_run(day, ordinary + truth_events))

    ordinary = tuple(
        Event(path=f"share/exports/e8_{n}.csv", kind=CREATED,
              at=datetime(2026, 9, 22, 1, 30), size=1000)
        for n in range(20)
    )
    verdict = judge.verdict(_a_run(8, ordinary + truth_events))

    assert verdict is not None

    # The Vault pulls the same district. Its walk must stay inside share/
    # and never open a truth log, even though the folder sits right there.
    (district / "share" / "exports" / "epos_day_end_20260920.csv").write_text(
        "card_no,date\n110300512847,2026-09-20\n", encoding="utf-8"
    )
    vault = Vault(
        district / "vault_store",
        district / "share",
        suspect_entropy=7.0,
        suspect_changed_fraction=0.5,
        suspect_record_drop_fraction=0.02,
        restore_folder_name="restored",
    )
    snapshot = vault.pull()
    assert snapshot.health == "CLEAN"
    pulled = _manifest.read_manifest(
        district / "vault_store", snapshot.snapshot_id
    )["files"]
    # The judge's trap file is in the share too; both must be pulled, and
    # neither may be a truth log.
    assert "exports/epos_day_end_20260920.csv" in pulled
    assert not any("_truth" in path for path in pulled)

    assert forbid_reading_the_truth == [], (
        f"these truth files were opened: {forbid_reading_the_truth}"
    )


@pytest.mark.slow
def test_the_watcher_records_nothing_from_the_truth_folder(
    district, forbid_reading_the_truth
):
    """The Watcher sees the folder change and must drop it on the floor."""
    with Watcher(district, poll_seconds=0.2) as watcher:
        (district / "logs" / "_truth" / "nightly_export.jsonl").write_text(
            '{"job": "nightly_export"}\n', encoding="utf-8"
        )
        (district / "share" / "exports" / "real.csv").write_text("a,b\n")

        import time

        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            seen = watcher.events_since(datetime(1970, 1, 1, tzinfo=timezone.utc))
            if any(event.path.endswith("real.csv") for event in seen):
                break
            time.sleep(0.05)

    recorded = watcher.events_since(datetime(1970, 1, 1, tzinfo=timezone.utc))
    assert any(event.path.endswith("real.csv") for event in recorded)
    assert not any(TRUTH_FOLDER in event.path for event in recorded)
    assert forbid_reading_the_truth == []


def test_the_guard_itself_actually_catches_a_read(district, forbid_reading_the_truth):
    """Without this, the two tests above could pass by patching nothing."""
    with pytest.raises(TruthWasRead):
        (district / "logs" / "_truth" / "nightly_export.jsonl").read_text()


# --- the narrowed text check ------------------------------------------------

# A line that both names the truth folder and reads something. A constant or
# a docstring sentence is allowed; `open(root / "_truth" / name)` is not.
_READING = re.compile(
    r"\b(open|read_text|read_bytes|read|readlines|load|loads|iterdir|glob|"
    r"rglob|scandir|listdir|walk)\s*\("
)


def test_there_are_truth_blind_modules_to_police():
    """Without this, the scan below passes by finding no files at all."""
    sources = [
        source
        for package in TRUTH_BLIND
        for source in (PACKAGE / package).rglob("*.py")
    ]
    assert len(sources) >= 8, f"only found {len(sources)} sources to police"


def test_no_truth_blind_module_names_the_truth_folder_on_a_reading_line():
    offenders: list[str] = []
    for package in TRUTH_BLIND:
        for source in sorted((PACKAGE / package).rglob("*.py")):
            for number, line in enumerate(
                source.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if TRUTH_FOLDER in line and _READING.search(line):
                    offenders.append(
                        f"{source.relative_to(PACKAGE).as_posix()}:{number}: {line.strip()}"
                    )

    assert offenders == [], (
        "these lines name the truth folder on a line that reads something: "
        f"{offenders}"
    )
