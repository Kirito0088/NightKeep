"""The fake district PDS server: data, jobs, clock, hidden ground truth.

Public interface:
    build_district(seed, district, out_dir)
    run_day(day_no)  # lands with #3/#4/#5, the six jobs

Hides 5,000 ration cards, 6 erratic jobs, their randomness, the simulated
clock and the hidden truth log. Nothing outside this package and tests/ may
read logs/_truth/.
"""

import sqlite3
from pathlib import Path

from nightkeep.config import District
from nightkeep.mock_pds import _generate
from nightkeep.mock_pds._schema import create_schema

_SIBLING_FOLDERS = ("exports", "allocations", "reports", "archive", "logs")


def build_district(seed: int, district: District, out_dir: Path) -> Path:
    """Build a fresh Thane district database and its folder layout.

    Creates out_dir/data/district.db, plus the exports, allocations,
    reports, archive and logs folders the nightly jobs will later write
    into. The same seed always reproduces the same district. Returns
    out_dir.
    """
    out_dir = Path(out_dir)
    data_dir = out_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    for folder in _SIBLING_FOLDERS:
        (out_dir / folder).mkdir(parents=True, exist_ok=True)

    db_path = data_dir / "district.db"
    db_path.unlink(missing_ok=True)

    conn = sqlite3.connect(db_path)
    try:
        create_schema(conn)
        _generate.generate(conn, seed, district)
    finally:
        conn.close()

    return out_dir
