"""The learning week, end to end, and what the jobs really did in it.

A deliverable, not a check. It runs the seven learning days from one seed and
reports, per job, how many nights it ran, when it started, how much it wrote
and how far those numbers moved from night to night. If the week comes back
tidy, the twist the whole project rests on is untestable, and better to know
that before the Watcher, the Habit Cards and the Judge are built on top of it.

It reads the jobs' own ground-truth logs, which is why it lives inside
mock_pds: no Nightkeep module may open them. Like every module here it takes
its values as arguments. The entrypoint runs it:

    python -m nightkeep --prove-erratic --seed 20260922
"""

import json
import shutil
from datetime import datetime, time
from pathlib import Path

from nightkeep.config import Clock, District, HarvestSurge, Jobs
from nightkeep.mock_pds import build_district, run_day

SUMMARY_NAME = "erratic_summary.json"

_FILE_KINDS = ("created", "modified", "renamed", "deleted")
_MINUTES_A_DAY = 24 * 60


def prove(
    *, seed: int, district: District, clock: Clock, jobs: Jobs,
    harvest_surge: HarvestSurge, out_dir: Path,
) -> dict:
    """Live the learning week on a fresh district and summarise what happened.

    Takes clock.learning_days * clock.simulated_day_seconds of real time.
    Returns the summary, and leaves a copy in reports/erratic_summary.json.
    """
    out_dir = Path(out_dir)
    _clear(out_dir)
    district_dir = build_district(seed, district, out_dir)
    for day_no in range(1, clock.learning_days + 1):
        run_day(
            day_no, seed=seed, clock=clock, jobs=jobs,
            harvest_surge=harvest_surge, district_dir=district_dir,
        )

    summary = {
        "seed": seed,
        "days": clock.learning_days,
        "harvest_surge_days": list(harvest_surge.days),
        "jobs": {
            job: _job_summary(_truth(district_dir, job), clock.day_starts_at)
            for job in sorted(vars(jobs))
        },
    }
    path = district_dir / "reports" / SUMMARY_NAME
    path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def _clear(out_dir: Path) -> None:
    """Empty a district an earlier run left behind, so the week starts fresh.

    Anything that is not one of this script's own districts is left alone: a
    mistyped out_dir must not cost someone a folder.
    """
    if not out_dir.exists() or not any(out_dir.iterdir()):
        return
    if not (out_dir / "data" / "district.db").exists():
        raise ValueError(
            f"{out_dir} holds something other than a district this script "
            "built. Choose an empty folder for --out-dir."
        )
    shutil.rmtree(out_dir)


def _truth(district_dir: Path, job: str) -> list[dict]:
    log = district_dir / "logs" / "_truth" / f"{job}.jsonl"
    if not log.exists():
        return []
    return [
        json.loads(line)
        for line in log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _job_summary(lines: list[dict], day_starts_at: time) -> dict:
    ran = [line for line in lines if line["skipped"] is None]
    return {
        "runs": len(ran),
        "nights_ran": len({line["day"] for line in ran}),
        "nights_skipped": len({line["day"] for line in lines if line["skipped"]}),
        "skipped_because": sorted({
            line["skipped"] for line in lines if line["skipped"]
        }),
        "start_time": _start_spread(lines, day_starts_at),
        "files": {
            kind: _spread([len(line[kind]) for line in ran])
            for kind in _FILE_KINDS
        },
        "bytes_written": _spread([line["bytes_written"] for line in ran]),
        "rows": _row_spread(ran),
        "extensions": sorted({
            extension for line in ran for extension in line["extensions"]
        }),
    }


def _spread(values: list[int]) -> dict | None:
    if not values:
        return None
    return {
        "low": min(values), "high": max(values), "spread": max(values) - min(values)
    }


def _start_spread(lines: list[dict], day_starts_at: time) -> dict | None:
    """Earliest and latest start, measured along the simulated day.

    Offsets run from day_starts_at, not from midnight, so a job whose window
    straddles midnight reads as one contiguous stretch rather than two ends
    of the clock.
    """
    if not lines:
        return None
    starts = [datetime.fromisoformat(line["sim_start"]) for line in lines]
    offsets = sorted(
        (_minutes_into_day(start, day_starts_at), start) for start in starts
    )
    return {
        "earliest": offsets[0][1].strftime("%H:%M"),
        "latest": offsets[-1][1].strftime("%H:%M"),
        "spread_minutes": offsets[-1][0] - offsets[0][0],
    }


def _minutes_into_day(moment: datetime, day_starts_at: time) -> int:
    day_start = day_starts_at.hour * 60 + day_starts_at.minute
    return (moment.hour * 60 + moment.minute - day_start) % _MINUTES_A_DAY


def _row_spread(ran: list[dict]) -> dict | None:
    """How far the export's row count moves, for the job that carries one.

    by_night is kept alongside the range because a harvest surge doubles one
    night on purpose, and a reader who cannot see the nights apart cannot
    tell that legitimate spike from the ordinary night-to-night drift.
    """
    by_night = {
        line["day"]: line["rows"] for line in ran if line.get("rows") is not None
    }
    if not by_night:
        return None
    counts = list(by_night.values())
    spread = _spread(counts)
    average = sum(counts) / len(counts)
    spread["swing_percent_of_average"] = round(spread["spread"] / average * 100)
    spread["by_night"] = {str(day): by_night[day] for day in sorted(by_night)}
    return spread


def render(summary: dict) -> str:
    """The same summary as something a person can read in one sitting."""
    surge = ", ".join(str(day) for day in summary["harvest_surge_days"])
    out = [
        f"{summary['days']} simulated days on seed {summary['seed']}, "
        f"harvest surge on day {surge}",
        "",
    ]
    for job, entry in summary["jobs"].items():
        out.append(f"{job}: ran {entry['nights_ran']} of {summary['days']} nights")
        if entry["skipped_because"]:
            out.append(f"  sat out         {', '.join(entry['skipped_because'])}")
        if entry["runs"] > entry["nights_ran"]:
            out.append(f"  launches        {entry['runs']} across those nights")
        start = entry["start_time"]
        if start:
            out.append(
                f"  started         {start['earliest']} to {start['latest']}, "
                f"a spread of {start['spread_minutes']} minutes"
            )
        rows = entry["rows"]
        if rows:
            out.append(
                f"  rows carried    {rows['low']:,} to {rows['high']:,}, a swing of "
                f"{rows['swing_percent_of_average']} percent of an average night"
            )
            nightly = ", ".join(
                f"day {day} {count:,}" for day, count in rows["by_night"].items()
            )
            out.append(f"  night by night  {nightly}")
        files = ", ".join(
            f"{kind} {entry['files'][kind]['low']} to {entry['files'][kind]['high']}"
            for kind in _FILE_KINDS if entry["files"][kind]
        )
        if files:
            out.append(f"  files           {files}")
        written = entry["bytes_written"]
        if written:
            out.append(f"  bytes written   {written['low']:,} to {written['high']:,}")
        if entry["extensions"]:
            out.append(f"  touched         {', '.join(entry['extensions'])}")
        out.append("")
    return "\n".join(out)
