"""Put everything back after a simulator run.

    python -m nightkeep.simulator.decrypt --root <demo dir> \\
        --key "$KEY" --locked-extension .locked \\
        --ransom-note-name HOW_TO_GET_YOUR_FILES_BACK.txt

Decrypts every ``*.locked`` file with the known key, removes the ransom
notes, and cleans the impersonator's staging directory. Takes every value
as an argument (repo rule: only the entrypoint reads configuration).
Refuses to run outside the demo folder, and refuses a wrong key instead
of writing garbage.
"""

from __future__ import annotations

import argparse
import sys

from nightkeep import simulator


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Reverse the Nightkeep ransomware simulator."
    )
    parser.add_argument("--root", required=True, help="demo folder to restore")
    parser.add_argument("--key", required=True, help="known reversible key")
    parser.add_argument("--locked-extension", required=True)
    parser.add_argument("--ransom-note-name", required=True)
    args = parser.parse_args(argv)

    try:
        report = simulator.decrypt_tree(
            args.root,
            key=args.key,
            locked_extension=args.locked_extension,
            ransom_note_name=args.ransom_note_name,
        )
    except (simulator.SimulatorRefused, simulator.DecryptRefused) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2

    print(
        f"restored {report.files_restored} files, "
        f"removed {report.notes_removed} ransom notes"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
