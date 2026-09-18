"""Turns a job run and its events into a verdict, and acts reversibly.

Public interface:
    verdict(run, events) -> Verdict

Hides all six signals, the verdict table, suspend/read-only actions and their
undo. Signals S2 to S7 are tripwires: hard-coded, live from minute one, never
learned.
"""
