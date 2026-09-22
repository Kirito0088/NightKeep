"""Regression test: a .bat job must launch via cmd.exe on Windows.

Two real Windows failures drove the quoting contract here:

1. 2026-09-21 (demo): running from ``C:\\My Projects 2026\\NightKeep``,
   the demo died launching ``archive_old.bat`` with::

       'C:\\My' is not recognized as an internal or external command,
       operable program or batch file.

   Root cause: the launcher passed the batch path to ``cmd.exe /c`` as a
   bare argv, and cmd.exe re-tokenizes everything after /c with its own
   parser, which splits an unquoted path at the first space.

2. 2026-09-23 (CI): running from ``D:\\a\\NightKeep\\NightKeep`` (no
   spaces at all), the fix for (1) failed with::

       '"D:\\...\\archive_old.bat --root ..."' is not recognized as an
       internal or external command, operable program or batch file.

   Root cause: the /c argument was built as a *list* element containing
   literal quotes. subprocess.list2cmdline escapes those quotes as \\",
   which cmd.exe does not understand, so cmd tried to run the whole
   quoted string as a single command.

The corrected contract: ``_bat_command()`` returns a single command-line
*string* (never a list) using the ``cmd.exe /c "..."`` idiom. A string
is handed to CreateProcess verbatim, with no list2cmdline step; cmd.exe
strips the outer quote pair itself, leaving the individually quoted inner
pieces (from list2cmdline) intact so spaced script and district paths
survive. A list form can never express this, because list2cmdline's \\"
escaping is invisible to cmd.exe's tokenizer.

On non-Windows machines the real cmd.exe does not exist, so the tests
there pin the exact command string ``_bat_command()`` must produce, for
both spaced and normal paths. On Windows the tests run the real cmd.exe
end to end: the batch file must really run and really see its arguments.
"""

import os
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from nightkeep.mock_pds import _day

JOB_NAME = "spaced_job"
SIM_START = datetime(2026, 9, 28, 0, 0, 0)
SIM_END = datetime(2026, 9, 28, 23, 59, 59)


def _job_arguments(district_dir: Path) -> list:
    return [
        "--root", str(district_dir),
        "--day", "1",
        "--sim-start", SIM_START.isoformat(),
        "--sim-end", SIM_END.isoformat(),
    ]


def _expected_bat_command(bat_path: Path, district_dir: Path) -> str:
    """The exact command string the launcher must build for a .bat job."""
    inner = subprocess.list2cmdline([str(bat_path), *_job_arguments(district_dir)])
    return f'cmd.exe /c "{inner}"'


@pytest.fixture()
def spaced_jobs_dir(tmp_path, monkeypatch):
    """A jobs directory whose own path contains spaces, like the real repo."""
    jobs_dir = tmp_path / "My Projects 2026" / "jobs"
    jobs_dir.mkdir(parents=True)
    (jobs_dir / f"{JOB_NAME}.bat").write_text("@echo off\r\n", encoding="utf-8")
    monkeypatch.setattr(_day, "_JOBS_DIR", jobs_dir)
    return jobs_dir


@pytest.fixture()
def plain_jobs_dir(tmp_path, monkeypatch):
    """A jobs directory with no spaces, like the CI runner path."""
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir(parents=True)
    (jobs_dir / f"{JOB_NAME}.bat").write_text("@echo off\r\n", encoding="utf-8")
    monkeypatch.setattr(_day, "_JOBS_DIR", jobs_dir)
    return jobs_dir


@pytest.mark.skipif(os.name == "nt", reason="pins the cmd.exe quoting contract; Windows runs the real cmd.exe")
def test_bat_command_quotes_script_and_district_paths_with_spaces(
    tmp_path, spaced_jobs_dir
):
    # The CI regression (2026-09-23): the /c payload must be one string in
    # the cmd.exe /c "..." idiom, never a list element with quotes that
    # list2cmdline would escape into \\" behind cmd.exe's back.
    bat_path = spaced_jobs_dir / f"{JOB_NAME}.bat"
    district_dir = tmp_path / "My Projects 2026" / "district"
    command = _day._bat_command(bat_path, _job_arguments(district_dir))
    assert isinstance(command, str)
    assert command == _expected_bat_command(bat_path, district_dir)
    # The executable path itself is independently quoted inside.
    assert f'"{bat_path}"' in command


@pytest.mark.skipif(os.name == "nt", reason="pins the cmd.exe quoting contract; Windows runs the real cmd.exe")
def test_bat_command_quotes_normal_paths_without_spaces(tmp_path, plain_jobs_dir):
    # The exact CI failure: D:\\a\\NightKeep\\NightKeep has no spaces, yet
    # the old list-form /c argument still failed. The string form must be
    # correct for the no-space case too.
    bat_path = plain_jobs_dir / f"{JOB_NAME}.bat"
    district_dir = tmp_path / "district"
    command = _day._bat_command(bat_path, _job_arguments(district_dir))
    assert isinstance(command, str)
    assert command == _expected_bat_command(bat_path, district_dir)
    assert command.startswith('cmd.exe /c "')
    assert command.endswith('"')
    assert command.count('"') >= 2


@pytest.mark.skipif(os.name != "nt", reason="needs the real cmd.exe")
def test_bat_job_launches_when_script_path_contains_spaces_windows(
    tmp_path, monkeypatch, spaced_jobs_dir
):
    # End to end on Windows: the batch file really runs and really sees
    # the spaced district path in its arguments.
    bat_path = spaced_jobs_dir / f"{JOB_NAME}.bat"
    probe = tmp_path / "probe.txt"
    bat_path.write_text(f'@echo off\r\necho %* > "{probe}"\r\n', encoding="utf-8")

    district_dir = tmp_path / "My Projects 2026" / "district"
    district_dir.mkdir(parents=True)
    _day.launch(JOB_NAME, district_dir, 1, SIM_START, SIM_END)  # must not raise

    assert str(district_dir) in probe.read_text(encoding="utf-8")


@pytest.mark.skipif(os.name != "nt", reason="needs the real cmd.exe")
def test_bat_job_launches_when_paths_have_no_spaces_windows(
    tmp_path, monkeypatch, plain_jobs_dir
):
    # End to end on Windows for the CI layout: no spaces anywhere, the
    # batch file must still really run and see every argument.
    bat_path = plain_jobs_dir / f"{JOB_NAME}.bat"
    probe = tmp_path / "probe.txt"
    bat_path.write_text(f'@echo off\r\necho %* > "{probe}"\r\n', encoding="utf-8")

    district_dir = tmp_path / "district"
    district_dir.mkdir(parents=True)
    _day.launch(JOB_NAME, district_dir, 1, SIM_START, SIM_END)  # must not raise

    seen = probe.read_text(encoding="utf-8")
    assert str(district_dir) in seen
    assert "--day" in seen
