"""The Watcher agent as its own process: it watches and it heartbeats.

Run it as::

    python -m nightkeep.watcher --run --root <folder> \\
        --interval <seconds>

It starts the real Watcher (file observer + process poll + append-only
event log) and rewrites ``<root>/share/.watcher-heartbeat`` every
interval. The Vault reads that file through the share -- the one channel
the Vault is allowed -- so the Vault can ask "are you alive" without any
connection to the server, and the server never learns the Vault's
address.

One process on purpose: this IS the agent. The watcher-killer simulator
variant terminates exactly this process, which must be possible without
killing whatever launched it. The ``--run`` flag is the dedicated marker
the killer looks for, together with the folder root. Killing it stops
both the watching and the heartbeats: that is what "kill the agent"
means, not just silencing a sidecar.

The Watcher itself ignores this file (see ``Watcher._ignored``):
heartbeat writes never become events, habit observations or judge input.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from nightkeep.types import HEARTBEAT_FILENAME
from nightkeep.watcher import Watcher


def heartbeat_path(root: str | Path) -> Path:
    """Where the agent writes, and where the Vault reads."""
    return Path(root) / "share" / HEARTBEAT_FILENAME


def write_heartbeat(path: str | Path) -> None:
    """Stamp the heartbeat file. Atomic: write temp, then rename."""
    path = Path(path)
    payload = {
        "written_at": datetime.now(timezone.utc).isoformat(),
        "pid": os.getpid(),
    }
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(tmp, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="NightKeep watcher agent: watches and heartbeats (F11)."
    )
    parser.add_argument(
        "--run",
        action="store_true",
        required=True,
        help="dedicated marker: this process is the watcher agent",
    )
    parser.add_argument("--root", required=True, help="folder to watch over")
    parser.add_argument(
        "--interval",
        type=float,
        default=10.0,
        help="seconds between heartbeat writes (design-doc S6: 10 [TUNE])",
    )
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=2.0,
        help="seconds between process-writer polls",
    )
    parser.add_argument(
        "--settle-seconds",
        type=float,
        default=1.0,
        help="seconds a run's events may trail its end",
    )
    parser.add_argument(
        "--reconcile-seconds",
        type=float,
        default=None,
        help=(
            "seconds between filesystem reconciliation sweeps, the "
            "deterministic backstop for native file events dropped "
            "under burst load; 0 disables. Default: 0.2 on Windows, "
            "disabled elsewhere."
        ),
    )
    args = parser.parse_args(argv)

    if args.interval <= 0:
        print("refused: --interval must be positive", file=sys.stderr)
        return 2
    if args.reconcile_seconds is not None and args.reconcile_seconds < 0:
        print("refused: --reconcile-seconds must not be negative",
              file=sys.stderr)
        return 2

    target = heartbeat_path(args.root)
    target.parent.mkdir(parents=True, exist_ok=True)
    # The watcher agent is the production/live path that needs the
    # deterministic reconciliation backstop on Windows (ReadDirectoryChangesW
    # can drop native events under ransomware-burst load), so its CLI default
    # explicitly selects 0.2s there and 0.0 elsewhere. --reconcile-seconds
    # overrides either way; this does not rely on Watcher's own default,
    # which is opt-in (disabled).
    reconcile_seconds = (
        args.reconcile_seconds
        if args.reconcile_seconds is not None
        else (0.2 if os.name == "nt" else 0.0)
    )
    watcher = Watcher(
        Path(args.root),
        poll_seconds=args.poll_seconds,
        settle_seconds=args.settle_seconds,
        reconcile_seconds=reconcile_seconds,
    )
    watcher.start()
    try:
        while True:
            write_heartbeat(target)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    finally:
        watcher.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
