"""Nightly safe copy of the district database, for the Vault to pull.

A job the district PDS software runs by itself each night, after the
day-end export. It knows nothing about Nightkeep: standard library only,
everything it needs through argv.

It copies data/district.db with SQLite's own backup API, so the copy is
consistent even while the live database is open, names it after the
business day, and places it in share/backups/ for the Vault to pull. It appends what it really did to its own ground-truth log,
logs/_truth/db_backup.jsonl.
"""

import argparse
import json
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path

JOB = "db_backup"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--day", type=int, required=True)
    parser.add_argument("--business-date", required=True)
    parser.add_argument("--sim-start", required=True)
    parser.add_argument("--scale", type=float, required=True)
    args = parser.parse_args()
    began = time.monotonic()

    existed, copy = _back_up(args.root, args.business_date)
    name = copy.relative_to(args.root).as_posix()
    truth = {"skipped": None, "created": [], "modified": [], "renamed": [],
             "deleted": [], "bytes_written": copy.stat().st_size,
             "extensions": [copy.suffix]}
    truth["modified" if existed else "created"].append(name)

    _append_truth(args, began, truth)


def _back_up(root: Path, business_date: str) -> tuple[bool, Path]:
    live = root / "data" / "district.db"
    copy = root / "share" / "backups" / f"district-backup-{business_date}.db"
    existed = copy.exists()
    # Read-only, so the backup never touches the live database.
    source = sqlite3.connect(f"{live.as_uri()}?mode=ro", uri=True)
    target = sqlite3.connect(copy)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    return existed, copy


def _append_truth(args: argparse.Namespace, began: float, truth: dict) -> None:
    sim_start = datetime.fromisoformat(args.sim_start)
    sim_end = sim_start + timedelta(seconds=(time.monotonic() - began) * args.scale)
    line = {"job": JOB, "day": args.day, "sim_start": sim_start.isoformat(),
            "sim_end": sim_end.isoformat(timespec="seconds"), **truth}
    log = args.root / "logs" / "_truth" / f"{JOB}.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line) + "\n")


if __name__ == "__main__":
    main()
