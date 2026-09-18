"""The fake district PDS server: data, jobs, clock, hidden ground truth.

Public interface:
    build_district(seed)
    run_day(day_no)

Hides 5,000 ration cards, 6 erratic jobs, their randomness, the simulated
clock and the hidden truth log. Nothing outside this package and tests/ may
read logs/_truth/.
"""
