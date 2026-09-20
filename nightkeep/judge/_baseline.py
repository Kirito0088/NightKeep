"""What each file's content looked like last time Nightkeep saw it.

S3 needs a "before" to compare against, and the only honest source for it on
the PDS server is the PDS server. Asking the Vault would put a path to the
Vault in the server's hands, which is rule 3, so this is a small local table
and nothing more: path, entropy, and when it was measured.

It is updated only from runs that were judged NORMAL or ODD. A run that
raised a verdict has, by definition, told us its files are not a trustworthy
picture of normal, and folding it in would let an attack teach Nightkeep
that scrambled is the new baseline.

One connection is held open for the life of the object. An attack produces
thousands of events in a few seconds, and opening a database connection per
file turns a two-second judgement into a thirty-second one, which is the
difference between catching ransomware and watching it finish.
"""

import sqlite3
from datetime import datetime
from pathlib import Path

_DDL = """
CREATE TABLE IF NOT EXISTS entropy_baseline (
    path        TEXT PRIMARY KEY,
    entropy     REAL NOT NULL,
    measured_at TEXT NOT NULL
);
"""

DATABASE_NAME = "judge.db"


class Baseline:
    """Path to last known entropy. Small, local, and rewritable."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_DDL)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def entropy_of(self, path: str) -> float | None:
        row = self._conn.execute(
            "SELECT entropy FROM entropy_baseline WHERE path = ?", (path,)
        ).fetchone()
        return float(row["entropy"]) if row else None

    def remember(self, path: str, entropy: float, at: datetime) -> None:
        self.remember_many([(path, entropy)], at)

    def remember_many(
        self, readings: list[tuple[str, float]], at: datetime
    ) -> None:
        """One transaction for a whole night's worth of files."""
        if not readings:
            return
        when = at.isoformat()
        self._conn.executemany(
            "INSERT INTO entropy_baseline (path, entropy, measured_at) "
            "VALUES (?, ?, ?) ON CONFLICT(path) DO UPDATE SET "
            "entropy = excluded.entropy, measured_at = excluded.measured_at",
            [(path, entropy, when) for path, entropy in readings],
        )
        self._conn.commit()

    def knows(self, path: str) -> bool:
        return self.entropy_of(path) is not None

    def count(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM entropy_baseline"
        ).fetchone()
        return int(row["n"])
