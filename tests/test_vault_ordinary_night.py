"""An ordinary night must not make the Vault's copy SUSPECT.

Found while building the live console (ADR-0011): on normal learning days
the allotment job leaves `.tmp` files in share/allocations that the
format-maintenance job renames to `.dat` only on some nights. When the
last CLEAN snapshot happens to hold no `.tmp`, the next ordinary night's
pull is marked SUSPECT for "new file types never seen before: .tmp", the
Vault enters Protect mode and the clean pin stops advancing. Data Safety
then says "Attention needed" on nights where nothing is wrong, which cuts
against P1.

Tracked as issue #20; this strict xfail pins the defect until the
Vault's rule is fixed, and will fail loudly the day it passes.
"""

import pytest

from nightkeep.types import CLEAN
from nightkeep.vault._health import FileEntry, assess


def entry(sha: str) -> FileEntry:
    return FileEntry(sha256=sha, size=100, entropy=4.0, header_ok=True)


@pytest.mark.xfail(strict=True, reason="Vault flags a night job's own .tmp files as a new file type")
def test_a_night_jobs_own_temporary_files_do_not_make_the_copy_suspect():
    baseline = {
        "exports/epos_day_end_2026-09-24.csv": entry("a"),
        "allocations/fps_quota_27030300145.dat": entry("b"),
        "backups/district-backup-2026-09-24.db": entry("c"),
    }
    tonight = {
        **baseline,
        "exports/epos_day_end_2026-09-25.csv": entry("d"),
        "allocations/fps_quota_27030300218.tmp": entry("e"),
    }
    result = assess(
        tonight, baseline, 5000, 5000,
        suspect_entropy=7.0,
        suspect_changed_fraction=0.5,
        suspect_record_drop_fraction=0.02,
    )
    assert result.health == CLEAN, result.reasons
