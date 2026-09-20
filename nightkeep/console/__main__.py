"""Run the Nightkeep console locally on loopback.

Bound to 127.0.0.1 only. It must not listen on the LAN.
See docs/adr/0002-flask-console.md.

Takes an already-loaded config: this module never reaches for the config
file on its own (see tests/test_config_locality.py). The blessed path is
`python -m nightkeep --console`, where the entrypoint loads the config
once and hands it over. Standalone, `python -m nightkeep.console
--config PATH` loads exactly the path it was given.

With a config, the console reads the real runtime state: the district
database for search and detail, the habit cards for the night tasks, the
vault for safe copies and the restore, and the orchestrator's report for
what the judge decided. Without one it keeps its hardcoded demo values so
it still starts and can be looked at.
"""

import argparse
from pathlib import Path

from nightkeep.config import Config, load_config
from nightkeep.console.app import create_app
from nightkeep.console.providers import (
    alert_presentation,
    build_runtime,
    calm_alert,
    restore_service_for,
    restore_wizard,
    safety_home,
    server_alert,
)


def create_console_app(
    config: Config | None = None,
    district_dir: Path | None = None,
    vault_dir: Path | None = None,
):
    """The console app: real runtime state when given a config, else demo."""
    runtime = None
    if config is not None and district_dir is not None:
        runtime = build_runtime(
            district_dir=Path(district_dir),
            vault_dir=Path(vault_dir) if vault_dir is not None else None,
            config=config,
        )
    if runtime is None:
        return create_app()

    district_figures = runtime.pds.district_figures()

    kwargs: dict = {"pds": runtime.pds}

    if runtime.habit is not None and runtime.vault is not None:
        kwargs["safety_home_data"] = safety_home(
            runtime.habit, runtime.vault, district_figures, runtime.verdicts
        )

    incident = runtime.incident
    if incident is not None and runtime.vault is not None:
        kwargs["alert_data"] = alert_presentation(
            incident, runtime.vault, runtime.pds
        )
    else:
        kwargs["alert_data"] = calm_alert()

    if runtime.vault is not None:
        kwargs["restore_wizard_data"] = restore_wizard(
            runtime.vault, incident, runtime.pds
        )

    kwargs["server_alert_data"] = server_alert(incident)
    kwargs["district_figures"] = district_figures
    kwargs["restore_service"] = restore_service_for(runtime)

    return create_app(**kwargs)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="nightkeep-console")
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help=(
            "path to the Nightkeep config file, to show real runtime "
            "state; without it the console shows demo values"
        ),
    )
    parser.add_argument(
        "--district-dir",
        type=Path,
        default=None,
        help="the district folder from a demo run (with data/district.db)",
    )
    parser.add_argument(
        "--vault-dir",
        type=Path,
        default=None,
        help="the Vault folder from a demo run",
    )
    args = parser.parse_args(argv)
    config = load_config(args.config) if args.config is not None else None
    app = create_console_app(
        config, district_dir=args.district_dir, vault_dir=args.vault_dir
    )
    app.run(host="127.0.0.1", port=5000, debug=False)


if __name__ == "__main__":
    main()
