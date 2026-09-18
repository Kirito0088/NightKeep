"""Deterministic simulated clock for Nightkeep.

Decoupled from wall-clock time. Advances only when explicitly stepped.
Allows tests and simulation runs to step time without sleeping.
"""

from datetime import date, datetime, time, timedelta


class SimulatedClock:
    """A controllable, deterministic clock for the PDS server simulation."""

    def __init__(self, current_time: datetime) -> None:
        self._current_time = current_time

    @classmethod
    def from_date(
        cls, start_date: date, start_time: time = time(0, 0, 0)
    ) -> "SimulatedClock":
        return cls(datetime.combine(start_date, start_time))

    @property
    def current_time(self) -> datetime:
        return self._current_time

    def now(self) -> datetime:
        return self._current_time

    def advance(self, duration: timedelta) -> datetime:
        if duration < timedelta(0):
            raise ValueError("Simulation time cannot move backward")
        self._current_time += duration
        return self._current_time

    def advance_to(self, target: datetime) -> datetime:
        if target < self._current_time:
            raise ValueError("Target time cannot be earlier than current simulation time")
        self._current_time = target
        return self._current_time

    def set_time(self, new_time: datetime) -> None:
        self._current_time = new_time
