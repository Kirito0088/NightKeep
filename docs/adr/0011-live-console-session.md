# ADR-0011: The console runs a live session, with demo controls and a Night Jobs tab

**Date:** 23 Sept 2026
**Status:** Accepted

## Context

For the Grand Finale and the recorded demo, the whole story has to work from
one command, `python -m nightkeep --console`, with a person clicking through
it by hand. Until now the console only read a finished run: `--demo-run`
(or the Full MVP Demo page, which launched it) had to finish first, and the
console showed its results afterwards. Nothing on screen let a judge pick the
moment of the attack, switch on the harvest surge, or watch Nightkeep learn.

MVP.md section 6, step 4 is the judge's menu: legit surprises (the harvest
surge) and Round 2 threat tests (fast scrambler, impersonator,
recovery-killer), picked live. Section 13's script has habit cards appearing
one by one during learning.

## Decision

**`python -m nightkeep --console` starts a live session beside Flask.**

- **The live engine (`nightkeep/live.py`) plays the district PDS server** in
  its own process, started by the entrypoint with a hidden `--live-engine`
  flag, so `__main__` stays the only config loader. It is glue with the same
  standing as `demo_run.py` and reuses its proven pieces: the watcher agent,
  the launch windows, and the live attack loop. Learning days fold runs into
  Habit; every later day is judged; the Vault pulls after each day. Days
  continue until the session is stopped.
- **The console and the engine share files, not code with state**
  (`nightkeep/live_protocol.py`): `status.json` and `report.json` are
  written only by the engine, and `control.json` only by the console. They
  live in `demo/live/engine/`, outside the district, so neither the
  simulator nor the Judge's read-only lock can reach them.
- **Demo controls sit bottom left on every page, and the harvest surge
  switch sits in the utility strip.** They are the judge's menu, labelled as
  demo controls, not Nightkeep features. The simulated attack unlocks once
  the Vault holds its first clean copy (after day 1), because the tripwires
  are live from minute one (Rule 2). The engine waits for any running night
  job to finish and holds the rest before launching the simulator.
- **After containment the Judge's read-only lock stays on** until the
  supervisor restores through the Restore screen's PIN. Search shows the lock
  screen meanwhile. `demo_run` still releases the lock immediately (the
  `release_lock` switch defaults to its old behaviour).
- **The Full MVP Demo page drives the same session on autopilot**: learn,
  guard, attack with `console.full_demo_variant`, restore, and print the same
  proof lines. With one session behind every screen, the showcase and the
  other screens can never show two different runs.
- **Night Jobs is a new nav tab.** CLAUDE.md fixes the console at seven
  mockup screens. Night Jobs has no artboard; it goes beside Data Safety at
  the team's request, in the nav slot order Ration Card Search, Data Safety,
  Night Jobs, Full MVP Demo. It is the learning-status view MVP.md section 13
  step 2 describes.
- **The office pop-up never waits on OK.** It is shown by its own process, so
  containment, the Vault pull and the rest of the response carry on whether
  or not anyone dismisses it, and it stays on screen after the engine moves on.
- **A-, A, A+ and English / Marathi work.** Both are plain forms that set a
  cookie. Marathi covers chrome and headings only, from one catalogue
  (`console/i18n.py`) that falls back to English. The English disclaimer
  stays on every screen (ADR-0005).

## What this does not change

- Rules 1 and 2: `habit` and `judge` are untouched.
- Rule 3: the jobs are never told where the Vault is. The engine holds the
  Vault object exactly as `demo_run` does; the console's restore uses its
  own Vault instance over the same folder.
- `python -m nightkeep --demo-run` is unchanged and remains the CI proof.
- The engine never reads the ground-truth logs.

## Consequences

- A fresh session learns for about 3.5 minutes at 30 s a day before the
  guard days start. `--day-seconds` shortens it for rehearsals.
- After an attack the night jobs stay stopped; "Start a fresh run" rebuilds
  the district and learns again.
- The restore lands in the Vault's restore folder (F8), not over the damaged
  share. Releasing the lock is what lets the office carry on.
