"""S3, the hardest signal to get right.

The trap this module exists to avoid: the archive job writes a ZIP every few
nights, and a ZIP is noise by design. If high entropy alone fired S3, the
demo would raise an INCIDENT on a legitimate job on stage.
"""

import os

import pytest

from nightkeep.judge.entropy_signal import (
    UNKNOWN,
    entropy,
    header_state,
    inspect,
)

JUMP = 1.5
FLOOR = 7.0

CSV = b"card_no,fps_id,quantity_kg\n110300512847,27030300145,20.000\n" * 40
SQLITE = b"SQLite format 3\x00" + b"\x00" * 200
ZIP = b"PK\x03\x04" + os.urandom(4000)
SCRAMBLED = os.urandom(8000)


def scramble(**overrides):
    arguments = {
        "data": SCRAMBLED,
        "extension": ".csv",
        "was_existing": True,
        "entropy_before": 4.2,
        "entropy_jump": JUMP,
        "entropy_floor": FLOOR,
    }
    arguments.update(overrides)
    return inspect(**arguments)


# --- entropy itself -------------------------------------------------------


def test_an_empty_file_carries_no_information():
    assert entropy(b"") == 0.0


def test_one_byte_repeated_is_the_lowest_entropy_there_is():
    assert entropy(b"\x00" * 1000) == 0.0


def test_random_bytes_sit_near_the_top_of_the_scale():
    assert entropy(os.urandom(20000)) > 7.5


def test_a_csv_sits_far_below_the_noise_floor():
    assert entropy(CSV) < 5.0


def test_entropy_never_leaves_the_zero_to_eight_scale():
    for data in (b"", b"a", CSV, SQLITE, ZIP, SCRAMBLED):
        assert 0.0 <= entropy(data) <= 8.0


# --- headers ---------------------------------------------------------------


def test_a_healthy_csv_reads_as_a_csv():
    assert header_state(CSV, ".csv") == "ok"


def test_a_scrambled_csv_no_longer_reads_as_one():
    assert header_state(SCRAMBLED, ".csv") == "broken"


def test_a_database_is_known_by_its_signature():
    assert header_state(SQLITE, ".db") == "ok"
    assert header_state(SCRAMBLED, ".db") == "broken"


def test_a_zip_is_known_by_its_signature_even_though_it_is_noise():
    assert header_state(ZIP, ".zip") == "ok"


def test_an_extension_with_no_rule_says_unknown_rather_than_guessing():
    assert header_state(SCRAMBLED, ".locked") == UNKNOWN
    assert header_state(CSV, ".whatever") == UNKNOWN


def test_a_jsonl_line_that_no_longer_parses_is_broken():
    assert header_state(b'{"job": "nightly_export"}\n', ".jsonl") == "ok"
    assert header_state(b"not json at all\n", ".jsonl") == "broken"


# --- the three-part rule ---------------------------------------------------


def test_a_scrambled_existing_csv_fires():
    result = scramble()
    assert result.fired
    assert "readable to noise" in result.reason


def test_a_brand_new_file_never_fires_however_random_it_looks():
    """The rule says an EXISTING file. This is the new-ZIP case."""
    result = scramble(was_existing=False)
    assert not result.fired
    assert "new file" in result.reason


def test_a_new_valid_zip_at_full_entropy_stays_quiet():
    """MVP section 10, named explicitly."""
    result = inspect(
        data=ZIP,
        extension=".zip",
        was_existing=False,
        entropy_before=None,
        entropy_jump=JUMP,
        entropy_floor=FLOOR,
    )
    assert not result.fired


def test_an_existing_zip_rewritten_by_the_archive_job_stays_quiet():
    """The archive job overwrites its own ZIP. Header still valid, so no."""
    result = inspect(
        data=ZIP,
        extension=".zip",
        was_existing=True,
        entropy_before=7.9,
        entropy_jump=JUMP,
        entropy_floor=FLOOR,
    )
    assert not result.fired
    assert "still reads as a valid file" in result.reason


def test_a_rewritten_file_that_still_parses_stays_quiet():
    result = scramble(data=CSV, entropy_before=4.0)
    assert not result.fired


def test_a_broken_header_without_scrambled_content_stays_quiet():
    """A truncated or half-written CSV is a bug, not ransomware."""
    result = scramble(data=b"\x00\x01\x02" * 300, entropy_before=4.2)
    assert not result.fired
    assert "not scrambled" in result.reason


def test_a_file_that_was_already_noise_does_not_count_as_a_jump():
    result = scramble(extension=".dat", entropy_before=7.8)
    assert not result.fired
    assert "already noise-like" in result.reason


def test_with_no_baseline_a_broken_scrambled_rewrite_still_fires():
    """First-night attack: no learned baseline, and still caught.

    The missing piece is the weakest of the three. Demanding it would mean
    ransomware on day one walks through.
    """
    result = scramble(entropy_before=None)
    assert result.fired
    assert "unreadable noise" in result.reason


def test_an_unknown_extension_cannot_be_used_as_evidence():
    """A .locked file judged as .locked proves nothing. Judge passes the
    extension the file had BEFORE the rename, which is what makes S3 work."""
    result = scramble(extension=".locked")
    assert not result.fired
    assert "no rule for" in result.reason

    as_its_real_kind = scramble(extension=".csv")
    assert as_its_real_kind.fired


def test_the_result_reports_the_numbers_it_judged_on():
    result = scramble(entropy_before=4.2)
    assert result.entropy_before == 4.2
    assert result.entropy_after > FLOOR
    assert result.header == "broken"
    assert result.jumped


@pytest.mark.parametrize("extension", [".csv", ".db", ".dat", ".json"])
def test_every_kind_the_jobs_actually_write_can_be_caught(extension):
    assert scramble(extension=extension).fired
