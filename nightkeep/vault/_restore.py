"""Putting a snapshot back, and proving it worked.

Two promises hold this together.

**Never on top.** A restore writes into a new folder of its own. The damaged
data is still on disk afterwards, untouched, which is what makes trying a
restore a safe thing to do rather than a decision. If a check fails, nothing
has been lost by finding out.

**Never "trust us".** Every sentence the console puts on the Restore screen
comes from a `Check` in here that actually ran. The wording is written at
the point the check is made, in the language a counter clerk reads, because
the module that knows why is the only one that can say why.
"""

import csv
import io
from dataclasses import dataclass
from pathlib import Path

from nightkeep.types import Check, RestoreResult
from nightkeep.vault import _health, _store

CARDS_TABLE = "cards"


@dataclass(frozen=True)
class Restored:
    """Where the files landed, before anything has been verified."""

    folder: Path
    written: tuple[Path, ...]
    database: Path | None


def write_files(
    store: _store.Store, manifest: dict, into: Path
) -> Restored:
    """Lay a snapshot's files out under `into`, rebuilding the folder tree."""
    into.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    databases: list[Path] = []

    for entry in manifest["files"]:
        target = into / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(store.get(entry["sha256"]))
        written.append(target)
        if target.suffix.lower() in (".db", ".sqlite"):
            databases.append(target)

    # The nightly safe copy is what the district database is rebuilt from.
    # Newest by name, which is the business date the job stamped on it.
    database = sorted(databases)[-1] if databases else None
    return Restored(folder=into, written=tuple(written), database=database)


def verify(
    store: _store.Store,
    manifest: dict,
    restored: Restored,
    expected_records: int,
    suspect_randomness: float,
) -> tuple[list[Check], int]:
    """Run the five checks. Returns them and the count of cards found."""
    checks: list[Check] = []
    found = 0

    # 1. The records themselves. The number on the screen, and the reason
    #    anyone is doing this at all.
    if restored.database is None:
        checks.append(Check(
            statement=(
                "This safe copy does not contain a district database, so no "
                "ration cards could be counted."
            ),
            passed=False,
        ))
    else:
        try:
            found = _health.counts_records(restored.database, CARDS_TABLE)
        except Exception:
            found = 0
        checks.append(Check(
            statement=(
                f"Every one of the {expected_records:,} ration cards is "
                f"present and readable. Found {found:,}."
            ),
            passed=found == expected_records,
        ))

    # 2. Content addressing, checked rather than assumed. Every file is
    #    re-hashed after it lands, so a blob that rotted on disk is caught.
    mismatched = [
        entry["path"] for entry in manifest["files"]
        if _store.sha256_of((restored.folder / entry["path"]).read_bytes())
        != entry["sha256"]
    ]
    checks.append(Check(
        statement=(
            f"All {len(manifest['files'])} restored files match their safe "
            f"copy on the Vault, byte for byte."
            if not mismatched else
            f"{len(mismatched)} restored files do not match their safe copy."
        ),
        passed=not mismatched,
    ))

    # 3. Not just present, but readable: the same damage test the health
    #    check applies at pull time, applied again to what came back.
    damaged = [
        damage.path for entry in manifest["files"]
        if (damage := _health.inspect(
            entry["path"],
            (restored.folder / entry["path"]).read_bytes()[:_health.SAMPLE_BYTES],
            suspect_randomness,
        )) is not None
    ]
    checks.append(Check(
        statement=(
            "File headers and formats are intact, with no scrambled files."
            if not damaged else
            f"{len(damaged)} restored files are still unreadable."
        ),
        passed=not damaged,
    ))

    # 4. Parsing, not just decoding. An export with a ragged row is a file
    #    the state server will reject, and better found here than there.
    unparsable = [
        path for path in restored.written
        if path.suffix.lower() == ".csv" and not _parses_as_csv(path)
    ]
    csv_count = sum(1 for path in restored.written if path.suffix.lower() == ".csv")
    checks.append(Check(
        statement=(
            f"All {csv_count} monthly allocation files and fair price shop "
            f"records parse correctly."
            if not unparsable else
            f"{len(unparsable)} allocation or shop record files will not parse."
        ),
        passed=not unparsable,
    ))

    # 5. SQLite's own opinion, which is the only one that matters about
    #    whether a database file is sound all the way through.
    if restored.database is None:
        checks.append(Check(
            statement="No district database was present to check.",
            passed=False,
        ))
    else:
        sound = _health.integrity_ok(restored.database)
        checks.append(Check(
            statement=(
                "The restored district database passed its own internal "
                "integrity check."
                if sound else
                "The restored district database failed its internal "
                "integrity check."
            ),
            passed=sound,
        ))

    return checks, found


def _parses_as_csv(path: Path) -> bool:
    """Every row readable, and every row the same width as the header."""
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return False
    try:
        rows = list(csv.reader(io.StringIO(text)))
    except csv.Error:
        return False
    if not rows:
        return True
    width = len(rows[0])
    return all(len(row) == width for row in rows if row)


def result(
    snapshot_id: str,
    restored: Restored,
    checks: list[Check],
    found: int,
    expected: int,
) -> RestoreResult:
    """Fold the checks into the one value the console renders."""
    failed = [check for check in checks if not check.passed]
    if failed:
        reasons = tuple(check.statement for check in failed)
    else:
        reasons = (
            f"All {len(checks)} checks passed. {found:,} of {expected:,} "
            f"ration cards are back, in a new folder beside the damaged one.",
        )
    return RestoreResult(
        ok=not failed,
        snapshot_id=snapshot_id,
        restored_to=str(restored.folder),
        records_verified=found,
        records_expected=expected,
        checks=tuple(checks),
        reasons=reasons,
    )
