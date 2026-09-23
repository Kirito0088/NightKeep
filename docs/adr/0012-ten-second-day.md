# ADR-0012: One simulated day takes 10 s, not 30 s

**Date:** 23 Sept 2026
**Status:** Accepted. Supersedes the 30 s day recorded in ADR-0001 and CLAUDE.md.

## Context

MVP.md F2 says one simulated day takes about 30 s, and ADR-0001 settled on
30 s over SOLUTION_DESIGN's 20 s. At 30 s, the live console (ADR-0011) spends
about 3.5 minutes learning before the guard days, and a full autopilot run
takes over 5 minutes. That is too slow to rehearse, to record and to show
judges live on stage.

The team runs demos at 10 s a day. The live console's manual flow and the
Full MVP Demo on autopilot have both been run end to end at 10 s days:
learning, guard days, attack caught, SUSPECT with the clean pin held, and
5,000 of 5,000 cards restored, with every proof check passing.

## Decision

**`clock.simulated_day_seconds` is 10 everywhere**: the live console,
`--demo-run`, and `--prove-erratic`. The team chose one speed for every
path over a console-only speed, so what is rehearsed is what CI proves.

`--day-seconds` still overrides it for a slower walkthrough.

## What this does not change

- Real-time settings stay real time: the watcher polls every 2 s, beats
  every 10 s, and the Vault calls 30 s of silence S6. None of them is
  measured in simulated days.
- Every simulated moment the truth log records is drawn from the seed, not
  measured (`mock_pds/_clock.py`), so a night reads the same at 10 s as at
  30 s. Only the pacing changes.
- Learning is still 7 days and guarding still 3.

## Consequences

- Learning takes about 70 s, and a full autopilot run about 2 to 3 minutes.
- The simulated attack unlocks about 10 s after a fresh start.
- Jobs get less real time between them. A slow machine that overruns a slot
  pushes the next job later by its seeded run length, which the clock
  already handles.
