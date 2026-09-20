"""The recovery script that undoes the simulator, exactly, with the known key.

CLAUDE.md pairs the simulator with "a matching decrypt script." This is it.
Because the transform is its own inverse, recovery is the same transform run
again with the same key: for every file the simulator left with the locked
extension, this reads it, XORs it back, writes the original name, and removes
the locked copy. It also clears the ransom notes and the recovery-blocking
command file, none of which the simulator ever ran.

It is a demo convenience, not the product. Nightkeep's real answer to a
locked machine is the Vault: restore from a clean copy the threat could not
reach. This script exists so a run can be reset between rehearsals without
rebuilding the district, and so a judge can see that "known key" is a real
claim and not a figure of speech.

    python -m nightkeep.simulator.restore_files --root demo

Refuses to touch anything outside a real demo district, the same way the
simulator does.
"""

import argparse
from pathlib import Path

from nightkeep.config import load_config
from nightkeep.simulator import _COMMAND_FILE, _transform
from nightkeep.simulator._rails import confirm_demo_district

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config.yaml"


def restore(root: Path, key: bytes, locked_extension: str, note_name: str) -> int:
    """Put every locked file back and clear what the simulator dropped.

    Returns the number of files restored. Raises UnsafeRootError, through
    `confirm_demo_district`, before touching anything if `root` is not a
    district mock_pds built.
    """
    safe_root = confirm_demo_district(root)
    restored = 0

    for locked in sorted(safe_root.rglob(f"*{locked_extension}")):
        if not locked.is_file():
            continue
        original = locked.with_name(locked.name[: -len(locked_extension)])
        original.write_bytes(_transform.transform(locked.read_bytes(), key))
        locked.unlink()
        restored += 1

    for note in safe_root.rglob(note_name):
        note.unlink()

    command_file = safe_root / _COMMAND_FILE
    if command_file.exists():
        command_file.unlink()

    return restored


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nightkeep.simulator.restore_files")
    parser.add_argument("--root", type=Path, required=True, help="the demo district")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args(arguments)

    simulator = load_config(args.config).simulator
    count = restore(
        args.root,
        key=simulator.key.encode("utf-8"),
        locked_extension=simulator.locked_extension,
        note_name=simulator.ransom_note_name,
    )
    print(f"Restored {count} files under {args.root}. The district is back.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
