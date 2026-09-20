"""One JSON manifest per snapshot.

The manifest is the snapshot's table of contents: which paths were pulled,
where each one's bytes live in the blob store, and what the health check
saw. It is written in canonical form (sorted keys, no whitespace) so its
SHA-256 is stable, and it carries the previous manifest's hash, chaining the
history together: silently editing an old manifest breaks the chain.
"""

import json
from pathlib import Path

from nightkeep.vault import _store

MANIFESTS_DIR = "manifests"


def _manifests_dir(root: Path) -> Path:
    path = root / MANIFESTS_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def manifest_path(root: Path, snapshot_id: str) -> Path:
    return _manifests_dir(root) / f"{snapshot_id}.json"


def canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def write_manifest(root: Path, payload: dict) -> str:
    """Write the manifest locked read-only. Returns its SHA-256 hex digest."""
    data = canonical(payload)
    _store.write_locked(manifest_path(root, payload["snapshot_id"]), data)
    return _store.sha256_hex(data)


def read_manifest(root: Path, snapshot_id: str) -> dict:
    """Read a manifest back. Raises FileNotFoundError for an unknown id."""
    return json.loads(manifest_path(root, snapshot_id).read_text(encoding="utf-8"))


def manifest_ids(root: Path) -> list[str]:
    """Every snapshot id on disk, oldest first (ids sort lexicographically)."""
    return sorted(path.stem for path in _manifests_dir(root).glob("*.json"))
