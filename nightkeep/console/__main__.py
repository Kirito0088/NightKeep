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
what the judge decided. Without one it shows sample records for browsing
and calm, honest screens: no fabricated incident, ever.
"""

import argparse
from pathlib import Path

from nightkeep.config import Config, load_config
from nightkeep.console.app import create_app
from nightkeep.console.providers import build_runtime, presentation_for
from nightkeep.console.showcase import LiveShowcase, ShowcaseController


def create_console_app(
    config: Config | None = None,
    district_dir: Path | None = None,
    vault_dir: Path | None = None,
    session=None,
):
    """The console app: real runtime state when given a config, else demo.

    With a live session (console/session.py), the district, Vault and
    report all come from the session's folder, every page carries the demo
    controls, and nothing is bound at startup: the session wipes and
    rebuilds its folder, so every request reads it fresh.

    The showcase controller is always attached: the one-click demo does
    not need a wired console to run. The runtime factory lets the
    safety/alert/restore/locked/server-alert screens and the IT view
    rebuild their presentation from fresh on-disk state per request, so
    a demo launched from the showcase becomes visible without
    restarting the console. The factory is installed even when the
    demo output does not exist yet: then build_runtime returns None and
    the routes keep their calm, honest defaults until the demo creates
    the runtime.
    """
    report_path = None
    if session is not None:
        # The live session owns where the district, the Vault and the
        # report live; every screen reads that one run.
        district_dir = session.paths.district
        vault_dir = session.paths.vault
        report_path = session.paths.report
    if session is not None and config is not None:
        # The Live Demo page's guided demo drives the same live session, on autopilot.
        controller = LiveShowcase(session, config.console.full_demo_variant)
    else:
        controller = ShowcaseController()
    live_kwargs = {
        "session": session,
        "console_settings": config.console if config is not None else None,
    }

    runtime_factory = None
    if config is not None and district_dir is not None:
        district_path = Path(district_dir)
        vault_path = Path(vault_dir) if vault_dir is not None else None

        def runtime_factory():
            return build_runtime(
                district_dir=district_path,
                vault_dir=vault_path,
                config=config,
                report_path=report_path,
            )

    if runtime_factory is None:
        return create_app(showcase_controller=controller, **live_kwargs)

    # Install the factory even when the runtime is not there yet. Each
    # request rebuilds from disk, so a demo launched from /showcase shows
    # up on every screen without restarting the console. Before the demo
    # exists, build_runtime returns None and refreshed_pool falls back
    # to the bound calm defaults.
    runtime = None if session is not None else runtime_factory()
    if runtime is not None:
        return create_app(
            showcase_controller=controller,
            runtime_factory=runtime_factory,
            **live_kwargs,
            **presentation_for(runtime),
        )
    return create_app(
        showcase_controller=controller,
        runtime_factory=runtime_factory,
        **live_kwargs,
    )


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
