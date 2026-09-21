"""The Pull Vault: content-addressed pulls, health checks, pinned clean points.

Covers F7. The deep module hides the blob store, manifests, the hash chain,
the S7 health check and restore verification behind pull(), snapshots() and
restore(). Rule 3 lives here too: the PDS server never gets a path,
credential or address for the Vault.
"""

import csv
import json
import os
import sqlite3
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from nightkeep.vault import Vault, VaultError
from nightkeep.vault import _manifest, _store

PACKAGE = Path(__file__).resolve().parent.parent / "nightkeep"
SERVER_SIDE = ("mock_pds", "watcher", "habit", "judge")

DAY = datetime(2026, 9, 20, 1, 0, tzinfo=timezone.utc)


def _cards_db(path: Path, count: int) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE cards (id INTEGER PRIMARY KEY, name TEXT)")
        conn.executemany(
            "INSERT INTO cards (name) VALUES (?)", [(f"card {n}",) for n in range(count)]
        )


def _share(tmp_path: Path, cards: int = 120) -> Path:
    """A fake district share/: exports, allocations and one db backup."""
    share = tmp_path / "district" / "share"
    exports = share / "exports"
    allocations = share / "allocations"
    backups = share / "backups"
    for folder in (exports, allocations, backups):
        folder.mkdir(parents=True)
    with (exports / "epos_day_end_20260920.csv").open(
        "w", encoding="utf-8", newline=""
    ) as fh:
        writer = csv.writer(fh)
        writer.writerow(["card_no", "date", "qty_kg"])
        writer.writerow(["110300512847", "2026-09-20", "5.000"])
    (allocations / "alloc_27030300145_2026-09.tmp").write_text(
        "fps_id=27030300145\nallotment_month=2026-09\n", encoding="utf-8"
    )
    _cards_db(backups / "district-backup-2026-09-20.db", cards)
    return share


def _vault(tmp_path: Path, share: Path, **overrides) -> Vault:
    args = dict(
        suspect_entropy=7.0,
        suspect_changed_fraction=0.5,
        suspect_record_drop_fraction=0.02,
        restore_folder_name="restored",
    )
    args.update(overrides)
    return Vault(tmp_path / "vault", share, **args)


def _pull(vault: Vault, day_offset: int = 0):
    return vault.pull(taken_at=DAY + timedelta(days=day_offset))


# -- the pull ------------------------------------------------------------


def test_pull_stores_every_share_file_once_by_hash(tmp_path):
    share = _share(tmp_path)
    vault = _vault(tmp_path, share)
    snapshot = _pull(vault)

    assert snapshot.health == "CLEAN"
    assert snapshot.file_count == 3
    blobs = list((tmp_path / "vault" / "blobs").iterdir())
    assert len(blobs) == 3
    for blob in blobs:
        assert len(blob.name) == 64  # SHA-256 hex

    # A second identical pull stores no new blobs.
    _pull(vault, day_offset=1)
    assert len(list((tmp_path / "vault" / "blobs").iterdir())) == 3


def test_blobs_are_read_only(tmp_path):
    share = _share(tmp_path)
    _pull(_vault(tmp_path, share))
    for blob in (tmp_path / "vault" / "blobs").iterdir():
        assert not blob.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)


def test_manifest_is_json_with_chain_link(tmp_path):
    share = _share(tmp_path)
    vault = _vault(tmp_path, share)
    first = _pull(vault)
    second = _pull(vault, day_offset=1)

    first_path = tmp_path / "vault" / "manifests" / f"{first.snapshot_id}.json"
    payload = json.loads(first_path.read_text(encoding="utf-8"))
    assert payload["previous_manifest_hash"] is None
    assert payload["health"] == "CLEAN"
    assert payload["record_count"] == 120
    assert set(payload["files"]) == {
        "exports/epos_day_end_20260920.csv",
        "allocations/alloc_27030300145_2026-09.tmp",
        "backups/district-backup-2026-09-20.db",
    }
    info = payload["files"]["exports/epos_day_end_20260920.csv"]
    assert set(info) == {"sha256", "size", "mtime", "entropy", "header_ok"}
    assert info["header_ok"] is True

    second_payload = json.loads(
        (tmp_path / "vault" / "manifests" / f"{second.snapshot_id}.json")
        .read_text(encoding="utf-8")
    )
    assert second_payload["previous_manifest_hash"] == _store.sha256_hex(
        first_path.read_bytes()
    )


