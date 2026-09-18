"""Allocation Generator: Next month's grain quota file for each fair price shop.

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
    parser = argparse.ArgumentParser(description="PDS Monthly Allocation Generator")
    parser.add_argument("--db-path", required=True, help="Path to district SQLite database")
    parser.add_argument("--out-dir", required=True, help="District root directory")
    parser.add_argument("--truth-log", required=True, help="Path to ground-truth JSONL log")
    parser.add_argument("--sim-date", required=True, help="Simulated date YYYY-MM-DD")
    parser.add_argument("--sim-time", required=True, help="Simulated run time HH:MM")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--is-month-start", action="store_true", help="Full allocation for all shops")
    parser.add_argument("--shop-count", type=int, default=50, help="Number of shops to generate for")

    args = parser.parse_args(argv)

    rng = random.Random(args.seed)
    truth_log_path = Path(args.truth_log)
    truth_log_path.parent.mkdir(parents=True, exist_ok=True)

    db_path = Path(args.db_path)
    if not db_path.is_file():
        sys.stderr.write(f"Database not found: {db_path}\n")
        return 1

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT fps_id, name, taluka, village FROM shops ORDER BY fps_id")
    shops = cursor.fetchall()
    conn.close()

    if not shops:
        sys.stderr.write("No shops found in database.\n")
        return 1

    if args.is_month_start:
        target_shops = shops
    else:
        sample_size = min(args.shop_count, len(shops))
        target_shops = rng.sample(shops, sample_size)
        target_shops.sort(key=lambda s: s[0])

    allocations_dir = Path(args.out_dir) / "allocations"
    allocations_dir.mkdir(parents=True, exist_ok=True)

    month_str = args.sim_date[:7]  # YYYY-MM
    written_files = []
    total_bytes = 0

    fieldnames = ["fps_id", "taluka", "village", "commodity", "allotment_month", "quota_kg"]

    for fps_id, _name, taluka, village in target_shops:
        alloc_file = allocations_dir / f"alloc_{fps_id}_{month_str}.csv"
        # Base quotas with slight randomized variation
        rice_quota = round(rng.uniform(1500.0, 3000.0), 2)
        wheat_quota = round(rng.uniform(1000.0, 2000.0), 2)
        sugar_quota = round(rng.uniform(80.0, 150.0), 2)

        with alloc_file.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(fieldnames)
            writer.writerow([fps_id, taluka, village, "rice", month_str, rice_quota])
            writer.writerow([fps_id, taluka, village, "wheat", month_str, wheat_quota])
            writer.writerow([fps_id, taluka, village, "sugar", month_str, sugar_quota])

        total_bytes += alloc_file.stat().st_size
        written_files.append(str(alloc_file))

    truth_entry = {
        "job": "allocation_gen",
        "sim_date": args.sim_date,
        "sim_time": args.sim_time,
        "status": "SUCCESS",
        "is_month_start": args.is_month_start,
        "shops_allocated": len(target_shops),
        "files_written": written_files,
        "bytes_written": total_bytes,
    }

    with truth_log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(truth_entry) + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
