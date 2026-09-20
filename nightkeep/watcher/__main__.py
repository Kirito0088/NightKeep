"""The Watcher heartbeat worker: a tiny separate process.

Run it as::

    python -m nightkeep.watcher --heartbeat --root <demo folder> \\
        --interval <seconds>

Every interval it rewrites ``<root>/share/.watcher-heartbeat`` with the
current UTC time. The Vault reads that file through the share -- the one
channel the Vault is allowed -- so the Vault can ask "are you alive"
without any connection to the server, and the server never learns the
Vault's address.

It is a separate process on purpose: the watcher-killer simulator variant
terminates exactly this process, which must be possible without killing
whatever launched it. The ``--heartbeat`` flag is the dedicated marker the
killer looks for, together with the demo root.

The Watcher itself ignores this file (see ``_ignored``): heartbeat writes
never become events, habit observations or judge input.
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


def heartbeat_path(root: str | Path) -> Path:
    """Where this worker writes, and where the Vault reads."""
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
        description="NightKeep watcher heartbeat worker (F11)."
    )
    parser.add_argument(
        "--heartbeat",
        action="store_true",
        required=True,
        help="dedicated marker: this process is the heartbeat worker",
    )
    parser.add_argument("--root", required=True, help="demo folder to watch over")
    parser.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="seconds between heartbeat writes",
    )
    args = parser.parse_args(argv)

    if args.interval <= 0:
        print("refused: --interval must be positive", file=sys.stderr)
        return 2

    target = heartbeat_path(args.root)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        while True:
            write_heartbeat(target)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
