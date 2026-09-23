"""An ordinary night must not make the Vault's copy SUSPECT (issue #20).

The Vault used to count every new file as a change and every new file type
as suspicious. A night job's fresh `.tmp` files, or the allotment job's
month-start run of 50 new files, were enough to mark an ordinary pull
SUSPECT. Protect mode then held the pin on day 1, and against that stale
baseline every later night crossed the 50% limit too.

What damages records is changing, removing or renaming files that were
already there. So the health check measures that: the share of the clean
copy's files that were changed or removed, and files from the clean copy
renamed to a type the clean copy never had (foo.csv -> foo.csv.locked).
Adding new files is what an office does every night.

The attack side stays covered: rewrites, deletions, renames, scrambled
content and broken headers are all still caught.
"""

import os

import pytest

from nightkeep.types import CLEAN, SUSPECT
from nightkeep.vault._health import FileEntry, assess


def entry(sha: str, *, entropy: float = 4.0, header_ok: bool = True) -> FileEntry:
    return FileEntry(sha256=sha, size=100, entropy=entropy, header_ok=header_ok)


def judge(tonight, baseline):
    return assess(
        tonight, baseline, 5000, 5000,
        suspect_entropy=7.0,
        suspect_changed_fraction=0.5,
        suspect_record_drop_fraction=0.02,
    )


def clean_copy(exports: int = 10) -> dict[str, FileEntry]:
    files = {
        f"exports/epos_day_end_2026-09-{day:02d}.csv": entry(f"e{day}")
        for day in range(1, exports + 1)
    }
    files["allocations/fps_quota_27030300145.dat"] = entry("q1")
    files["backups/district-backup-2026-09-24.db"] = entry("b1")
    return files


# --- ordinary nights ------------------------------------------------------------


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
    result = judge(tonight, baseline)
    assert result.health == CLEAN, result.reasons


def test_the_month_start_allotment_run_is_an_ordinary_night():
    """50 new quota files on the 1st of the month, on top of a small share."""
    baseline = clean_copy(exports=3)
    tonight = {
        **baseline,
        **{f"allocations/fps_quota_2703030{shop:04d}.tmp": entry(f"n{shop}")
           for shop in range(50)},
    }
    result = judge(tonight, baseline)
    assert result.health == CLEAN, result.reasons


def test_the_format_script_renaming_tmp_to_dat_is_not_ransomware():
    """fix_dat renames .tmp to .dat some nights, even the first time a .dat
    appears: a changed extension, not an appended one."""
    baseline = {
        "exports/epos_day_end_2026-09-24.csv": entry("a"),
        "allocations/fps_quota_27030300145.tmp": entry("q"),
        "backups/district-backup-2026-09-24.db": entry("c"),
    }
    tonight = {
        "exports/epos_day_end_2026-09-24.csv": entry("a"),
        "allocations/fps_quota_27030300145.dat": entry("q"),
        "backups/district-backup-2026-09-24.db": entry("c"),
    }
    result = judge(tonight, baseline)
    assert result.health == CLEAN, result.reasons


def test_old_exports_zipped_away_on_a_few_nights_stay_clean():
    baseline = clean_copy(exports=10)
    tonight = dict(baseline)
    for day in (1, 2, 3):
        del tonight[f"exports/epos_day_end_2026-09-{day:02d}.csv"]
    result = judge(tonight, baseline)
    assert result.health == CLEAN, result.reasons


# --- attacks are still caught ------------------------------------------------------


def test_files_renamed_to_a_locked_extension_are_caught_even_a_few():
    """A contained attack renames only a handful before it is paused."""
    baseline = clean_copy(exports=10)
    tonight = dict(baseline)
    for day in (1, 2, 3):
        path = f"exports/epos_day_end_2026-09-{day:02d}.csv"
        tonight[path + ".locked"] = tonight.pop(path)
    result = judge(tonight, baseline)
    assert result.health == SUSPECT
    assert any(".locked" in reason and "renamed" in reason for reason in result.reasons)


def test_most_of_the_clean_copy_rewritten_is_caught():
    baseline = clean_copy(exports=10)
    tonight = {path: entry(sha + "-rewritten") for path, sha in
               ((p, e.sha256) for p, e in baseline.items())}
    result = judge(tonight, baseline)
    assert result.health == SUSPECT
    assert any("changed or removed" in reason for reason in result.reasons)


def test_most_of_the_clean_copy_deleted_is_caught():
    baseline = clean_copy(exports=10)
    tonight = {"backups/district-backup-2026-09-24.db": baseline["backups/district-backup-2026-09-24.db"]}
    result = judge(tonight, baseline)
    assert result.health == SUSPECT
    assert any("changed or removed" in reason for reason in result.reasons)


def test_one_scrambled_file_is_still_caught():
    baseline = clean_copy(exports=10)
    tonight = dict(baseline)
    tonight["exports/epos_day_end_2026-09-05.csv"] = entry("x", entropy=7.9, header_ok=False)
    result = judge(tonight, baseline)
    assert result.health == SUSPECT
    assert any("scrambled" in reason for reason in result.reasons)


def test_a_new_file_that_is_scrambled_is_still_caught():
    """New files are not damage by themselves, but a new file full of random
    bytes with a broken header is still looked at."""
    baseline = clean_copy(exports=10)
    tonight = {**baseline, "exports/epos_day_end_2026-09-30.csv": entry(
        "x", entropy=7.9, header_ok=False)}
    assert judge(tonight, baseline).health == SUSPECT
