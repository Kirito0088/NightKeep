"""Plain dataclasses shared across the PDS server / Vault boundary.

The only thing allowed to cross that line. Nothing here carries state, holds
a connection or reaches for config. Every one is frozen, so a value handed
across the boundary cannot be edited by whoever received it.

The reason strings live here too, but they are never *built* here. Each is
written inside the module that knows why, in plain language, and the console
renders it without re-deriving anything. That one decision is what keeps the
UI simple.
"""

from dataclasses import dataclass
from datetime import datetime

# --- What the watcher saw -------------------------------------------------

CREATED = "created"
MODIFIED = "modified"
RENAMED = "renamed"
DELETED = "deleted"

EVENT_KINDS = (CREATED, MODIFIED, RENAMED, DELETED)


@dataclass(frozen=True)
class Event:
    """One file change on the PDS server, and who the watcher thinks did it.

    `path` is relative to the watched root, in posix form, so a log written
    on one machine reads the same on another. `process` is the executable
    name, not a full path: the watcher attributes by active writer, and a
    full path would imply a certainty it does not have.
    """

    path: str
    kind: str
    at: datetime
    pid: int | None = None
    process: str | None = None
    old_path: str | None = None
    size: int = 0

    def __post_init__(self) -> None:
        if self.kind not in EVENT_KINDS:
            raise ValueError(
                f"event kind must be one of {EVENT_KINDS}, got {self.kind!r}"
            )


@dataclass(frozen=True)
class JobRun:
    """One execution of one job, start to finish.

    The unit `habit` scores and `judge` judges. `identity` is what makes two
    runs the same job: executable, script path and the script's SHA-256, not
    the filename alone. A vendor silently changing a script produces a new
    identity, which is the point.
    """

    job: str
    identity: str
    started_at: datetime
    finished_at: datetime
    events: tuple[Event, ...] = ()
    # The simulated clock time the run began at. The two clocks answer
    # different questions: `started_at` is when files really changed, which
    # is how events are attributed, and `sim_started_at` is the 02:14 that
    # makes "later than usual" mean anything.
    sim_started_at: datetime | None = None
    day_no: int | None = None

    @property
    def seconds(self) -> float:
        return (self.finished_at - self.started_at).total_seconds()


# --- What habit concluded --------------------------------------------------


@dataclass(frozen=True)
class HabitScore:
    """How far one run sits from its own job's habit card, 0 to 1.

    Learned, and never sufficient on its own to pause anything. That is rule
    one, and `judge` is where it is enforced. The reasons are plain numbers,
    written by `habit`: "wrote 4,812 files, usually 240 give or take 60".
    """

    value: float
    reasons: tuple[str, ...] = ()
    is_first_sighting: bool = False

    def __post_init__(self) -> None:
        if not 0.0 <= self.value <= 1.0:
            raise ValueError(f"habit score must be 0 to 1, got {self.value}")


# --- What judge decided ----------------------------------------------------

NORMAL = "NORMAL"
ODD = "ODD"
SUSPICIOUS = "SUSPICIOUS"
INCIDENT = "INCIDENT"

VERDICT_LEVELS = (NORMAL, ODD, SUSPICIOUS, INCIDENT)


@dataclass(frozen=True)
class Signal:
    """One named check that fired. S1 is learned; S2 to S7 are tripwires."""

    code: str
    title: str
    reason: str
    is_tripwire: bool


@dataclass(frozen=True)
class Verdict:
    """NORMAL, ODD, SUSPICIOUS or INCIDENT, with why and what was done.

    An INCIDENT always carries at least one tripwire signal. Actions are
    reversible by construction: suspend, not kill; read-only, not delete.
    """

    level: str
    reasons: tuple[str, ...] = ()
    actions: tuple[str, ...] = ()
    signals: tuple[Signal, ...] = ()

    def __post_init__(self) -> None:
        if self.level not in VERDICT_LEVELS:
            raise ValueError(
                f"verdict level must be one of {VERDICT_LEVELS}, got {self.level!r}"
            )
        if self.level == INCIDENT and not any(s.is_tripwire for s in self.signals):
            raise ValueError(
                "an INCIDENT needs at least one tripwire signal: the learned "
                "habit score never pauses anything on its own"
            )


# --- What the vault holds --------------------------------------------------

CLEAN = "CLEAN"
SUSPECT = "SUSPECT"

HEALTH_STATES = (CLEAN, SUSPECT)

# The liveness heartbeat the Watcher writes into the shared folder, and the
# only thing the Vault is allowed to read from the server besides backup
# data. A dotfile so it never looks like an export, and a fixed name so
# both sides agree without a conversation (the server never learns the
# Vault's address, and the Vault never writes to the server).
HEARTBEAT_FILENAME = ".watcher-heartbeat"


@dataclass(frozen=True)
class WatcherLiveness:
    """The Vault's S6 answer: has the Watcher checked in recently?

    Kept separate from Snapshot.health on purpose: a silent watcher says
    nothing about whether the *data* is damaged, and a damaged snapshot
    says nothing about whether the watcher is alive. The two are combined
    by the vault's own verdict rule, not by overloading either one.
    """

    alive: bool
    last_seen: datetime | None
    checked_at: datetime
    reason: str


@dataclass(frozen=True)
class Snapshot:
    """One pull: files stored by SHA-256, plus one manifest describing them."""

    snapshot_id: str
    taken_at: datetime
    health: str
    file_count: int
    total_bytes: int
    manifest_hash: str
    previous_manifest_hash: str | None = None
    is_clean_point: bool = False
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.health not in HEALTH_STATES:
            raise ValueError(
                f"snapshot health must be one of {HEALTH_STATES}, got {self.health!r}"
            )
        if self.is_clean_point and self.health != CLEAN:
            raise ValueError("a SUSPECT snapshot can never be a clean point")


@dataclass(frozen=True)
class Check:
    """One verification a restore had to pass, stated as a sentence."""

    statement: str
    passed: bool


@dataclass(frozen=True)
class RestoreResult:
    """The outcome of restoring one snapshot, and the proof it worked.

    Never "trust us": every claim on the screen comes from a check in here,
    and the restore lands in a new folder, so the damaged data is still on
    disk if a check fails.
    """

    ok: bool
    snapshot_id: str
    restored_to: str
    records_verified: int
    records_expected: int
    checks: tuple[Check, ...] = ()
    reasons: tuple[str, ...] = ()

    @property
    def all_records_verified(self) -> bool:
        return self.records_verified == self.records_expected
