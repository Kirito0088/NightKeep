"""Turns a job run and its events into a verdict, and acts reversibly.

Public interface:
    Judge(root, habit, odd_score, rename_burst, entropy_jump, entropy_floor,
          recovery_commands, trap_files)
    verdict(run, events) -> Verdict
    undo()

Hides all the signals, the verdict table, suspend/read-only actions and
their undo. Signals S2 to S5 are tripwires: hard-coded, live from minute
one, never learned.

**Rule 1 is enforced here**, in one place and one place only: the level
INCIDENT is unreachable unless a tripwire fired. `Verdict` refuses to be
built otherwise, so even a future bug in this table cannot pause a process
on a habit score alone.

**Rule 2 is enforced by `_signals.py` having no route to a habit card.**
Every threshold it uses arrives as an argument from config. The one thing it
reads from `habit` is the set of extensions that have ever been seen, which
is an observation rather than a threshold: it can make S4 fire on more
things, never fewer.
"""

from collections import Counter
from pathlib import Path

from nightkeep.habit import Habit
from nightkeep.judge import _actions, _signals
from nightkeep.judge._baseline import DATABASE_NAME, Baseline
from nightkeep.types import (
    INCIDENT,
    NORMAL,
    ODD,
    SUSPICIOUS,
    Event,
    HabitScore,
    JobRun,
    Signal,
    Verdict,
)

# The only processes that could be carrying a recovery-killing command: a
# shell, a script host, or one of the tools itself. Anything else running
# `vssadmin delete shadows` had to start one of these to do it.
_SHELLS_AND_RECOVERY_TOOLS = frozenset({
    "cmd.exe", "powershell.exe", "pwsh.exe", "wscript.exe", "cscript.exe",
    "vssadmin.exe", "wbadmin.exe", "bcdedit.exe", "diskshadow.exe",
    "sh", "bash", "zsh",
})

TRAP_CONTENTS = (
    b"transaction_id,card_no,fps_id,occurred_at,allotment_month,"
    b"commodity,quantity_kg,auth_mode,status\n"
)


