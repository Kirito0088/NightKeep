"""Counter clerks editing e-KYC status in office hours.

A job the district PDS software runs by itself, standing in for a clerk at
a keyboard: standard library only, everything it needs through argv. It
knows nothing about Nightkeep.

The scheduler decides how many members to touch and hands over a seed, so
the same simulated day always edits the same members the same way; this
job never seeds its own randomness. On a Sunday the scheduler still runs
it, with --sunday set, so the office being shut is itself part of the
learned habit. Either way it appends what it really did to its own
ground-truth log, logs/_truth/operator_activity.jsonl.
"""

import argparse
import json
import random
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path

JOB = "operator_activity"
_EKYC_STATUSES = ("Done", "Pending")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--day", type=int, required=True)
    parser.add_argument("--sim-start", required=True)
    parser.add_argument("--scale", type=float, required=True)
    parser.add_argument("--edits", type=int, required=True)
    parser.add_argument("--edit-seed", type=int, required=True)
    parser.add_argument("--sunday", action="store_true")
    args = parser.parse_args()
    began = time.monotonic()

    truth = {"skipped": None, "created": [], "modified": [], "renamed": [],
             "deleted": [], "bytes_written": 0, "extensions": []}
    if args.sunday:
        truth["skipped"] = "Sunday, office closed"
    else:
        db_path = args.root / "data" / "district.db"
        edited = _edit_members(db_path, args.edits, args.edit_seed)
        if edited:
            name = (Path("data") / "district.db").as_posix()
            truth["modified"].append(name)
            truth["bytes_written"] = db_path.stat().st_size
            truth["extensions"] = [db_path.suffix]
        else:
            truth["skipped"] = "no members to edit"

    _append_truth(args, began, truth)


def _edit_members(db_path: Path, count: int, edit_seed: int) -> bool:
    rng = random.Random(edit_seed)
    conn = sqlite3.connect(db_path)
    try:
        member_ids = [row[0] for row in conn.execute("SELECT member_id FROM members")]
        chosen = rng.sample(member_ids, min(count, len(member_ids))) if member_ids else []
        if not chosen:
            return False
        for member_id in chosen:
            new_status = rng.choice(_EKYC_STATUSES)
            conn.execute(
                "UPDATE members SET ekyc_status = ? WHERE member_id = ?",
                (new_status, member_id),
            )
        conn.commit()
        return True
    finally:
        conn.close()


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
