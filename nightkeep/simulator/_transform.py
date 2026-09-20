"""The one reversible transform the simulator and its recovery script share.

CLAUDE.md's rail: "uses a known key with a matching decrypt script." The
whole safety of this rests on the transform being its own inverse, so the
recovery script cannot fail to undo it.

A keystream is derived from the key by hashing it with a block counter, and
the file's bytes are XORed against that stream. XOR twice with the same
stream returns the original, exactly, which is why `restore_files.py` needs
nothing but the same key. Applied to a readable CSV, the output is
noise-like and its header no longer matches its extension, which is what the
detection spine is meant to notice. Nothing here is a real cipher, and it is
not trying to be: a real sample would never ship its own key, and that it
does is the point.
"""

import hashlib

_BLOCK = hashlib.sha256().digest_size


def keystream(key: bytes, length: int) -> bytes:
    """`length` bytes derived from `key`, the same every time for a given key."""
    out = bytearray()
    counter = 0
    while len(out) < length:
        out.extend(hashlib.sha256(key + counter.to_bytes(8, "big")).digest())
        counter += 1
    return bytes(out[:length])


def transform(data: bytes, key: bytes) -> bytes:
    """XOR `data` against the key's stream. Its own inverse, by construction."""
    stream = keystream(key, len(data))
    return bytes(byte ^ stream_byte for byte, stream_byte in zip(data, stream))