class Judge:
    """The verdict table, and the only thing allowed to act on it."""

    def __init__(
        self,
        root: Path,
        habit: Habit,
        odd_score: float,
        rename_burst: int,
        entropy_jump: float,
        entropy_floor: float,
        recovery_commands: tuple[str, ...],
        trap_files: tuple[str, ...],
    ) -> None:
        self.root = Path(root).resolve()
        self._habit = habit
        self._odd_score = odd_score
        self._rename_burst = rename_burst
        self._entropy_jump = entropy_jump
        self._entropy_floor = entropy_floor
        self._recovery_commands = recovery_commands
        self._trap_files = trap_files
        self._baseline = Baseline(self.root / "data" / DATABASE_NAME)
        self._taken = _actions.Taken()
        self._history: list[tuple[JobRun, Verdict]] = []

    # --- setup -------------------------------------------------------------

    def plant_traps(self) -> list[Path]:
        """Put the decoys in place. Part of setting the Judge up, not of judging.

        A trap has to look like a real export or nothing would bother
        encrypting it, and it has to be a file no job will ever open, or it
        would fire on its own. The names in config sit in the export and
        allocation folders alongside the real ones, dated far enough in the
        past that no job's date arithmetic reaches them.
        """
        planted = []
        for relative in self._trap_files:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_bytes(TRAP_CONTENTS)
            planted.append(path)
        return planted

    # --- the public interface ---------------------------------------------

    def verdict(self, run: JobRun, events: list[Event] | None = None) -> Verdict:
        """Judge one run. The only place a level is decided."""
        events = list(events if events is not None else run.events)
        habit_score = self._habit.score(run)

        signals, readings = self._fire_signals(events)
        tripwires = tuple(signal for signal in signals if signal.is_tripwire)
        codes = {signal.code for signal in tripwires}

        level = self._level(codes, habit_score)
        verdict = self._act(run, events, level, signals, habit_score)

        if level in (NORMAL, ODD):
            # Only a quiet night updates what "normal" looks like. Folding an
            # incident back in would teach Nightkeep that scrambled is fine.
            self._baseline.remember_many(
                [(reading.path, reading.entropy) for reading in readings],
                run.started_at,
            )

        self._history.append((run, verdict))
        return verdict

    def undo(self) -> list[str]:
        """Resume what was paused and unlock what was locked."""
        return _actions.undo(self._taken)

    def history(self) -> list[tuple[JobRun, Verdict]]:
        """Every verdict so far, oldest first. The console's verdict feed."""
        return list(self._history)

    # --- the verdict table (MVP section 10) --------------------------------

    def _level(self, codes: set[str], habit_score: HabitScore) -> str:
        unusual = habit_score.value >= self._odd_score

        if not codes:
            return ODD if unusual else NORMAL

        # A trap file is unambiguous. Nothing legitimate touches it, so this
        # needs no corroboration from a habit card.
        if "S2" in codes:
            return INCIDENT

        # Scrambling or mass-renaming, on a night that also looks unlike the
        # job's own habit. Either one alone is worth an alert, not a pause.
        if codes & {"S3", "S4"} and unusual:
            return INCIDENT

        # Recovery-killing text is what ransomware does on its way out. On
        # its own it is suspicious; alongside any other ransom signal it is
        # the end of the argument.
        if "S5" in codes and codes & {"S2", "S3", "S4"}:
            return INCIDENT

        return SUSPICIOUS

    # --- firing the signals -------------------------------------------------

    def _fire_signals(
        self, events: list[Event]
    ) -> tuple[list[Signal], list[_signals.Reading]]:
        signals: list[Signal] = []

        trap = _signals.trap_touched(events, self._trap_files)
        if trap:
            signals.append(trap)

        scramble, readings = _signals.scrambled_in_place(
            events, self.root, self._baseline,
            self._entropy_jump, self._entropy_floor,
        )
        if scramble:
            signals.append(scramble)

        renames = _signals.mass_rename(
            events, self._habit.seen_extensions(), self._rename_burst
        )
        if renames:
            signals.append(renames)

        killer = _signals.recovery_killer(
            events, self.root, self._recovery_commands, self._running_command_lines()
        )
        if killer:
            signals.append(killer)

        return signals, readings

    def _running_command_lines(self) -> tuple[str, ...]:
        """What is running right now, for S5. Read-only, and best effort.

        Only the processes that could actually carry one of these commands:
        a shell, a script host, or the recovery tools themselves. Reading
        every process's command line on every verdict costs half a second
        each time and finds nothing the rest of the year.
        """
        import psutil

        lines = []
        for process in psutil.process_iter(["name", "cmdline"]):
            try:
                name = (process.info["name"] or "").lower()
                if name not in _SHELLS_AND_RECOVERY_TOOLS:
                    continue
                cmdline = process.info["cmdline"] or ()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            if cmdline:
                lines.append(" ".join(str(part) for part in cmdline))
        return tuple(lines)

    # --- acting -------------------------------------------------------------

    def _act(
        self,
        run: JobRun,
        events: list[Event],
        level: str,
        signals: tuple[Signal, ...] | list[Signal],
        habit_score: HabitScore,
    ) -> Verdict:
        signals = tuple(signals)
        reasons = tuple(signal.reason for signal in signals) + habit_score.reasons
        actions: list[str] = []

        if level == INCIDENT:
            taken = self._taken
            pid = self._busiest_pid(events)
            if pid is not None:
                _actions.suspend_process(pid, taken)
            _actions.make_read_only(self.root / "data", taken)
            _actions.make_read_only(self.root / "share", taken)
            actions = list(taken.descriptions)
            if not actions:
                actions = ["the program had already finished, so nothing was left to pause"]
        elif level == SUSPICIOUS:
            # Judge does not reach across to the Vault. The Vault notices on
            # its own, from its own health check, which is the whole point of
            # two independent witnesses.
            actions = ["raised an alert on the office computer"]
        elif level == ODD:
            actions = ["noted it for review. Nothing was blocked"]
        else:
            actions = ["logged it"]

        return Verdict(
            level=level,
            reasons=reasons,
            actions=tuple(actions),
            signals=signals,
        )

    @staticmethod
    def _busiest_pid(events: list[Event]) -> int | None:
        """The process behind most of these changes, if the watcher knew one."""
        counted = Counter(event.pid for event in events if event.pid is not None)
        if not counted:
            return None
        return counted.most_common(1)[0][0]


__all__ = ["Judge"]
