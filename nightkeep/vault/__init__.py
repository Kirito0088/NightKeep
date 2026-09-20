"""The separate machine that holds the backups. It always opens the connection.

Public interface:
    Vault(root, share, suspect_entropy, suspect_changed_fraction,
          suspect_record_drop_fraction, restore_folder_name,
          watcher_silence_seconds=30.0, liveness_check_interval_seconds=10.0)
    pull() -> Snapshot
    check_watcher_liveness() -> WatcherLiveness
    start_liveness_monitor(on_change=None, on_state_change=None)
    stop_liveness_monitor()
    last_liveness -> WatcherLiveness | None
    liveness_check_count -> int
    vault_verdict -> NORMAL | SUSPICIOUS | INCIDENT
    protect_mode -> bool
    vault_state -> VaultState
    alerts() -> list[dict]
    snapshots() -> list[Snapshot]
    restore(snapshot_id) -> RestoreResult

The Vault's own verdict (vault_verdict / protect_mode / vault_state) is
the documented response to S6: S6 alone -- or S7 alone -- is SUSPICIOUS
and enters Protect mode (loud alert via on_state_change, alert log
entry, clean pin held); S6 + S7 together is INCIDENT. Snapshot.health
stays strictly about the data; the S6 suspicion never rewrites it.

Hides the content-addressed blob store, JSON manifests, the hash chain, the
S7 health check, the S6 liveness check, pinned clean points and restore
verification.

The PDS server never gets a path, credential or address for the Vault. The
share path and every threshold arrive here as arguments from the Vault's own
startup; nothing on the server is ever told them, and the Vault only ever
reads the share, never writes to it.
"""

from datetime import datetime, timezone
from pathlib import Path
import json
import threading

from nightkeep.types import (
    CLEAN,
    HEARTBEAT_FILENAME,
    INCIDENT,
    NORMAL,
    SUSPECT,
    SUSPICIOUS,
    Check,
    RestoreResult,
    Snapshot,
    VaultState,
    WatcherLiveness,
)
from nightkeep.vault import _health, _manifest, _store
from nightkeep.vault._health import FileEntry
from nightkeep.vault._store import sha256_hex

CLEAN_POINT_FILE = "clean_point"
# The Vault's own alert/evidence log: one JSON line per verdict change.
# This is the durable half of the documented SUSPICIOUS response (loud
# alert + Protect mode + extra evidence capture).
ALERT_LOG = "alerts.jsonl"


class VaultError(Exception):
    """The Vault could not do what was asked, in plain words."""


