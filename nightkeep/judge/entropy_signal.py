"""S3: has an existing file been scrambled in place?

The rule MVP section 10 states, and the reason this module exists at all:

    A file is only suspicious when an **existing** file is rewritten **and**
    entropy jumps **and** its header breaks. A new valid ZIP or JPEG at
    entropy 8.0 stays NORMAL.

All three conditions, never one alone. High entropy by itself is not
evidence of anything: the archive job writes ZIPs every few nights and they
are meant to look like noise. What no legitimate job does is take a file
that was a readable CSV yesterday and leave it unreadable today.

Entropy here is Shannon entropy over the byte histogram, in bits per byte,
so it runs from 0 (every byte identical) to 8 (every byte equally likely).

This module reads file *contents*, which the watcher deliberately does not.
That split is on purpose: the watcher says a file changed, and judge asks
this module what the change looked like.
"""

import json
import math
from collections import Counter
from dataclasses import dataclass

# How much of a file is enough to judge it. Ransomware encrypts from the
# start, and a header that survives the first 64 KB survived the rewrite.
SAMPLE_BYTES = 64 * 1024

# What the first bytes of a healthy file of each kind look like. An extension
# that is not here cannot be checked, and says so rather than guessing.
_MAGIC = {
    ".db": (b"SQLite format 3\x00",),
    ".sqlite": (b"SQLite format 3\x00",),
    ".zip": (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"),
    ".gz": (b"\x1f\x8b",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".pdf": (b"%PDF",),
}

# Kinds we check by parsing rather than by magic bytes, because they have no
# signature: a CSV is only a CSV if it reads as one.
_TEXT_KINDS = frozenset({".csv", ".txt", ".log", ".dat", ".tmp", ".vbs", ".bat"})
_JSON_KINDS = frozenset({".json", ".jsonl"})

UNKNOWN = "unknown"


def entropy(data: bytes) -> float:
    """Shannon entropy of `data` in bits per byte, 0.0 to 8.0.

    An empty file has no information and scores 0.0.
    """
    if not data:
        return 0.0
    counts = Counter(data)
    total = len(data)
    return -sum(
        (count / total) * math.log2(count / total) for count in counts.values()
    )


def header_state(data: bytes, extension: str) -> str:
    """Is this still a healthy file of that kind? "ok", "broken" or "unknown".

    `unknown` is a real answer, not a failure. An extension nobody has a rule
    for cannot be used as evidence in either direction, and saying so keeps
    S3 from firing on a file it does not understand.
    """
    kind = extension.lower()

    if kind in _MAGIC:
        return "ok" if data.startswith(_MAGIC[kind]) else "broken"

    if kind in _JSON_KINDS:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return "broken"
        first = next((line for line in text.splitlines() if line.strip()), "")
        if not first:
            return "ok"
        try:
            json.loads(first)
        except ValueError:
            return "broken"
        return "ok"

    if kind in _TEXT_KINDS:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return "broken"
        # A sample cut mid-character is not a broken file. Anything that
        # decodes but is mostly control bytes is.
        printable = sum(
            1 for character in text if character.isprintable() or character in "\r\n\t"
        )
        if text and printable / len(text) < 0.9:
            return "broken"
        if kind == ".csv":
            first = next((line for line in text.splitlines() if line.strip()), "")
            return "ok" if ("," in first or not first) else "broken"
        return "ok"

    return UNKNOWN


@dataclass(frozen=True)
class Scramble:
    """What S3 saw when it looked at one rewritten file."""

    fired: bool
    reason: str
    entropy_before: float | None
    entropy_after: float
    header: str

    @property
    def jumped(self) -> bool:
        if self.entropy_before is None:
            return False
        return self.entropy_after > self.entropy_before


def inspect(
    data: bytes,
    extension: str,
    *,
    was_existing: bool,
    entropy_before: float | None,
    entropy_jump: float,
    entropy_floor: float,
) -> Scramble:
    """Judge one rewritten file against the three-part rule.

    `extension` is the extension that *means* something, which for a renamed
    file is the one it had before the rename. Ransomware renaming
    `quota.csv` to `quota.csv.locked` has not stopped it from being a CSV,
    and judging it as a `.locked` file would learn nothing.

    `entropy_before` is the last entropy Nightkeep recorded for this path, or
    None if it has never seen it. With a baseline, the rule is the literal
    one: existing, jumped, broken. Without one, a rewritten file whose header
    is now broken and whose content is above the noise floor is still a
    scramble, because the missing piece of evidence is the weakest of the
    three, and demanding it would let a first-night attack through.
    """
    after = entropy(data)
    header = header_state(data, extension)

    if not was_existing:
        return Scramble(
            fired=False,
            reason="a new file, so nothing was overwritten",
            entropy_before=entropy_before,
            entropy_after=after,
            header=header,
        )

    if header != "broken":
        readable = "still reads as a valid file" if header == "ok" else (
            "is a kind Nightkeep has no rule for, so its header proves nothing"
        )
        return Scramble(
            fired=False,
            reason=f"rewritten, but it {readable}",
            entropy_before=entropy_before,
            entropy_after=after,
            header=header,
        )

    if after < entropy_floor:
        return Scramble(
            fired=False,
            reason=(
                f"header no longer valid, but the content is not scrambled "
                f"({after:.1f} of 8.0)"
            ),
            entropy_before=entropy_before,
            entropy_after=after,
            header=header,
        )

    if entropy_before is not None and (after - entropy_before) < entropy_jump:
        return Scramble(
            fired=False,
            reason=(
                f"header no longer valid, but the content was already "
                f"noise-like ({entropy_before:.1f} to {after:.1f} of 8.0)"
            ),
            entropy_before=entropy_before,
            entropy_after=after,
            header=header,
        )

    if entropy_before is None:
        detail = f"and its content is now unreadable noise ({after:.1f} of 8.0)"
    else:
        detail = (
            f"and its content went from readable to noise "
            f"({entropy_before:.1f} to {after:.1f} of 8.0)"
        )
    return Scramble(
        fired=True,
        reason=f"an existing {extension or 'file'} was overwritten {detail}",
        entropy_before=entropy_before,
        entropy_after=after,
        header=header,
    )
