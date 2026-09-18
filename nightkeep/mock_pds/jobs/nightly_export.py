"""Nightly Export: Day-end export of transactions for the state server.

Standalone job script. Contains zero imports from Nightkeep.
Receives all configuration and paths through argv.
"""

import argparse
import csv
import json
import random
import sqlite3
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PDS Nightly Transaction Export")
    parser.add_argument("--db-path", required=True, help="Path to district SQLite database")
    parser.add_argument("--out-dir", required=True, help="District root directory")
    parser.add_argument("--truth-log", required=True, help="Path to ground-truth JSONL log")
    parser.add_argument("--sim-date", required=True, help="Simulated date YYYY-MM-DD")
    parser.add_argument("--sim-time", required=True, help="Simulated run time HH:MM")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for volume/skips")
    parser.add_argument("--row-count", type=int, default=240, help="Target row count to export")
    parser.add_argument("--network-down", action="store_true", help="Simulate network failure")

    args = parser.parse_args(argv)

    rng = random.Random(args.seed)
    truth_log_path = Path(args.truth_log)
    truth_log_path.parent.mkdir(parents=True, exist_ok=True)

    if args.network_down:
        # Network is down: export skips
        truth_entry = {
            "job": "nightly_export",
            "sim_date": args.sim_date,
            "sim_time": args.sim_time,
            "status": "SKIPPED_NETWORK_DOWN",
            "rows_exported": 0,
            "files_written": [],
            "bytes_written": 0,
        }
        with truth_log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(truth_entry) + "\n")
        return 0

    db_path = Path(args.db_path)
    if not db_path.is_file():
        sys.stderr.write(f"Database not found: {db_path}\n")
        return 1

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT transaction_id, card_no, fps_id, occurred_at, allotment_month, "
        "commodity, quantity_kg, auth_mode, status FROM transactions ORDER BY transaction_id"
    )
    all_rows = cursor.fetchall()
    conn.close()

    if not all_rows:
        rows_to_export = []
    else:
        count = min(args.row_count, len(all_rows))
        rows_to_export = rng.sample(all_rows, count)
        rows_to_export.sort(key=lambda r: r[0])

    exports_dir = Path(args.out_dir) / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    export_file = exports_dir / f"transactions_{args.sim_date}.csv"

    fieldnames = [
        "transaction_id", "card_no", "fps_id", "occurred_at", "allotment_month",
        "commodity", "quantity_kg", "auth_mode", "status"
    ]

    with export_file.open("w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(fieldnames)
        for row in rows_to_export:
            writer.writerow(row)

    file_size = export_file.stat().st_size

    truth_entry = {
        "job": "nightly_export",
        "sim_date": args.sim_date,
        "sim_time": args.sim_time,
        "status": "SUCCESS",
        "rows_exported": len(rows_to_export),
        "files_written": [str(export_file)],
        "bytes_written": file_size,
    }

    with truth_log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(truth_entry) + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
