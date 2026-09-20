"""Content-addressed blob store.

Every file the Vault pulls is saved once, under its SHA-256 hex digest, and
locked read-only the moment it lands. Identical files across pulls share one
blob. The store never learns filenames: names live in the manifests.
"""

import hashlib
from pathlib import Path

BLOBS_DIR = "blobs"


def _blobs_dir(root: Path) -> Path:
    path = root / BLOBS_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_locked(path: Path, data: bytes) -> None:
    """Write bytes, then take away every write bit.

    The Vault's own process can still replace a file by chmodding it back,
    which is exactly what a locked clean point needs on the next CLEAN pull.
    Anything else on the machine, including ransomware that somehow reached
    the Vault, meets read-only files.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    path.chmod(0o444)


def store_blob(root: Path, data: bytes) -> str:
    """Store data under its SHA-256 digest. Returns the digest.

    Storing the same bytes twice keeps the first copy untouched.
    """
    digest = hashlib.sha256(data).hexdigest()
    path = _blobs_dir(root) / digest
    if not path.exists():
        write_locked(path, data)
    return digest


def read_blob(root: Path, digest: str) -> bytes:
    """Read a blob back by digest. Raises FileNotFoundError if it is gone."""
    return (_blobs_dir(root) / digest).read_bytes()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
