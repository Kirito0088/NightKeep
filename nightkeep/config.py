"""The one loader. It reads config.yaml once and hands back a typed structure.

Nothing else in Nightkeep opens config.yaml. The entrypoint calls load_config
and passes the values it holds into the modules as arguments. A missing,
mistyped or unrecognised key fails here, at start-up, naming the key.
"""

from dataclasses import dataclass
from datetime import time
from pathlib import Path
from typing import Any

import yaml


class ConfigError(Exception):
    """config.yaml is missing a key, has the wrong type, or has a stray key."""


class _Reader:
    """Reads one mapping, remembering the dotted path it sits at.

    Every key taken is struck off. Whatever is left when done() runs was never
    asked for, which means it is a typo, so it raises rather than sits silent.
    """

    def __init__(self, mapping: Any, path: str = "") -> None:
        if not isinstance(mapping, dict):
            raise ConfigError(
                f"{self._describe(path)} must be a block of keys, "
                f"got {type(mapping).__name__}"
            )
        self._mapping = mapping
        self._path = path
        self._taken: set[str] = set()

    @staticmethod
    def _describe(path: str) -> str:
        return path or "the top level of config.yaml"

    def _at(self, key: str) -> str:
        return f"{self._path}.{key}" if self._path else key

    def _take(self, key: str) -> Any:
        if key not in self._mapping:
            raise ConfigError(f"config.yaml is missing {self._at(key)}")
        self._taken.add(key)
        return self._mapping[key]

    def _typed(
        self, key: str, wanted: type | tuple[type, ...], name: str
    ) -> Any:
        value = self._take(key)
        # bool is a subclass of int in Python, so `true` would slip through an
        # isinstance check for a count. A stray `true` where a number belongs is
        # exactly the silent failure this loader exists to stop.
        wants_flag = wanted is bool
        if isinstance(value, bool) is not wants_flag or not isinstance(value, wanted):
            raise ConfigError(
                f"config.yaml: {self._at(key)} must be {name}, "
                f"got {type(value).__name__}"
            )
        return value

    def integer(self, key: str) -> int:
        return self._typed(key, int, "a whole number")

    def number(self, key: str) -> float:
        value = self._typed(key, (int, float), "a number")
        return float(value)

    def text(self, key: str) -> str:
        return self._typed(key, str, "text")

    def flag(self, key: str) -> bool:
        return self._typed(key, bool, "true or false")

    def whole_numbers(self, key: str) -> tuple[int, ...]:
        value = self._take(key)
        if not isinstance(value, list) or any(
            not isinstance(item, int) or isinstance(item, bool) for item in value
        ):
            raise ConfigError(
                f"config.yaml: {self._at(key)} must be a list of whole numbers"
            )
        return tuple(value)

    def texts(self, key: str) -> tuple[str, ...]:
        value = self._take(key)
        if not isinstance(value, list) or any(
            not isinstance(item, str) for item in value
        ):
            raise ConfigError(
                f"config.yaml: {self._at(key)} must be a list of text lines"
            )
        return tuple(value)

    def clock_time(self, key: str) -> time:
        """A 24-hour HH:MM string, turned into a real time of day."""
        value = self.text(key)
        try:
            hours, minutes = (int(part) for part in value.split(":", 1))
            return time(hours, minutes)
        except (ValueError, TypeError) as problem:
            raise ConfigError(
                f"config.yaml: {self._at(key)} must be a 24-hour time "
                f'like "01:30", got "{value}"'
            ) from problem

    def block(self, key: str) -> "_Reader":
        return _Reader(self._take(key), self._at(key))

    def done(self) -> None:
        stray = sorted(set(self._mapping) - self._taken)
        if stray:
            named = ", ".join(self._at(key) for key in stray)
            raise ConfigError(
                f"config.yaml has keys Nightkeep does not know: {named}. "
                "Check the spelling, or add them to nightkeep/config.py."
            )


@dataclass(frozen=True)
class Span:
    """An inclusive low-to-high range the simulator draws from."""

    low: int
    high: int


@dataclass(frozen=True)
class StartWindow:
    """The hours a job may start in. It starts anywhere inside them."""

    earliest: time
    latest: time


@dataclass(frozen=True)
class District:
    """How big the fake district is."""

    ration_cards: int
    fps_count: int
    members_per_card: Span
    transactions_per_card_per_month: Span


@dataclass(frozen=True)
class NightlyExport:
    """Day-end export of transactions for the state server."""

    start_window: StartWindow
    volume_variation: float
    rows_per_run: Span
    network_down_probability: float


@dataclass(frozen=True)
class AllocationGen:
    """Next month's grain quota file for each shop."""

    start_window: StartWindow
    volume_variation: float
    month_start_day: int
    double_run_probability: float
    files_on_month_start: Span
    files_on_a_top_up: Span


