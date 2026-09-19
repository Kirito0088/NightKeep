"""Nightkeep's entrypoint. Shallow glue, and the only caller of load_config.

It reads config.yaml once, then hands the values it holds to the modules as
arguments. Nothing here decides anything: it parses the command line, picks
which module to start and prints what that module handed back. As the modules
land, their start-up calls go below the summary, each taking what it needs
from `config`.
"""

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from nightkeep import mock_pds
from nightkeep.config import Config, ConfigError, load_config
from nightkeep.mock_pds import prove_erratic

DEFAULT_CONFIG = Path(__file__).resolve().parent / "config.yaml"
DEMO_DIR = Path(__file__).resolve().parent.parent / "demo"
ERRATIC_DIR = DEMO_DIR / "erratic_week"


def main(arguments: list[str]) -> int:
    """Read the config, then either report the set-up or prove the week."""
    parser = argparse.ArgumentParser(prog="nightkeep")
    parser.add_argument(
        "config", nargs="?", type=Path, default=DEFAULT_CONFIG,
        help="path to config.yaml",
    )
    parser.add_argument(
        "--prove-erratic", action="store_true",
        help="live the learning week and report how erratic the six jobs are",
    )
    parser.add_argument("--seed", type=int, help="overrides the seed in config.yaml")
    parser.add_argument(
        "--out-dir", type=Path, default=ERRATIC_DIR,
        help="where --prove-erratic builds its district",
    )
    parser.add_argument(
        "--day-seconds", type=int,
        help="overrides how much real time one simulated day takes",
    )
    args = parser.parse_args(arguments)

    try:
        config = load_config(args.config)
    except ConfigError as problem:
        print(f"Nightkeep cannot start. {problem}", file=sys.stderr)
        return 1

    if args.seed is not None:
        config = replace(config, seed=args.seed)
    if args.day_seconds is not None:
        config = replace(
            config, clock=replace(config.clock, simulated_day_seconds=args.day_seconds)
        )

    if args.prove_erratic:
        return _prove_erratic(config, args.out_dir)

    clock = config.clock
    print(f"Nightkeep, seed {config.seed}, config from {args.config}")
    print(
        f"{config.district.ration_cards:,} ration cards across "
        f"{config.district.fps_count} fair price shops"
    )
    print(
        f"{clock.learning_days} learning days then {clock.guard_days} guard "
        f"days, one day every {clock.simulated_day_seconds} s"
    )
    jobs = vars(config.jobs)
    print(f"{len(jobs)} jobs configured: " + ", ".join(jobs))

    district_dir = mock_pds.build_district(config.seed, config.district, DEMO_DIR)
    print(f"District built at {district_dir}")
    return 0


def _prove_erratic(config: Config, out_dir: Path) -> int:
    try:
        summary = prove_erratic.prove(
            seed=config.seed, district=config.district, clock=config.clock,
            jobs=config.jobs, harvest_surge=config.harvest_surge, out_dir=out_dir,
        )
    except ValueError as problem:
        print(f"Nightkeep cannot start. {problem}", file=sys.stderr)
        return 1

    print(prove_erratic.render(summary))
    print(f"Summary written to {out_dir / 'reports' / prove_erratic.SUMMARY_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
