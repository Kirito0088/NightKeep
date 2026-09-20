"""The one check every simulator entry point calls before touching a file.

CLAUDE.md's hard safety rail: "hard-codes a path check and refuses to run
outside the demo folder." The literal string "demo" in a path is not a
safety boundary on its own, since any folder can be named that. What
actually identifies "the demo folder" is that `mock_pds.build_district`
built it: it has a SQLite database at data/district.db with the four
tables `_schema.py` creates. Nothing else on a machine looks like that by
accident, so this is the check, not a comment promising one.
"""

import sqlite3
from pathlib import Path

REQUIRED_TABLES = frozenset({"shops", "cards", "members", "transactions"})


class UnsafeRootError(RuntimeError):
    """Raised instead of touching anything outside a real demo district."""


def confirm_demo_district(root: Path) -> Path:
    """Resolve root and confirm mock_pds built a district there.

    Returns the resolved path so every caller works from the same value.
    Raises UnsafeRootError, naming what was missing, otherwise.
    """
    resolved = Path(root).resolve()
    db_path = resolved / "data" / "district.db"
    if not db_path.is_file():
        raise UnsafeRootError(
            f"refusing to run: no district database at {db_path}"
        )

    try:
        connection = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)
        try:
            tables = {
                row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        finally:
            connection.close()
    except sqlite3.Error as problem:
        raise UnsafeRootError(
            f"refusing to run: {db_path} is not a readable district database ({problem})"
        ) from problem

    if not REQUIRED_TABLES <= tables:
        raise UnsafeRootError(
            f"refusing to run: {db_path} does not match a mock_pds district"
        )

    return resolved
