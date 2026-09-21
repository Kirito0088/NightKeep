"""F7: count_cards() must return the true card count on Windows too.

Regression test for the Windows SQLite bug in nightkeep/vault/_health.py.
The old count_cards() wrote the database bytes into a
NamedTemporaryFile(delete=True) and called sqlite3.connect() while that
handle was still open. Windows refuses the second open of a held file, so
connect() raised, the blanket ``except`` swallowed it, and count_cards()
returned None -- silently dropping the record-count signal from every F7
health check on Windows.

These tests pin the contract with REAL SQLite database bytes (not mocks):
a real cards table must report its true row count, anything unreadable
must stay None, and no temp file may leak. On Windows the first test
fails before the fix (returns None) and passes after it.
"""

import os
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from nightkeep.types import CLEAN
from nightkeep.vault import Vault, _manifest
from nightkeep.vault._health import count_cards

CARD_COUNT = 5_000


def _real_db_bytes(cards: int) -> bytes:
    """Real SQLite database bytes with a cards table of N rows."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        path = tmp.name
    try:
        conn = sqlite3.connect(path)
        try:
            conn.execute("CREATE TABLE cards (id INTEGER PRIMARY KEY, name TEXT)")
            conn.executemany(
                "INSERT INTO cards (name) VALUES (?)",
                [(f"card {n}",) for n in range(cards)],
            )
            conn.commit()
        finally:
            conn.close()
        return Path(path).read_bytes()
    finally:
        os.unlink(path)


# -- the contract --------------------------------------------------------


def test_count_cards_returns_true_row_count_for_real_db():
    data = _real_db_bytes(CARD_COUNT)
    assert data.startswith(b"SQLite format 3\x00")  # genuinely a database
    assert count_cards(data) == CARD_COUNT


def test_count_cards_returns_true_row_count_for_small_db():
    assert count_cards(_real_db_bytes(3)) == 3


def test_count_cards_returns_none_for_non_database_bytes():
    # None still means "unreadable", exactly as before.
    assert count_cards(b"\x00\x01not a sqlite database") is None
    assert count_cards(b"") is None


def test_count_cards_returns_none_for_db_without_cards_table():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        path = tmp.name
    try:
        conn = sqlite3.connect(path)
        try:
            conn.execute("CREATE TABLE other (id INTEGER PRIMARY KEY)")
            conn.commit()
        finally:
            conn.close()
        assert count_cards(Path(path).read_bytes()) is None
    finally:
        os.unlink(path)


def test_count_cards_leaves_no_temp_files_behind():
    before = {p.name for p in Path(tempfile.gettempdir()).glob("*.db")}
    assert count_cards(_real_db_bytes(10)) == 10
    assert count_cards(b"garbage") is None
    after = {p.name for p in Path(tempfile.gettempdir()).glob("*.db")}
    assert after == before


# -- end to end through the Vault -----------------------------------------

DAY = datetime(2026, 9, 20, 1, 0, tzinfo=timezone.utc)


def _share_with_real_db(tmp_path: Path) -> Path:
    share = tmp_path / "district" / "share"
    backups = share / "backups"
    backups.mkdir(parents=True)
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        path = tmp.name
    try:
        conn = sqlite3.connect(path)
        try:
            conn.execute("CREATE TABLE cards (id INTEGER PRIMARY KEY, name TEXT)")
            conn.executemany(
                "INSERT INTO cards (name) VALUES (?)",
                [(f"card {n}",) for n in range(CARD_COUNT)],
            )
            conn.commit()
        finally:
            conn.close()
        (backups / "district-backup-2026-09-20.db").write_bytes(Path(path).read_bytes())
    finally:
        os.unlink(path)
    return share


def test_clean_to_clean_pull_stays_clean_and_restore_reports_5000_of_5000(tmp_path):
    share = _share_with_real_db(tmp_path)
    vault = Vault(
        tmp_path / "vault",
        share,
        suspect_entropy=7.0,
        suspect_changed_fraction=0.5,
        suspect_record_drop_fraction=0.02,
        restore_folder_name="restored",
    )

    first = vault.pull(taken_at=DAY)
    assert first.health == CLEAN
    assert first.is_clean_point
    assert _manifest.read_manifest(tmp_path / "vault", first.snapshot_id)[
        "record_count"
    ] == CARD_COUNT

    # An unchanged second pull must remain CLEAN through the real health
    # check (which relies on count_cards for the record-count signal).
    second = vault.pull(taken_at=DAY + timedelta(days=1))
    assert second.health == CLEAN
    assert second.is_clean_point
    assert _manifest.read_manifest(tmp_path / "vault", second.snapshot_id)[
        "record_count"
    ] == CARD_COUNT

    result = vault.restore(second.snapshot_id)
    assert result.ok is True
    assert result.records_verified == CARD_COUNT
    assert result.records_expected == CARD_COUNT
    assert result.all_records_verified
    assert all(check.passed for check in result.checks)
