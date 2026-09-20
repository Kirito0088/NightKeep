"""Day-end export of ePoS transactions for the state server.

A job the district PDS software runs by itself each night. It knows nothing
about Nightkeep: standard library only, everything it needs through argv.

It writes one CSV of the business day's transactions into share/exports/. On a
night the network is down there is nothing to upload to, so it writes
nothing. Either way it appends what it really did to its own ground-truth
log, logs/_truth/nightly_export.jsonl.
"""

import argparse
import csv
import json
import sqlite3
from datetime import datetime
from pathlib import Path

JOB = "nightly_export"
COLUMNS = (
    "transaction_id", "card_no", "fps_id", "occurred_at", "allotment_month",
    "commodity", "quantity_kg", "auth_mode", "status",
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--day", type=int, required=True)
    parser.add_argument("--business-date", required=True)
    parser.add_argument("--sim-start", required=True)
    parser.add_argument("--sim-end", required=True)
    parser.add_argument("--network-down", action="store_true")
    args = parser.parse_args()

    truth = {"skipped": None, "created": [], "modified": [], "renamed": [],
             "deleted": [], "bytes_written": 0, "extensions": [], "rows": None}
    if args.network_down:
        truth["skipped"] = "network down"
    else:
        existed, export, rows = _export(args.root, args.business_date)
        name = export.relative_to(args.root).as_posix()
        truth["modified" if existed else "created"].append(name)
        truth["bytes_written"] = export.stat().st_size
        truth["extensions"] = [export.suffix]
        truth["rows"] = rows

    _append_truth(args, truth)


def _export(root: Path, business_date: str) -> tuple[bool, Path, int]:
    db = root / "data" / "district.db"
    # Read-only, so the export never touches the live database.
    conn = sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            f"SELECT {', '.join(COLUMNS)} FROM transactions "
            "WHERE substr(occurred_at, 1, 10) = ? ORDER BY transaction_id",
            (business_date,),
        ).fetchall()
    finally:
        conn.close()

    path = root / "share" / "exports" / f"epos_day_end_{business_date.replace('-', '')}.csv"
    existed = path.exists()
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(COLUMNS)
        quantity = COLUMNS.index("quantity_kg")
        for row in rows:
            row = list(row)
            row[quantity] = f"{row[quantity]:.3f}"
            writer.writerow(row)
    return existed, path, len(rows)


def _append_truth(args: argparse.Namespace, truth: dict) -> None:
    sim_start = datetime.fromisoformat(args.sim_start)
    sim_end = datetime.fromisoformat(args.sim_end)
    line = {"job": JOB, "day": args.day, "sim_start": sim_start.isoformat(),
            "sim_end": sim_end.isoformat(timespec="seconds"), **truth}
    log = args.root / "logs" / "_truth" / f"{JOB}.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line) + "\n")


if __name__ == "__main__":
    main()
