"""The recovery function that undoes the simulator, exactly, with the known key.

CLAUDE.md pairs the simulator with "a matching decrypt script." This is it.
Because the transform is its own inverse, recovery is the same transform run
again with the same key: for every file the simulator left with the locked
extension, this reads it, XORs it back, writes the original name, and removes
the locked copy. It also clears the demo notes and the recovery-blocking
command file, none of which the simulator ever ran.

It is a demo convenience, not the product. Nightkeep's real answer to a
locked machine is the Vault: restore from a clean copy the threat could not
reach. This exists so a run can be reset between rehearsals without
rebuilding the district, and so a judge can see that "known key" is a real
claim and not a figure of speech.

    python -m nightkeep --restore --out-dir demo

It is a pure function, not an entrypoint: the one entrypoint reads config
once and passes the key, the extension and the note name in, the same way
every other module here takes its values as arguments. It refuses to touch
anything outside a real demo district, the same way the simulator does.
"""

from pathlib import Path

from nightkeep.simulator import _COMMAND_FILE, _transform
from nightkeep.simulator._rails import confirm_demo_district


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
