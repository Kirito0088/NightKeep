"""Where habit cards live: one SQLite file, nothing clever.

Three tables. `runs` is the raw observations, one row per job run, because a
median is only as good as the numbers under it and throwing them away would
make a card impossible to explain. `seen_extensions` is what each job has
ever produced, which is what makes S4's "unseen extension" mean something.
`card_versions` records that a job's script changed, because legitimate jobs
do change and a card built on the old script is no longer about this job.
"""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

_DDL = """
CREATE TABLE IF NOT EXISTS runs (
    run_id      INTEGER PRIMARY KEY,
    job         TEXT NOT NULL,
    identity    TEXT NOT NULL,
    version     INTEGER NOT NULL,
    day_no      INTEGER,
    observed_at TEXT NOT NULL,
    numbers     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS runs_by_job ON runs (job, version);

CREATE TABLE IF NOT EXISTS seen_extensions (
    job       TEXT NOT NULL,
    extension TEXT NOT NULL,
    PRIMARY KEY (job, extension)
);

CREATE TABLE IF NOT EXISTS card_versions (
    job        TEXT NOT NULL,
    version    INTEGER NOT NULL,
    identity   TEXT NOT NULL,
    started_at TEXT NOT NULL,
    PRIMARY KEY (job, version)
);
"""


@dataclass(frozen=True)
class Version:
    """Which card a job is currently on, and what script it belongs to."""

    version: int
    identity: str
    is_new: bool


class Store:
    """The habit database. Opened per call, so no connection is held."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_DDL)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """One connection for one call: committed, then closed.

        sqlite3's own `with conn:` only commits; it never closes. A
        connection left for the garbage collector keeps habit.db open, and
        on Windows an open file cannot be deleted, so the console's fresh
        run could not clear the old session's folder.
        """
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    # --- card versions ----------------------------------------------------

    def version_for(self, job: str, identity: str, at: datetime) -> Version:
        """The current card version for this job, starting a new one if the
        script behind it has changed."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT version, identity FROM card_versions WHERE job = ? "
                "ORDER BY version DESC LIMIT 1",
                (job,),
            ).fetchone()
            if row is not None and row["identity"] == identity:
                return Version(row["version"], identity, is_new=False)

            version = 1 if row is None else row["version"] + 1
            conn.execute(
                "INSERT INTO card_versions (job, version, identity, started_at) "
                "VALUES (?, ?, ?, ?)",
                (job, version, identity, at.isoformat()),
            )
            # Version 1 is a job being met for the first time, which is not
            # the same event as a job's script changing under us.
            return Version(version, identity, is_new=version > 1)

    def current_version(self, job: str) -> int | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT version FROM card_versions WHERE job = ? "
                "ORDER BY version DESC LIMIT 1",
                (job,),
            ).fetchone()
        return row["version"] if row else None

    # --- observations ------------------------------------------------------

    def add_run(
        self,
        job: str,
        identity: str,
        version: int,
        day_no: int | None,
        observed_at: datetime,
        numbers: dict[str, float],
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO runs (job, identity, version, day_no, observed_at, "
                "numbers) VALUES (?, ?, ?, ?, ?, ?)",
                (job, identity, version, day_no, observed_at.isoformat(),
                 json.dumps(numbers)),
            )

    def observations(self, job: str, version: int) -> list[dict[str, float]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT numbers FROM runs WHERE job = ? AND version = ? "
                "ORDER BY run_id",
                (job, version),
            ).fetchall()
        return [json.loads(row["numbers"]) for row in rows]

    def run_count(self, job: str, version: int) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM runs WHERE job = ? AND version = ?",
                (job, version),
            ).fetchone()
        return int(row["n"])

    def jobs(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT job FROM card_versions ORDER BY job"
            ).fetchall()
        return [row["job"] for row in rows]

    # --- extensions --------------------------------------------------------

    def remember_extensions(self, job: str, extensions: frozenset[str]) -> None:
        if not extensions:
            return
        with self._connect() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO seen_extensions (job, extension) VALUES (?, ?)",
                [(job, extension) for extension in sorted(extensions)],
            )

    def seen_extensions(self, job: str | None = None) -> frozenset[str]:
        """What this job has produced before, or what any job ever has.

        The second form is what S4 asks: an extension no job on this machine
        has ever written is a stronger signal than one this job has not.
        """
        with self._connect() as conn:
            if job is None:
                rows = conn.execute("SELECT extension FROM seen_extensions").fetchall()
            else:
                rows = conn.execute(
                    "SELECT extension FROM seen_extensions WHERE job = ?", (job,)
                ).fetchall()
        return frozenset(row["extension"] for row in rows)
