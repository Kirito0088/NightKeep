"""The simulated clock for one day. Maps simulated time to real time.

A simulated day runs from day_starts_at on its date until the same time the
next morning, so a shop day and the night that follows it sit in one day.
The whole day takes simulated_day_seconds of real time. The clock only ever
moves forward: waiting for a moment already passed returns at once, with
the simulated time actually reached.
"""

import random
import time as wall
from datetime import date, datetime, time, timedelta

from nightkeep.config import Span, StartWindow
from nightkeep.mock_pds import conventions as c

_DAY = timedelta(days=1)


def date_of_day(day_no: int) -> date:
    """Day 1 is the day after the district was built."""
    return c.SIMULATED_TODAY + timedelta(days=day_no)


class DayClock:
    def __init__(self, day_no: int, day_starts_at: time, seconds_per_day: float) -> None:
        self.date = date_of_day(day_no)
        self.start = datetime.combine(self.date, day_starts_at)
        self.end = self.start + _DAY
        self._seconds_per_day = seconds_per_day
        self._real_start = wall.monotonic()

    @property
    def scale(self) -> float:
        """Simulated seconds that pass per real second."""
        return _DAY.total_seconds() / self._seconds_per_day

    def at(self, time_of_day: time) -> datetime:
        """The moment inside this day that falls at time_of_day.

        Times before day_starts_at belong to the next calendar date, which is
        how a 01:30 job lands in the night after the shop day.
        """
        moment = datetime.combine(self.date, time_of_day)
        return moment if moment >= self.start else moment + _DAY

    def draw_start(self, rng: random.Random, window: StartWindow) -> datetime:
        """A seeded moment, to the second, anywhere inside window tonight."""
        earliest = self.at(window.earliest)
        latest = self.at(window.latest)
        if latest < earliest:
            latest += _DAY
        spread = int((latest - earliest).total_seconds())
        return earliest + timedelta(seconds=rng.randint(0, spread))

    def draw_delay(self, rng: random.Random, minutes: Span) -> timedelta:
        """A seeded gap, to the second, of between minutes.low and .high."""
        return timedelta(seconds=rng.randint(minutes.low * 60, minutes.high * 60))

    def wait_until(self, moment: datetime) -> datetime:
        """Sleep until moment, and return the simulated time now reached.

        That is moment itself, or later if the day is already running behind,
        say because a job overran into the next job's slot.
        """
        offset = (moment - self.start) / _DAY * self._seconds_per_day
        remaining = self._real_start + offset - wall.monotonic()
        if remaining > 0:
            wall.sleep(remaining)
            return moment
        return max(moment, self._now())

    def _now(self) -> datetime:
        elapsed = wall.monotonic() - self._real_start
        return self.start + timedelta(seconds=round(elapsed * self.scale))
