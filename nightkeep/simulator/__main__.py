"""Run one simulator variant as its own process.

The judge suspends the busiest process on INCIDENT and the watcher
attributes file events to their writer, so each variant runs here as a real
subprocess rather than as a library call inside the demo runner.

Every tunable arrives as a command-line argument: the simulator never
reaches for configuration itself (repo rule: configuration is read once,
at startup, by the entrypoint). The orchestrating entrypoint loads it and
passes the values through, for example:

    python -m nightkeep.simulator --variant fast --root <demo dir> \\
        --key "$KEY" --locked-extension .locked \\
        --ransom-note-name HOW_TO_GET_YOUR_FILES_BACK.txt --delay 0.01

    python -m nightkeep.simulator --variant impersonator --root <demo dir> \\
        --key "$KEY" --locked-extension .locked \\
        --ransom-note-name HOW_TO_GET_YOUR_FILES_BACK.txt --delay 0.01 \\
        --day 8 --sim-start 2026-09-22T02:14:00 --sim-end 2026-09-22T06:00:00

    python -m nightkeep.simulator --variant recovery-killer --root <demo dir> \\
        --key "$KEY" --locked-extension .locked \\
        --ransom-note-name HOW_TO_GET_YOUR_FILES_BACK.txt --delay 0.01 \\
        --command "vssadmin delete shadows" --command "wbadmin delete catalog"

    python -m nightkeep.simulator --variant watcher-killer --root <demo dir>

The demo-folder boundary is hard-coded in the simulator module and cannot
be tuned away. The watcher-killer touches no files: it terminates only the
heartbeat worker process marked for that demo root.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime

from nightkeep import simulator


def _common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", required=True, help="demo folder to attack")
    parser.add_argument("--key", required=True, help="known reversible key")
    parser.add_argument("--locked-extension", required=True)
    parser.add_argument("--ransom-note-name", required=True)
    parser.add_argument(
        "--delay",
        type=float,
        default=0,
        help="seconds between files (slows the burst for drills)",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="NightKeep safe ransomware simulator (rehearsal only)."
    )
    parser.add_argument(
        "--variant",
        required=True,
        choices=["fast", "impersonator", "recovery-killer", "watcher-killer"],
    )
    _common_arguments(parser)
    parser.add_argument(
        "--command",
        action="append",
        default=[],
        help="recovery command text to echo (repeatable, recovery-killer only)",
    )
    parser.add_argument("--day", type=int, default=8)
    parser.add_argument("--sim-start", default=None)
    parser.add_argument("--sim-end", default=None)
    args = parser.parse_args(argv)

    try:
        if args.variant == "fast":
            report = simulator.fast_encrypt(
                args.root,
                key=args.key,
                locked_extension=args.locked_extension,
                ransom_note_name=args.ransom_note_name,
                delay_between_files_seconds=args.delay,
            )
        elif args.variant == "impersonator":
            sim_start = (
                datetime.fromisoformat(args.sim_start)
                if args.sim_start
                else datetime.now()
            )
            sim_end = (
                datetime.fromisoformat(args.sim_end)
                if args.sim_end
                else sim_start
            )
            report = simulator.impersonate(
                args.root,
                day_no=args.day,
                sim_start=sim_start,
                sim_end=sim_end,
                key=args.key,
                locked_extension=args.locked_extension,
                ransom_note_name=args.ransom_note_name,
                delay_between_files_seconds=args.delay,
            )
        elif args.variant == "watcher-killer":
            report = simulator.watcher_killer(args.root)
        else:
            report = simulator.recovery_killer(
                args.root,
                key=args.key,
                locked_extension=args.locked_extension,
                ransom_note_name=args.ransom_note_name,
                delay_between_files_seconds=args.delay,
                commands=tuple(args.command),
            )
    except simulator.SimulatorRefused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2

    if report.variant == "watcher-killer":
        print(
            "watcher-killer: terminated heartbeat worker pids "
            f"{list(report.killed_pids)}"
        )
    else:
        print(
            f"{report.variant}: encrypted {report.files_encrypted} files, "
            f"renamed {report.files_renamed}, notes {report.notes_written}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
