"""Next month's grain quota file for each fair price shop.

A job the district PDS software runs by itself each night. It knows nothing
about Nightkeep: standard library only, everything it needs through argv.

It writes one .tmp file per shop into share/allocations/: the legacy habit
nobody fixed, which is why fix_dat.vbs exists to rename them to .dat later.
A big run lands on the 1st, small top-ups mid-month, and a vendor bug
sometimes runs the whole thing twice in one night; the scheduler decides
which, this job just writes the files it is told to. Either way it appends
what it really did to its own ground-truth log,
logs/_truth/allocation_gen.jsonl.
"""

import argparse
import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

JOB = "allocation_gen"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--day", type=int, required=True)
    parser.add_argument("--business-date", required=True)
    parser.add_argument("--sim-start", required=True)
    parser.add_argument("--sim-end", required=True)
    parser.add_argument("--files", type=int, required=True)
    args = parser.parse_args()

    business_date = date.fromisoformat(args.business_date)
    allotment_month = _next_month(business_date)
    fps_ids = _shops(args.root, args.files)

    truth = {"skipped": None, "created": [], "modified": [], "renamed": [],
              "deleted": [], "bytes_written": 0, "extensions": []}
    extensions: set[str] = set()
    for fps_id in fps_ids:
        existed, path = _write_allocation(args.root, fps_id, allotment_month)
        name = path.relative_to(args.root).as_posix()
        truth["modified" if existed else "created"].append(name)
        truth["bytes_written"] += path.stat().st_size
        extensions.add(path.suffix)
    truth["extensions"] = sorted(extensions)
    if not fps_ids:
        truth["skipped"] = "no shops to allocate for"

    _append_truth(args, truth)


def _next_month(business_date: date) -> str:
    if business_date.month == 12:
        return f"{business_date.year + 1}-01"
    return f"{business_date.year}-{business_date.month + 1:02d}"


def _shops(root: Path, count: int) -> list[str]:
    db = root / "data" / "district.db"
    conn = sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT fps_id FROM shops ORDER BY fps_id LIMIT ?", (count,)
        ).fetchall()
    finally:
        conn.close()
    return [row[0] for row in rows]


def _write_allocation(root: Path, fps_id: str, allotment_month: str) -> tuple[bool, Path]:
    path = root / "share" / "allocations" / f"alloc_{fps_id}_{allotment_month}.tmp"
    existed = path.exists()
    path.write_text(
        f"fps_id={fps_id}\nallotment_month={allotment_month}\n", encoding="utf-8"
    )
    return existed, path


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
