"""What each job normally does, learned over the 7 learning days.

Public interface:
    Habit(database, mad_multiplier, min_runs_before_scoring,
          minimum_spread_fraction)
    score(run) -> HabitScore
    learn(run)

Hides feature extraction, median/MAD ranges, novelty flags, card versions and
SQLite storage. The score it returns never pauses anything on its own.

**Rule 1 lives here.** Nothing in this module imports psutil, opens a file
for writing outside its own database, or changes a permission. It computes a
number and writes sentences explaining it. What that number is allowed to
cause is `judge`'s decision, and `judge` may never act on it alone.

Why median and MAD rather than mean and standard deviation: a single harvest
surge night doubles the volumes, and a mean would drag the whole card toward
the surge. The median does not move, so the surge reads as one unusual night
rather than quietly becoming the new normal.
"""

from datetime import datetime
from pathlib import Path
from statistics import median

from nightkeep.habit._features import (
    FEATURE_WORDS,
    NUMERIC_FEATURES,
    circular_distance,
    clock_of,
    extract,
)
from nightkeep.habit._store import Store
from nightkeep.types import HabitScore, JobRun

DATABASE_NAME = "habit.db"


def _mad(values: list[float], centre: float, feature: str) -> float:
    """Median absolute deviation: the robust cousin of standard deviation."""
    if feature == "start_minute":
        deviations = [circular_distance(value, centre) for value in values]
    else:
        deviations = [abs(value - centre) for value in values]
    return median(deviations)


