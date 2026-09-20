"""The separate machine that holds the backups. It always opens the connection.

Public interface:
    Vault(root, share, suspect_entropy, suspect_changed_fraction,
          suspect_record_drop_fraction, restore_folder_name)
    pull() -> Snapshot
    snapshots() -> list[Snapshot]
    restore(snapshot_id) -> RestoreResult

Hides the content-addressed blob store, JSON manifests, the hash chain, the
S7 health check, pinned clean points and restore verification.

The PDS server never gets a path, credential or address for the Vault. The
share path and every threshold arrive here as arguments from the Vault's own
startup; nothing on the server is ever told them, and the Vault only ever
reads the share, never writes to it.
"""

from datetime import datetime, timezone
from pathlib import Path

from nightkeep.types import (
    CLEAN,
    Check,
    RestoreResult,
    Snapshot,
)
from nightkeep.vault import _health, _manifest, _store
from nightkeep.vault._health import FileEntry
from nightkeep.vault._store import sha256_hex

CLEAN_POINT_FILE = "clean_point"


class VaultError(Exception):
    """The Vault could not do what was asked, in plain words."""


class Vault:
    """Pulls the PDS share into a content-addressed store and judges it."""

    def __init__(
        self,
        root: Path,
        share: Path,
        *,
        suspect_entropy: float,
        suspect_changed_fraction: float,
        suspect_record_drop_fraction: float,
        restore_folder_name: str,
    ) -> None:
        self._root = Path(root)
        self._share = Path(share)
        self._suspect_entropy = suspect_entropy
        self._suspect_changed_fraction = suspect_changed_fraction
        self._suspect_record_drop_fraction = suspect_record_drop_fraction
        self._restore_folder_name = restore_folder_name

    # -- pulls ----------------------------------------------------------

    def pull(self, *, taken_at: datetime | None = None) -> Snapshot:
        """Copy the share into the store and health-check it.

        Returns the new Snapshot, CLEAN or SUSPECT. A CLEAN pull becomes the
        pinned clean point; a SUSPECT pull is kept but never promoted.
        """
        if not self._share.is_dir():
            raise VaultError(f"the share is not there to pull: {self._share}")
        moment = taken_at or datetime.now(timezone.utc)
        entries = self._pull_files()
        file_entries = {path: entry for path, (entry, _) in entries.items()}
        baseline, baseline_record_count = self._clean_baseline()
        current_record_count = self._record_count(entries)
        assessment = _health.assess(
            file_entries,
            baseline,
            baseline_record_count,
            current_record_count,
            suspect_entropy=self._suspect_entropy,
            suspect_changed_fraction=self._suspect_changed_fraction,
            suspect_record_drop_fraction=self._suspect_record_drop_fraction,
        )

        snapshot_id = self._fresh_id(moment)
        if assessment.health == CLEAN:
            if baseline is None:
                reasons = (
                    "first pull: this snapshot becomes the Day-0 clean point",
                )
            else:
                reasons = ("matches the last clean snapshot",)
        else:
            reasons = assessment.reasons

        payload = {
            "snapshot_id": snapshot_id,
            "taken_at": moment.isoformat(),
            "health": assessment.health,
            "reasons": list(reasons),
            "previous_manifest_hash": self._latest_manifest_hash(),
            "record_count": assessment.record_count,
            "files": {
                path: {
                    "sha256": entry.sha256,
                    "size": entry.size,
                    "mtime": entry_mtime,
                    "entropy": round(entry.entropy, 3),
                    "header_ok": entry.header_ok,
                }
                for path, (entry, entry_mtime) in entries.items()
            },
        }
        manifest_hash = _manifest.write_manifest(self._root, payload)

        is_clean_point = assessment.health == CLEAN
        if is_clean_point:
            _store.write_locked(
                self._root / CLEAN_POINT_FILE, snapshot_id.encode("utf-8")
            )

        total_bytes = sum(entry.size for entry, _ in entries.values())
        return Snapshot(
            snapshot_id=snapshot_id,
            taken_at=moment,
            health=assessment.health,
            file_count=len(entries),
            total_bytes=total_bytes,
            manifest_hash=manifest_hash,
            previous_manifest_hash=payload["previous_manifest_hash"],
            is_clean_point=is_clean_point,
            reasons=reasons,
        )

    def _pull_files(self) -> dict[str, tuple[FileEntry, float]]:
        """Read every file under share/, storing new blobs. Never writes there."""
        entries: dict[str, tuple[FileEntry, float]] = {}
        for path in sorted(self._share.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            relpath = path.relative_to(self._share).as_posix()
            data = path.read_bytes()
            digest = _store.store_blob(self._root, data)
            entries[relpath] = (
                FileEntry(
                    sha256=digest,
                    size=len(data),
                    # Rounded here so the in-memory entry and the manifest
                    # agree exactly when this pull becomes a baseline.
                    entropy=round(_health.shannon_entropy(data), 3),
                    header_ok=_health.header_ok(relpath, data),
                ),
                path.stat().st_mtime,
            )
        return entries

    def _clean_baseline(self) -> tuple[dict[str, FileEntry] | None, int | None]:
        """The pinned clean point's files and record count, if one exists."""
        pin = self._root / CLEAN_POINT_FILE
        if not pin.exists():
            return None, None
        manifest = _manifest.read_manifest(self._root, pin.read_text().strip())
        baseline = {
            path: FileEntry(
                sha256=info["sha256"],
                size=info["size"],
                entropy=info["entropy"],
                header_ok=info["header_ok"],
            )
            for path, info in manifest["files"].items()
        }
        return baseline, manifest.get("record_count")

    def _record_count(self, entries: dict[str, tuple[FileEntry, float]]) -> int | None:
        backup = _health.newest_backup(
            {path: entry for path, (entry, _) in entries.items()}
        )
        if backup is None:
            return None
        digest = entries[backup][0].sha256
        return _health.count_cards(_store.read_blob(self._root, digest))

    def _fresh_id(self, moment: datetime) -> str:
        base = moment.strftime("%Y%m%d-%H%M%S")
        candidate, suffix = base, 2
        while _manifest.manifest_path(self._root, candidate).exists():
            candidate, suffix = f"{base}-{suffix}", suffix + 1
        return candidate

    def _latest_manifest_hash(self) -> str | None:
        ids = _manifest.manifest_ids(self._root)
        if not ids:
            return None
        path = _manifest.manifest_path(self._root, ids[-1])
        return sha256_hex(path.read_bytes())

    # -- history --------------------------------------------------------

    def snapshots(self) -> list[Snapshot]:
        """Every pull on disk, oldest first, with the clean point marked."""
        pin_file = self._root / CLEAN_POINT_FILE
        pinned = pin_file.read_text().strip() if pin_file.exists() else None
        found = []
        for snapshot_id in _manifest.manifest_ids(self._root):
            path = _manifest.manifest_path(self._root, snapshot_id)
            manifest = _manifest.read_manifest(self._root, snapshot_id)
            total_bytes = sum(info["size"] for info in manifest["files"].values())
            found.append(
                Snapshot(
                    snapshot_id=snapshot_id,
                    taken_at=datetime.fromisoformat(manifest["taken_at"]),
                    health=manifest["health"],
                    file_count=len(manifest["files"]),
                    total_bytes=total_bytes,
                    manifest_hash=sha256_hex(path.read_bytes()),
                    previous_manifest_hash=manifest["previous_manifest_hash"],
                    is_clean_point=snapshot_id == pinned,
                    reasons=tuple(manifest["reasons"]),
                )
            )
        return found

    # -- restore ----------------------------------------------------------

    def restore(self, snapshot_id: str) -> RestoreResult:
        """Materialize one snapshot into a new folder and prove it.

        The restore lands beside the damaged data, never on top of it.
        Every claim in the result comes from a check that actually ran.
        """
        try:
            manifest = _manifest.read_manifest(self._root, snapshot_id)
        except FileNotFoundError:
            raise VaultError(f"no such snapshot: {snapshot_id}") from None
        target = self._root / self._restore_folder_name / snapshot_id
        if target.exists():
            raise VaultError(f"already restored to {target}; refusing to overwrite")

        hashes_ok = True
        for relpath, info in manifest["files"].items():
            data = _store.read_blob(self._root, info["sha256"])
            out = target / relpath
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data)
            hashes_ok &= sha256_hex(out.read_bytes()) == info["sha256"]

        checks: list[Check] = [
            Check(
                f"every restored file's hash matches the manifest "
                f"({len(manifest['files'])} files)",
                hashes_ok,
            ),
            Check(
                "every restored file still opens as its own type",
                all(info["header_ok"] for info in manifest["files"].values()),
            ),
            Check(
                "every restored export parses as a CSV",
                self._csvs_parse(target, manifest),
            ),
        ]
        records_verified, records_expected = self._verify_database(
            target, manifest, checks
        )
        reasons = tuple(
            check.statement for check in checks if not check.passed
        )
        return RestoreResult(
            ok=all(check.passed for check in checks),
            snapshot_id=snapshot_id,
            restored_to=str(target),
            records_verified=records_verified,
            records_expected=records_expected,
            checks=tuple(checks),
            reasons=reasons,
        )

    def _csvs_parse(self, target: Path, manifest: dict) -> bool:
        import csv

        for relpath in manifest["files"]:
            if not relpath.endswith(".csv"):
                continue
            try:
                with (target / relpath).open("r", encoding="utf-8", newline="") as fh:
                    for _ in csv.reader(fh):
                        pass
            except Exception:
                return False
        return True

    def _verify_database(
        self, target: Path, manifest: dict, checks: list[Check]
    ) -> tuple[int, int]:
        import sqlite3

        expected = manifest.get("record_count") or 0
        backups = sorted(
            path for path in manifest["files"] if path.startswith("backups/")
        )
        if not backups:
            checks.append(Check("the snapshot holds a database backup", False))
            return 0, expected
        db_path = target / backups[-1]
        try:
            with sqlite3.connect(db_path) as conn:
                integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
                count = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
        except Exception:
            checks.append(Check("the database backup opens cleanly", False))
            return 0, expected
        checks.append(Check("the database backup passes its integrity check",
                            integrity == "ok"))
        checks.append(
            Check(
                f"all {expected:,} ration cards are present and readable",
                count == expected,
            )
        )
        return count, expected
