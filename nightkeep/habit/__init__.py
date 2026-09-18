"""What each job normally does, learned over the 7 learning days.

Public interface:
    score(run) -> HabitScore
    learn(run)

Hides feature extraction, median/MAD ranges, novelty flags, card versions and
SQLite storage. The score it returns never pauses anything on its own.
"""