def combined_verdict(
    liveness: WatcherLiveness | None, health: str
) -> str:
    """The Vault's own call from its two independent witnesses.

    Per the design-doc verdict table: S6 silence together with S7 data
    damage is an INCIDENT; either one alone is SUSPICIOUS (loud alert,
    clean pin held). This lives outside Snapshot.health on purpose: the
    snapshot still describes only the data.

    `liveness` may be None before the monitor's first check -- no check
    means no S6 evidence, so only the snapshot's health can speak.
    """
    silent = liveness is not None and not liveness.alive
    if silent and health == SUSPECT:
        return INCIDENT
    if silent or health == SUSPECT:
        return SUSPICIOUS
    return NORMAL


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
        watcher_silence_seconds: float = 30.0,
        liveness_check_interval_seconds: float = 10.0,
    ) -> None:
        if liveness_check_interval_seconds <= 0:
            raise VaultError(
                "the liveness check interval must be positive, got "
                f"{liveness_check_interval_seconds}"
            )
        self._root = Path(root)
        self._share = Path(share)
        self._suspect_entropy = suspect_entropy
        self._suspect_changed_fraction = suspect_changed_fraction
        self._suspect_record_drop_fraction = suspect_record_drop_fraction
        self._restore_folder_name = restore_folder_name
        self._watcher_silence_seconds = watcher_silence_seconds
        self._liveness_check_interval_seconds = liveness_check_interval_seconds
        # The periodic S6 check the design doc asks the Vault to run during
        # normal operation: every interval the Vault asks (by reading the
        # share); the server only answers (by writing the heartbeat).
        self._liveness_lock = threading.Lock()
        self._last_liveness: WatcherLiveness | None = None
        self._liveness_checks = 0
        self._monitor_thread: threading.Thread | None = None
        self._monitor_stop = threading.Event()
        # The Vault's recorded answer to the design-doc verdict table.
        # Recomputed from the two witnesses after every liveness check and
        # every pull; the monitor's state hook and the alert log fire on
        # every change. This is what makes the documented SUSPICIOUS /
        # INCIDENT response real instead of computed on demand.
        self._verdict = NORMAL
        self._latest_health = self._newest_snapshot_health()
        self._previous_verdict = NORMAL
        self._state_hook = None

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
        snapshot = Snapshot(
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
        # The new snapshot is the S7 witness for the Vault's own verdict.
        # A SUSPECT pull while the watcher is alive is S7 alone:
        # SUSPICIOUS + Protect mode per the design doc. A SUSPECT pull
        # while S6 is already recorded is S6 + S7: INCIDENT. The
        # snapshot's own health is untouched -- it still describes only
        # the data; the composition lives in the vault verdict.
        with self._liveness_lock:
            self._latest_health = assessment.health
        self._refresh_vault_state()
        return snapshot

    def check_watcher_liveness(self) -> WatcherLiveness:
        """S6: has the Watcher checked in through the share recently?

        The Vault asks by reading; the server only answers by writing the
        heartbeat file. No connection is opened, nothing is written to the
        server, and the server never learns the Vault is asking. A missing
        or stale heartbeat is S6, kept as its own state: it says nothing
        about the data, so it never changes a snapshot's health.
        """
        checked_at = datetime.now(timezone.utc)
        heartbeat = self._share / HEARTBEAT_FILENAME
        try:
            payload = json.loads(heartbeat.read_text(encoding="utf-8"))
            written_at = datetime.fromisoformat(payload["written_at"])
        except (OSError, ValueError, KeyError):
            return WatcherLiveness(
                alive=False,
                last_seen=None,
                checked_at=checked_at,
                reason=(
                    "S6: the watcher is silent -- no readable heartbeat in "
                    "the share"
                ),
            )
        if written_at.tzinfo is None:
            written_at = written_at.replace(tzinfo=timezone.utc)
        age = (checked_at - written_at).total_seconds()
        if age > self._watcher_silence_seconds:
            return WatcherLiveness(
                alive=False,
                last_seen=written_at,
                checked_at=checked_at,
                reason=(
                    f"S6: the watcher has been silent for {age:.0f} s, over "
                    f"the {self._watcher_silence_seconds:.0f} s limit "
                    f"(last heartbeat {written_at.isoformat()})"
                ),
            )
        return WatcherLiveness(
            alive=True,
            last_seen=written_at,
            checked_at=checked_at,
            reason=f"the watcher checked in {age:.1f} s ago",
        )

    # -- the periodic liveness check -------------------------------------

    def start_liveness_monitor(
        self, on_change=None, on_state_change=None
    ) -> None:
        """Ask the Watcher for liveness every check interval, in the
        background. This is the design doc's "the Vault checks every 10 s":
        the Vault asks by reading the share, the server only answers by
        writing the heartbeat, and nothing is ever written to the server.

        The latest answer is always available as `last_liveness`;
        `on_change` (if given) is called with each WatcherLiveness whose
        alive/silent state differs from the previous check -- the seam a
        console alert would hook into. `on_state_change` (if given) is
        called with a VaultState every time the Vault's own verdict
        changes -- that is the documented response: the loud alert for
        SUSPICIOUS / INCIDENT, which also flips `protect_mode` on and
        writes the alert log. Idempotent: starting twice keeps the one
        running monitor.
        """
        with self._liveness_lock:
            if (
                self._monitor_thread is not None
                and self._monitor_thread.is_alive()
            ):
                return
            self._monitor_stop.clear()
            self._state_hook = on_state_change
            self._monitor_thread = threading.Thread(
                target=self._liveness_loop,
                args=(on_change,),
                name="vault-liveness-monitor",
                daemon=True,
            )
            self._monitor_thread.start()

    def stop_liveness_monitor(self) -> None:
        """Stop the background check. Safe to call when it never started."""
        with self._liveness_lock:
            thread = self._monitor_thread
        if thread is None:
            return
        self._monitor_stop.set()
        thread.join(timeout=5)
        with self._liveness_lock:
            self._monitor_thread = None

    @property
    def last_liveness(self) -> WatcherLiveness | None:
        """The monitor's latest answer, or None before its first check."""
        with self._liveness_lock:
            return self._last_liveness

    @property
    def liveness_check_count(self) -> int:
        """How many periodic checks the monitor has run so far."""
        with self._liveness_lock:
            return self._liveness_checks

    def _liveness_loop(self, on_change) -> None:
        previous_alive: bool | None = None
        while True:
            liveness = self.check_watcher_liveness()
            with self._liveness_lock:
                self._last_liveness = liveness
                self._liveness_checks += 1
            # The S6 witness just moved: recompute the Vault's own verdict
            # and raise the documented response if it changed.
            self._refresh_vault_state()
            if (
                on_change is not None
                and previous_alive is not None
                and liveness.alive != previous_alive
            ):
                on_change(liveness)
            previous_alive = liveness.alive
            if self._monitor_stop.wait(self._liveness_check_interval_seconds):
                break

    # -- the vault's own verdict (the documented S6 response) --------------

    @property
    def vault_verdict(self) -> str:
        """The Vault's recorded call: NORMAL, SUSPICIOUS or INCIDENT.

        S6 alone (or S7 alone) is SUSPICIOUS; S6 + S7 together is
        INCIDENT. Updated by the monitor after every check and by pull()
        after every snapshot.
        """
        with self._liveness_lock:
            return self._verdict

    @property
    def protect_mode(self) -> bool:
        """True once the Vault has called SUSPICIOUS or INCIDENT.

        The design doc's Protect mode: the clean pin is held (only CLEAN
        snapshots ever advance it), and the alert has been raised. There
        is no automatic backup clean-up in this build to stop, and new
        snapshots keep their data-only health -- the S6 suspicion lives
        in this flag and the verdict, not in Snapshot.health.
        """
        return self.vault_verdict in (SUSPICIOUS, INCIDENT)

    @property
    def vault_state(self) -> VaultState:
        """The full recorded state behind `vault_verdict`."""
        with self._liveness_lock:
            liveness = self._last_liveness
            return VaultState(
                verdict=self._verdict,
                protect_mode=self._verdict in (SUSPICIOUS, INCIDENT),
                watcher_alive=(
                    None if liveness is None else liveness.alive
                ),
                snapshot_health=self._latest_health,
                previous_verdict=self._previous_verdict,
            )

    def alerts(self) -> list[dict]:
        """Every verdict change the Vault has recorded, oldest first.

        The durable half of the documented response: the loud alert and
        the extra evidence capture, one JSON record per change.
        """
        path = self._root / ALERT_LOG
        if not path.exists():
            return []
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def _refresh_vault_state(self) -> None:
        """Recompute the verdict from the two witnesses; on any change,
        record it, append the alert log line, and fire the state hook.

        Called by the monitor after every liveness check and by pull()
        after every snapshot, so whichever witness moves first raises the
        response. The hook and the file write happen outside the lock: a
        hook may call back into the Vault.
        """
        with self._liveness_lock:
            new_verdict = combined_verdict(
                self._last_liveness, self._latest_health or CLEAN
            )
            if new_verdict == self._verdict:
                return
            liveness = self._last_liveness
            state = VaultState(
                verdict=new_verdict,
                protect_mode=new_verdict in (SUSPICIOUS, INCIDENT),
                watcher_alive=(
                    None if liveness is None else liveness.alive
                ),
                snapshot_health=self._latest_health,
                previous_verdict=self._verdict,
            )
            self._previous_verdict = self._verdict
            self._verdict = new_verdict
            hook = self._state_hook
        self._append_alert(state, liveness)
        if hook is not None:
            hook(state)

    def _append_alert(
        self, state: VaultState, liveness: WatcherLiveness | None
    ) -> None:
        """One durable evidence line for a verdict change."""
        self._root.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "verdict": state.verdict,
            "previous_verdict": state.previous_verdict,
            "protect_mode": state.protect_mode,
            "watcher_alive": state.watcher_alive,
            "liveness_reason": None if liveness is None else liveness.reason,
            "snapshot_health": state.snapshot_health,
        }
        path = self._root / ALERT_LOG
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")

    def _newest_snapshot_health(self) -> str | None:
        """The S7 witness as last recorded on disk, if any snapshot exists."""
        ids = _manifest.manifest_ids(self._root)
        if not ids:
            return None
        return _manifest.read_manifest(self._root, ids[-1])["health"]

    def _pull_files(self) -> dict[str, tuple[FileEntry, float]]:
        """Read every file under share/, storing new blobs. Never writes there."""
        entries: dict[str, tuple[FileEntry, float]] = {}
        for path in sorted(self._share.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            if path.name == HEARTBEAT_FILENAME:
                # The liveness heartbeat is a signal, not backup data. It
                # changes every few seconds by design; pulling it would
                # pollute the data health check. The Vault reads it through
                # check_watcher_liveness() instead.
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