class Habit:
    """The habit cards, and the score one run gets against its own."""

    def __init__(
        self,
        database: Path,
        mad_multiplier: float,
        min_runs_before_scoring: int,
        minimum_spread_fraction: float,
    ) -> None:
        self._store = Store(Path(database))
        self._mad_multiplier = mad_multiplier
        self._min_runs = min_runs_before_scoring
        self._minimum_spread_fraction = minimum_spread_fraction

    # --- the public interface --------------------------------------------

    def learn(self, run: JobRun) -> None:
        """Fold one run into its job's habit card.

        Called on the 7 learning days. Learning never widens a canary signal: this
        writes to the habit database and nothing else, and `judge` reads its
        canary-signal thresholds from config, never from here. That is rule 2.
        """
        features = extract(run)
        version = self._store.version_for(run.job, run.identity, run.started_at)
        self._store.add_run(
            job=run.job,
            identity=run.identity,
            version=version.version,
            day_no=run.day_no,
            observed_at=run.started_at,
            numbers=features.numbers,
        )
        self._store.remember_extensions(run.job, features.extensions)

    def score(self, run: JobRun) -> HabitScore:
        """How far this run sits from its own habit card, 0 to 1.

        The value is the share of a job's known features that fell outside
        their usual range. The reasons are plain numbers, one sentence each,
        and the console prints them without re-deriving anything.
        """
        features = extract(run)
        version = self._store.version_for(run.job, run.identity, run.started_at)

        if version.is_new:
            return HabitScore(
                value=1.0,
                reasons=(
                    f"the program behind {run.job} changed since it was last "
                    f"seen, so what it used to do no longer describes it",
                ),
                is_first_sighting=True,
            )

        observations = self._store.observations(run.job, version.version)
        if len(observations) < self._min_runs:
            return HabitScore(
                value=0.0,
                reasons=(
                    f"{run.job} has only been seen {len(observations)} "
                    f"time{'' if len(observations) == 1 else 's'}, which is "
                    f"not yet enough to say what is usual for it",
                ),
                is_first_sighting=True,
            )

        unusual: list[str] = []
        considered = 0
        for feature in NUMERIC_FEATURES:
            history = [
                observation[feature]
                for observation in observations
                if feature in observation
            ]
            if not history:
                continue
            value = features.numbers[feature]
            if not any(history) and value == 0:
                # A job that has never renamed a file, and did not rename one
                # tonight, has told us nothing. Counting that as evidence of
                # normality would let three silent features outvote the one
                # that is screaming, which is exactly how an attack scores
                # below the line. A job that has never renamed and tonight
                # renamed four thousand files is counted, and loudly.
                continue
            considered += 1
            reason = self._judge_feature(feature, value, history)
            if reason is not None:
                unusual.append(reason)

        novel = features.extensions - self._store.seen_extensions(run.job)
        if novel:
            considered += 1
            listed = ", ".join(sorted(novel))
            unusual.append(
                f"produced file types this job has never produced before "
                f"({listed})"
            )

        if considered == 0:
            return HabitScore(value=0.0, reasons=("nothing to compare against yet",))

        value = len(unusual) / considered
        if not unusual:
            unusual = [f"everything {run.job} did was within its usual range"]
        return HabitScore(value=round(value, 3), reasons=tuple(unusual))

    # --- internals --------------------------------------------------------

    def _judge_feature(
        self, feature: str, value: float, history: list[float]
    ) -> str | None:
        """One feature, judged against its own median. Returns why, or None."""
        centre = median(history)
        spread = self._spread(feature, history, centre)
        distance = (
            circular_distance(value, centre)
            if feature == "start_minute"
            else abs(value - centre)
        )
        if distance <= spread:
            return None

        if feature == "start_minute":
            return (
                f"started at {clock_of(value)}, usually around "
                f"{clock_of(centre)}"
            )
        did = FEATURE_WORDS[feature].format(value=value)
        return f"{did}, usually {centre:,.0f} give or take {spread:,.0f}"

    def _spread(self, feature: str, history: list[float], centre: float) -> float:
        """How far from the median still counts as usual.

        A job that never varies has a MAD of zero, which would make every
        run infinitely unusual and every night an alarm. The floor under the
        spread is what stops that.
        """
        spread = _mad(history, centre, feature) * self._mad_multiplier
        floor = abs(centre) * self._minimum_spread_fraction
        if feature == "start_minute":
            # Minutes, not a fraction of a clock reading: 10% of "02:00" is
            # a meaningless number.
            floor = 60.0 * self._minimum_spread_fraction * 10
        return max(spread, floor)

    # --- what the console asks for ----------------------------------------

    def cards(self) -> dict[str, dict[str, tuple[float, float]]]:
        """Every job's current card, as feature -> (median, spread).

        Read-only. The console shows this beside the ground truth so a judge
        can see that learning was correct, which is F10b.
        """
        summary: dict[str, dict[str, tuple[float, float]]] = {}
        for job in self._store.jobs():
            version = self._store.current_version(job)
            if version is None:
                continue
            observations = self._store.observations(job, version)
            if len(observations) < self._min_runs:
                continue
            card: dict[str, tuple[float, float]] = {}
            for feature in NUMERIC_FEATURES:
                history = [o[feature] for o in observations if feature in o]
                if not history:
                    continue
                centre = median(history)
                card[feature] = (centre, self._spread(feature, history, centre))
            summary[job] = card
        return summary

    def seen_extensions(self) -> frozenset[str]:
        """Every extension any job on this machine has ever produced.

        `judge` asks this for S4. It is a fact about what has been observed,
        not a threshold, so reading it can never widen a canary signal.
        """
        return self._store.seen_extensions()

    def run_count(self, job: str) -> int:
        version = self._store.current_version(job)
        return 0 if version is None else self._store.run_count(job, version)


def open_habit(
    root: Path,
    mad_multiplier: float,
    min_runs_before_scoring: int,
    minimum_spread_fraction: float,
) -> Habit:
    """Open the habit database that belongs to one district folder."""
    return Habit(
        database=Path(root) / "data" / DATABASE_NAME,
        mad_multiplier=mad_multiplier,
        min_runs_before_scoring=min_runs_before_scoring,
        minimum_spread_fraction=minimum_spread_fraction,
    )


__all__ = ["Habit", "open_habit", "DATABASE_NAME"]