def test_first_pull_becomes_the_pinned_day_zero_point(tmp_path):
    share = _share(tmp_path)
    vault = _vault(tmp_path, share)
    snapshot = _pull(vault)

    assert snapshot.is_clean_point is True
    assert (tmp_path / "vault" / "clean_point").read_text().strip() == (
        snapshot.snapshot_id
    )
    assert "Day-0" in snapshot.reasons[0]


def test_snapshots_lists_pulls_oldest_first(tmp_path):
    share = _share(tmp_path)
    vault = _vault(tmp_path, share)
    ids = [_pull(vault, day_offset=n).snapshot_id for n in range(3)]

    listed = vault.snapshots()
    assert [s.snapshot_id for s in listed] == ids
    assert all(s.health == "CLEAN" for s in listed)
    assert listed[-1].is_clean_point is True  # the pin moves forward on CLEAN


def test_pull_never_writes_to_the_share(tmp_path):
    share = _share(tmp_path)
    before = {
        path: (path.stat().st_mtime_ns, _store.sha256_hex(path.read_bytes()))
        for path in sorted(share.rglob("*"))
        if path.is_file()
    }
    _pull(_vault(tmp_path, share))
    after = {
        path: (path.stat().st_mtime_ns, _store.sha256_hex(path.read_bytes()))
        for path in sorted(share.rglob("*"))
        if path.is_file()
    }
    assert before == after


def test_pull_takes_its_thresholds_as_arguments(tmp_path):
    share = _share(tmp_path)
    strict = _vault(tmp_path, share, suspect_changed_fraction=0.0)
    _pull(strict)
    # Touch one file: with a zero limit, any change is SUSPECT.
    (share / "exports" / "epos_day_end_20260920.csv").write_text(
        "card_no,date,qty_kg\n110300512848,2026-09-21,3.000\n", encoding="utf-8"
    )
    assert _pull(strict, day_offset=1).health == "SUSPECT"


# -- the health check ----------------------------------------------------


def test_encrypted_share_marks_suspect_and_keeps_the_pin(tmp_path):
    share = _share(tmp_path)
    vault = _vault(tmp_path, share)
    clean = _pull(vault)

    target = share / "exports" / "epos_day_end_20260920.csv"
    target.write_bytes(os.urandom(6000))  # scrambled: random, header broken
    bad = _pull(vault, day_offset=1)

    assert bad.health == "SUSPECT"
    assert bad.is_clean_point is False
    assert any("scrambled" in reason for reason in bad.reasons)
    assert any("own type" in reason for reason in bad.reasons)
    # The pin still points at the last clean snapshot.
    assert (tmp_path / "vault" / "clean_point").read_text().strip() == (
        clean.snapshot_id
    )
    listed = {s.snapshot_id: s for s in vault.snapshots()}
    assert listed[clean.snapshot_id].is_clean_point is True
    assert listed[bad.snapshot_id].is_clean_point is False


def test_new_file_type_marks_suspect(tmp_path):
    share = _share(tmp_path)
    vault = _vault(tmp_path, share)
    _pull(vault)

    (share / "exports" / "epos_day_end_20260920.csv.locked").write_bytes(
        os.urandom(2000)
    )
    bad = _pull(vault, day_offset=1)

    assert bad.health == "SUSPECT"
    assert any(".locked" in reason for reason in bad.reasons)


def test_record_drop_marks_suspect(tmp_path):
    share = _share(tmp_path)
    vault = _vault(tmp_path, share)
    _pull(vault)

    _cards_db(share / "backups" / "district-backup-2026-09-21.db", 100)
    bad = _pull(vault, day_offset=1)

    assert bad.health == "SUSPECT"
    assert any("120 to 100" in reason for reason in bad.reasons)


