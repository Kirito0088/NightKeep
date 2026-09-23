"""The demo runner's job identity: executable + script path + SHA-256.

The identity must name the interpreter the scheduler really launches the
job through, for every script language, so learned habit cards stay
keyed to what actually ran.
"""

import hashlib
import sys
from pathlib import Path

import pytest

from nightkeep import demo_run
from nightkeep.mock_pds import _day

EXPECTED_EXE = {
    "nightly_export": Path(sys.executable).name,
    "db_backup": Path(sys.executable).name,
    "allocation_gen": Path(sys.executable).name,
    "operator_activity": Path(sys.executable).name,
    "archive_old": "cmd.exe",
    "fix_dat": "cscript.exe",
}


@pytest.mark.parametrize("job", sorted(EXPECTED_EXE))
def test_job_identity_names_the_real_interpreter_path_and_hash(job):
    path = _day._job_path(job)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()

    assert demo_run._job_identity(job) == f"{EXPECTED_EXE[job]}|jobs/{path.name}|{digest}"
