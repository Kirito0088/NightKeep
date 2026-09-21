"""Regression test: a .bat job must launch when its script path contains spaces.

Real Windows failure (demo, 2026-09-21): running from
``C:\\My Projects 2026\\NightKeep`` with
``python -m nightkeep --demo-run --variant recovery-killer``, the demo died
launching ``nightkeep\\mock_pds\\jobs\\archive_old.bat`` with::

    'C:\\My' is not recognized as an internal or external command,
    operable program or batch file.

Root cause: the launcher passed the batch path to ``cmd.exe /c`` as a bare
argv, and cmd.exe re-tokenizes everything after /c with its own parser,
which splits an unquoted path at the first space. The fix passes the whole
command line as one /c argument, wrapped in one outer pair of quotes (cmd
strips that pair; the individually quoted pieces inside then survive
spaced paths).

On non-Windows machines the real cmd.exe does not exist, so the test there
runs the real ``_day.launch`` against a fake ``cmd.exe`` shim that records
the argv it received: the assertion pins the exact quoting contract the
fix establishes. On Windows the test runs the real cmd.exe end to end.
"""

import json
import os
import stat
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from nightkeep.mock_pds import _day

JOB_NAME = "spaced_job"
SIM_START = datetime(2026, 9, 28, 0, 0, 0)
SIM_END = datetime(2026, 9, 28, 23, 59, 59)


@pytest.fixture()
def spaced_jobs_dir(tmp_path, monkeypatch):
    """A jobs directory whose own path contains spaces, like the real repo."""
    jobs_dir = tmp_path / "My Projects 2026" / "jobs"
    jobs_dir.mkdir(parents=True)
    (jobs_dir / f"{JOB_NAME}.bat").write_text("@echo off\r\n", encoding="utf-8")
    monkeypatch.setattr(_day, "_JOBS_DIR", jobs_dir)
    return jobs_dir


def _expected_cmd_argv(bat_path: Path, district_dir: Path) -> list:
    """The argv the fixed launcher must hand to the OS for a .bat job."""
    arguments = [
        "--root", str(district_dir),
        "--day", "1",
        "--sim-start", SIM_START.isoformat(),
        "--sim-end", SIM_END.isoformat(),
    ]
    inner = subprocess.list2cmdline([str(bat_path), *arguments])
    # The shim records sys.argv[1:], so the expectation starts after the
    # program name.
    return ["/c", f'"{inner}"']


@pytest.mark.skipif(os.name == "nt", reason="uses a cmd.exe shim; Windows runs the real cmd.exe")
def test_bat_job_launches_when_script_path_contains_spaces(
    tmp_path, monkeypatch, spaced_jobs_dir
):
    # A fake cmd.exe that records the exact argv the launcher produced.
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    capture = tmp_path / "cmd_argv.json"
    shim = bin_dir / "cmd.exe"
    shim.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        f"open({str(capture)!r}, 'w').write(json.dumps(sys.argv[1:]))\n",
        encoding="utf-8",
    )
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])

    district_dir = tmp_path / "My Projects 2026" / "district"
    district_dir.mkdir(parents=True)
    _day.launch(JOB_NAME, district_dir, 1, SIM_START, SIM_END)  # must not raise

    launched = json.loads(capture.read_text(encoding="utf-8"))
    bat_path = spaced_jobs_dir / f"{JOB_NAME}.bat"
    assert launched == _expected_cmd_argv(bat_path, district_dir)


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