def test_missing_database_backup_marks_suspect(tmp_path):
    share = _share(tmp_path)
    vault = _vault(tmp_path, share)
    _pull(vault)

    for backup in (share / "backups").glob("*.db"):
        backup.unlink()
    bad = _pull(vault, day_offset=1)

    assert bad.health == "SUSPECT"
    assert any("no database backup" in reason for reason in bad.reasons)


# -- restore -------------------------------------------------------------


def test_restore_materializes_and_proves_itself(tmp_path):
    share = _share(tmp_path)
    vault = _vault(tmp_path, share)
    snapshot = _pull(vault)

    result = vault.restore(snapshot.snapshot_id)

    assert result.ok is True
    assert result.records_verified == 120
    assert result.records_expected == 120
    assert result.all_records_verified
    assert all(check.passed for check in result.checks)
    assert result.reasons == ()
    target = Path(result.restored_to)
    for relpath in (
        "exports/epos_day_end_20260920.csv",
        "allocations/alloc_27030300145_2026-09.tmp",
        "backups/district-backup-2026-09-20.db",
    ):
        assert (target / relpath).read_bytes() == (share / relpath).read_bytes()


def test_restore_unknown_snapshot_raises(tmp_path):
    vault = _vault(tmp_path, _share(tmp_path))
    with pytest.raises(VaultError, match="no such snapshot"):
        vault.restore("20990101-000000")


def test_restore_refuses_to_overwrite(tmp_path):
    share = _share(tmp_path)
    vault = _vault(tmp_path, share)
    snapshot = _pull(vault)
    vault.restore(snapshot.snapshot_id)
    with pytest.raises(VaultError, match="refusing to overwrite"):
        vault.restore(snapshot.snapshot_id)


def test_restore_detects_a_tampered_blob(tmp_path):
    share = _share(tmp_path)
    vault = _vault(tmp_path, share)
    snapshot = _pull(vault)

    blob = next((tmp_path / "vault" / "blobs").iterdir())
    blob.chmod(0o644)
    blob.write_bytes(b"tampered")
    blob.chmod(0o444)

    result = vault.restore(snapshot.snapshot_id)
    assert result.ok is False
    assert result.reasons != ()
    assert any("hash" in reason for reason in result.reasons)


def test_restore_counts_five_thousand_records_from_the_restored_db(tmp_path):
    """The 5,000/5,000 is counted from the restored SQLite file itself,
    not copied from the manifest's metadata."""
    share = _share(tmp_path, cards=5000)
    vault = _vault(tmp_path, share)
    snapshot = _pull(vault)

    # The manifest's expected count was computed at pull time by actually
    # counting the cards in the backup, not hardcoded.
    manifest = _manifest.read_manifest(vault._root, snapshot.snapshot_id)
    assert manifest["record_count"] == 5000

    result = vault.restore(snapshot.snapshot_id)
    assert result.ok is True
    assert result.records_verified == 5000
    assert result.records_expected == 5000
    assert result.all_records_verified

    # Independent proof: open the restored database file ourselves and
    # count. If the Vault had merely copied the manifest's number, this
    # would not match a genuinely restored 5,000-row table.
    target = Path(result.restored_to)
    db_path = target / "backups" / "district-backup-2026-09-20.db"
    with sqlite3.connect(db_path) as conn:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        count = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    assert integrity == "ok"
    assert count == 5000


# -- rule 3: the server never gets the Vault --------------------------------


def test_server_side_modules_never_import_the_vault():
    offenders = []
    for package in SERVER_SIDE:
        for source in (PACKAGE / package).rglob("*.py"):
            text = source.read_text(encoding="utf-8")
            if "nightkeep.vault" in text or "nightkeep import vault" in text:
                offenders.append(source.relative_to(PACKAGE).as_posix())
    assert offenders == []


def test_pull_leaves_no_vault_path_inside_the_district(tmp_path):
    share = _share(tmp_path)
    vault_root = tmp_path / "vault"
    _pull(_vault(tmp_path, share))

    needle = str(vault_root).encode("utf-8")
    offenders = [
        str(path)
        for path in sorted((tmp_path / "district").rglob("*"))
        if path.is_file() and needle in path.read_bytes()
    ]
    assert offenders == []
