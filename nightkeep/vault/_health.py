"""S7: the Vault's own health check, run on every pull.

Compares the new snapshot against the previous CLEAN one and marks it
SUSPECT when the data no longer looks like the PDS server's own messy self:
too many files changed, broken headers, high-entropy rewrites that are not
archives, brand-new file types, or a falling ration-card record count.

Self-contained on purpose. The PDS server and the Vault share no code that
carries state, so the Vault does its own header and entropy checks rather
than importing the judge's.
"""

import math
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path

from nightkeep.types import CLEAN, SUSPECT

# Archive types are allowed to look random. Everything else with jumped
# entropy and a broken header is treated as scrambled.
ARCHIVE_EXTENSIONS = frozenset({".zip"})


@dataclass(frozen=True)
class FileEntry:
    """What the pull saw for one file, by its path inside share/."""

    sha256: str
    size: int
    entropy: float
    header_ok: bool


@dataclass(frozen=True)
class Assessment:
    health: str
    reasons: tuple[str, ...]  # the SUSPECT reasons; empty when CLEAN
    record_count: int | None


def shannon_entropy(data: bytes) -> float:
    """Bits of randomness per byte, 0 for empty input."""
    if not data:
        return 0.0
    counts = [0] * 256
    for byte in data:
        counts[byte] += 1
    length = len(data)
    return -sum(
        (count / length) * math.log2(count / length)
        for count in counts
        if count
    )


def header_ok(name: str, data: bytes) -> bool:
    """Does the file's magic still match its extension?"""
    suffix = Path(name).suffix.lower()
    if suffix == ".db":
        return data.startswith(b"SQLite format 3\x00")
    if suffix in (".csv", ".tmp"):
        # The PDS jobs write plain UTF-8 text here. Encrypted bytes are not.
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return False
        return "\x00" not in text
    if suffix == ".zip":
        return data.startswith(b"PK\x03\x04")
    # An unknown type is not broken; its novelty is a separate signal.
    return True


def newest_backup(entries: dict[str, FileEntry]) -> str | None:
    """The newest database backup path in this pull, or None."""
    backups = [
        path for path in entries
        if path.startswith("backups/") and path.endswith(".db")
    ]
    return max(backups) if backups else None


def count_cards(data: bytes) -> int | None:
    """Rows in the cards table of a database backup. None if unreadable."""
    try:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=True) as tmp:
            tmp.write(data)
            tmp.flush()
            with sqlite3.connect(tmp.name) as conn:
                return conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    except Exception:
        return None


def assess(
    entries: dict[str, FileEntry],
    baseline: dict[str, FileEntry] | None,
    baseline_record_count: int | None,
    current_record_count: int | None,
    *,
    suspect_entropy: float,
    suspect_changed_fraction: float,
    suspect_record_drop_fraction: float,
) -> Assessment:
    """Judge one pull against the previous CLEAN snapshot."""
    if baseline is None:
        return Assessment(CLEAN, (), current_record_count)

    reasons: list[str] = []
    current_paths = set(entries)
    baseline_paths = set(baseline)
    changed = {
        path
        for path in current_paths | baseline_paths
        if entries.get(path) != baseline.get(path)
    }
    total = len(current_paths | baseline_paths)
    changed_fraction = len(changed) / max(total, 1)
    if changed_fraction > suspect_changed_fraction:
        reasons.append(
            f"{len(changed)} of {total} files changed since the last clean "
            f"snapshot, over the {suspect_changed_fraction:.0%} limit"
        )

    rewritten = [path for path in changed if path in entries]
    broken = [path for path in rewritten if not entries[path].header_ok]
    if broken:
        shown = ", ".join(sorted(broken)[:3])
        extra = f" and {len(broken) - 3} more" if len(broken) > 3 else ""
        reasons.append(
            f"{len(broken)} changed files no longer open as their own type: "
            f"{shown}{extra}"
        )
    scrambled = [
        path
        for path in rewritten
        if entries[path].entropy > suspect_entropy
        and Path(path).suffix.lower() not in ARCHIVE_EXTENSIONS
    ]
    if scrambled:
        shown = ", ".join(sorted(scrambled)[:3])
        extra = f" and {len(scrambled) - 3} more" if len(scrambled) > 3 else ""
        reasons.append(
            f"{len(scrambled)} changed files look randomly scrambled: "
            f"{shown}{extra}"
        )
    new_extensions = {
        Path(path).suffix.lower() for path in current_paths
    } - {
        Path(path).suffix.lower() for path in baseline_paths
    } - {""}
    if new_extensions:
        reasons.append(
            "new file types never seen before: "
            + ", ".join(sorted(new_extensions))
        )

    if current_record_count is None:
        reasons.append("no database backup found in this pull")
    elif baseline_record_count:
        drop = (baseline_record_count - current_record_count) / baseline_record_count
        if drop > suspect_record_drop_fraction:
            reasons.append(
                f"ration-card records fell from {baseline_record_count:,} to "
                f"{current_record_count:,}, over the "
                f"{suspect_record_drop_fraction:.0%} limit"
            )

    health = SUSPECT if reasons else CLEAN
    return Assessment(health, tuple(reasons), current_record_count)