@dataclass(frozen=True)
class ArchiveOld:
    """Zips old exports and deletes the originals, once the folder is big."""

    start_window: StartWindow
    volume_variation: float
    size_threshold_kb: int
    files_zipped_per_run: Span


@dataclass(frozen=True)
class DbBackup:
    """The nightly database backup file the Vault pulls."""

    delay_after_export_minutes: Span
    volume_variation: float


@dataclass(frozen=True)
class FixDat:
    """The undocumented script. Renames .tmp to .dat, some nights only."""

    start_window: StartWindow
    volume_variation: float
    run_probability: float


@dataclass(frozen=True)
class OperatorActivity:
    """Clerks editing records in office hours."""

    start_window: StartWindow
    volume_variation: float
    edits_per_day: Span
    skip_sundays: bool


@dataclass(frozen=True)
class Jobs:
    """The six jobs the fake district PDS server runs by itself."""

    nightly_export: NightlyExport
    allocation_gen: AllocationGen
    archive_old: ArchiveOld
    db_backup: DbBackup
    fix_dat: FixDat
    operator_activity: OperatorActivity


@dataclass(frozen=True)
class Clock:
    """The simulated clock: how long a day lasts and how many there are."""

    simulated_day_seconds: int
    day_starts_at: time
    learning_days: int
    guard_days: int


@dataclass(frozen=True)
class HarvestSurge:
    """Peak season. Doubles volumes on chosen days, and must not alarm."""

    days: tuple[int, ...]
    multiplier: float


@dataclass(frozen=True)
class Watcher:
    """How closely the watcher looks, and how long a run's events trail it."""

    poll_seconds: int
    settle_seconds: float


@dataclass(frozen=True)
class Habit:
    """How far from its own habit card a run has to sit to look unusual."""

    mad_multiplier: float
    min_runs_before_scoring: int
    minimum_spread_fraction: float


@dataclass(frozen=True)
class Judge:
    """The tripwires. Fixed, live from minute one, and never widened."""

    odd_score: float
    rename_burst: int
    entropy_jump: float
    entropy_floor: float
    recovery_commands: tuple[str, ...]
    trap_files: tuple[str, ...]


@dataclass(frozen=True)
class Vault:
    """The Vault's own clock and its own judgement. No path to the server."""

    pull_every_simulated_minutes: int
    suspect_entropy: float
    restore_folder_name: str


@dataclass(frozen=True)
class Simulator:
    """The safe simulator: a known key, an echo, and a path it cannot leave."""

    locked_extension: str
    ransom_note_name: str
    key: str
    delay_between_files_seconds: float


@dataclass(frozen=True)
class Config:
    """Every tunable number Nightkeep has, already validated."""

    seed: int
    district: District
    clock: Clock
    harvest_surge: HarvestSurge
    jobs: Jobs
    watcher: Watcher
    habit: Habit
    judge: Judge
    vault: Vault
    simulator: Simulator


def _read_span(reader: _Reader, key: str) -> Span:
    block = reader.block(key)
    span = Span(low=block.integer("low"), high=block.integer("high"))
    block.done()
    if span.high < span.low:
        raise ConfigError(
            f"config.yaml: {key}.high must not be below {key}.low"
        )
    return span


def _read_start_window(reader: _Reader) -> StartWindow:
    block = reader.block("start_window")
    window = StartWindow(
        earliest=block.clock_time("earliest"),
        latest=block.clock_time("latest"),
    )
    block.done()
    return window


def _read_district(reader: _Reader) -> District:
    district = District(
        ration_cards=reader.integer("ration_cards"),
        fps_count=reader.integer("fps_count"),
        members_per_card=_read_span(reader, "members_per_card"),
        transactions_per_card_per_month=_read_span(
            reader, "transactions_per_card_per_month"
        ),
    )
    reader.done()
    return district


def _read_clock(reader: _Reader) -> Clock:
    clock = Clock(
        simulated_day_seconds=reader.integer("simulated_day_seconds"),
        day_starts_at=reader.clock_time("day_starts_at"),
        learning_days=reader.integer("learning_days"),
        guard_days=reader.integer("guard_days"),
    )
    reader.done()
    return clock


def _read_harvest_surge(reader: _Reader) -> HarvestSurge:
    surge = HarvestSurge(
        days=reader.whole_numbers("days"),
        multiplier=reader.number("multiplier"),
    )
    reader.done()
    return surge


