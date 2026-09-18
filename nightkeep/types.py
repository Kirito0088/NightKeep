"""Plain dataclasses shared across the PDS server / Vault boundary.

The only thing allowed to cross that line. Nothing here carries state, holds a
connection or reaches for config. Each type lands with the ticket that needs
it: HabitScore with habit, Verdict with judge, RestoreResult with vault.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class JobRun:
    """The operational facts of one completed run of one job.

    Captured by mock_pds / watcher, scored by habit, evaluated by judge.
    Contains no scoring logic or detection conclusions.
    """

    job_name: str
    command: tuple[str, ...]
    script_path: str
    script_sha256: str
    start_time: datetime
    end_time: datetime
    exit_code: int
    files_created: tuple[str, ...]
    files_modified: tuple[str, ...]
    files_deleted: tuple[str, ...]
    folders_touched: tuple[str, ...]
    bytes_written: int
    extensions: tuple[str, ...]
    details: dict[str, Any]
