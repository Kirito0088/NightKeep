"""Nightkeep's entrypoint. Shallow glue, and the only caller of load_config.

It reads config.yaml once, then hands the values it holds to the modules as
arguments. No logic lives here. As the modules land, their start-up calls go
below the summary, each taking what it needs from `config`.
"""

import sys
from pathlib import Path

from nightkeep.config import ConfigError, load_config

DEFAULT_CONFIG = Path(__file__).resolve().parent / "config.yaml"


def main(arguments: list[str]) -> int:
    """Read the config and report what Nightkeep is set up to watch."""
    path = Path(arguments[0]) if arguments else DEFAULT_CONFIG

    try:
        config = load_config(path)
    except ConfigError as problem:
        print(f"Nightkeep cannot start. {problem}", file=sys.stderr)
        return 1

    clock = config.clock
    print(f"Nightkeep, seed {config.seed}, config from {path}")
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