def _read_jobs(reader: _Reader) -> Jobs:
    export = reader.block("nightly_export")
    nightly_export = NightlyExport(
        start_window=_read_start_window(export),
        volume_variation=export.number("volume_variation"),
        rows_per_run=_read_span(export, "rows_per_run"),
        network_down_probability=export.number("network_down_probability"),
    )
    export.done()

    allocation = reader.block("allocation_gen")
    allocation_gen = AllocationGen(
        start_window=_read_start_window(allocation),
        volume_variation=allocation.number("volume_variation"),
        month_start_day=allocation.integer("month_start_day"),
        double_run_probability=allocation.number("double_run_probability"),
        files_on_month_start=_read_span(allocation, "files_on_month_start"),
        files_on_a_top_up=_read_span(allocation, "files_on_a_top_up"),
    )
    allocation.done()

    archive = reader.block("archive_old")
    archive_old = ArchiveOld(
        start_window=_read_start_window(archive),
        volume_variation=archive.number("volume_variation"),
        size_threshold_kb=archive.integer("size_threshold_kb"),
        files_zipped_per_run=_read_span(archive, "files_zipped_per_run"),
    )
    archive.done()

    backup = reader.block("db_backup")
    db_backup = DbBackup(
        delay_after_export_minutes=_read_span(
            backup, "delay_after_export_minutes"
        ),
        volume_variation=backup.number("volume_variation"),
    )
    backup.done()

    fix = reader.block("fix_dat")
    fix_dat = FixDat(
        start_window=_read_start_window(fix),
        volume_variation=fix.number("volume_variation"),
        run_probability=fix.number("run_probability"),
    )
    fix.done()

    operator = reader.block("operator_activity")
    operator_activity = OperatorActivity(
        start_window=_read_start_window(operator),
        volume_variation=operator.number("volume_variation"),
        edits_per_day=_read_span(operator, "edits_per_day"),
        skip_sundays=operator.flag("skip_sundays"),
    )
    operator.done()

    reader.done()
    return Jobs(
        nightly_export=nightly_export,
        allocation_gen=allocation_gen,
        archive_old=archive_old,
        db_backup=db_backup,
        fix_dat=fix_dat,
        operator_activity=operator_activity,
    )


def _read_watcher(reader: _Reader) -> Watcher:
    watcher = Watcher(
        poll_seconds=reader.integer("poll_seconds"),
        settle_seconds=reader.number("settle_seconds"),
    )
    reader.done()
    return watcher


def _read_habit(reader: _Reader) -> Habit:
    habit = Habit(
        mad_multiplier=reader.number("mad_multiplier"),
        min_runs_before_scoring=reader.integer("min_runs_before_scoring"),
        minimum_spread_fraction=reader.number("minimum_spread_fraction"),
    )
    reader.done()
    return habit


def _read_judge(reader: _Reader) -> Judge:
    judge = Judge(
        odd_score=reader.number("odd_score"),
        rename_burst=reader.integer("rename_burst"),
        entropy_jump=reader.number("entropy_jump"),
        entropy_floor=reader.number("entropy_floor"),
        recovery_commands=reader.texts("recovery_commands"),
        trap_files=reader.texts("trap_files"),
    )
    reader.done()
    if not judge.trap_files:
        raise ConfigError("config.yaml: judge.trap_files must name at least one trap")
    if not judge.recovery_commands:
        raise ConfigError(
            "config.yaml: judge.recovery_commands must name at least one command"
        )
    return judge


def _read_vault(reader: _Reader) -> Vault:
    vault = Vault(
        pull_every_simulated_minutes=reader.integer("pull_every_simulated_minutes"),
        suspect_entropy=reader.number("suspect_entropy"),
        restore_folder_name=reader.text("restore_folder_name"),
    )
    reader.done()
    return vault


def _read_simulator(reader: _Reader) -> Simulator:
    simulator = Simulator(
        locked_extension=reader.text("locked_extension"),
        ransom_note_name=reader.text("ransom_note_name"),
        key=reader.text("key"),
        delay_between_files_seconds=reader.number("delay_between_files_seconds"),
    )
    reader.done()
    return simulator


def load_config(path: str | Path) -> Config:
    """Read config.yaml and return it as a typed, frozen structure.

    Raises ConfigError, naming the key, if anything is missing, of the wrong
    type, or not recognised.
    """
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as problem:
        raise ConfigError(f"cannot read {path}: {problem}") from problem

    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as problem:
        raise ConfigError(f"{path} is not valid YAML: {problem}") from problem

    top = _Reader(raw)
    config = Config(
        seed=top.integer("seed"),
        district=_read_district(top.block("district")),
        clock=_read_clock(top.block("clock")),
        harvest_surge=_read_harvest_surge(top.block("harvest_surge")),
        jobs=_read_jobs(top.block("jobs")),
        watcher=_read_watcher(top.block("watcher")),
        habit=_read_habit(top.block("habit")),
        judge=_read_judge(top.block("judge")),
        vault=_read_vault(top.block("vault")),
        simulator=_read_simulator(top.block("simulator")),
    )
    top.done()
    return config
