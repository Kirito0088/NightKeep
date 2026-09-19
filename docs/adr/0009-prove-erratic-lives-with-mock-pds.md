# ADR-0009: The erratic-week proof lives inside mock_pds

**Date:** 20 Sept 2026
**Status:** Accepted

## Context

Ticket #5 asks for proof, before the Watcher exists, that the six nightly
jobs really are erratic: seven simulated days run end to end from one seed,
and a summary of what each job actually did, read from the ground-truth logs.

Two rules in CLAUDE.md pull against each other here.

- "Nothing outside `mock_pds/` and `tests/` may read `logs/_truth/`." The
  summary's numbers can only come from those logs, so the code that reads
  them has to sit inside `mock_pds/`.
- The module table gives `mock_pds` exactly two public functions,
  `build_district` and `run_day`, and says to stop and say why before
  widening that. A third and fourth public name inside the package looks
  like exactly that widening.

## Decision

**`nightkeep/mock_pds/prove_erratic.py` is a script, not a third entry in
the module table.** It offers `prove(...)` and `render(summary)`, and the
entrypoint is its only caller, through `python -m nightkeep --prove-erratic`.

- No Nightkeep module imports it. `watcher`, `habit`, `judge`, `vault` and
  `console` still see `mock_pds` as two functions, which is what the table
  is protecting.
- It takes its values as arguments like every other module here: seed,
  district, clock, jobs, harvest surge, out_dir. It never opens
  `config.yaml`. The entrypoint reads config once and hands the values in,
  which is why the command-line surface sits in `__main__.py` rather than in
  the script.
- It calls the two public functions to live the week. It reaches for no
  internals of `_day`, `_clock` or `_generate`.
- It reads `logs/_truth/*.jsonl` and nothing else. The summary is not
  allowed to re-derive a number from the database, because a proof that
  checked the scheduler against itself would prove nothing.

`nightly_export` now records a `rows` count on its own ground-truth line, so
the export's volume swing comes from the job's own account of what it
carried rather than from file size standing in for it. That makes the export
truth line one field wider than the other five jobs', which is accepted: it
is the export that has a row count, and only it.

## Consequences

- The deliverable is one command, and the seven days run with no manual step
  in between.
- A future ticket that wants the guard days, or a longer run, extends this
  script rather than adding a public function to `mock_pds`.
- The rail in `tests/test_config_locality.py` still holds: `config.py` is
  the one loader and `__main__.py` is the one caller of it.
- Start times are the one thing a re-run does not reproduce exactly. A job
  that overruns its slot pushes the next one's real start later, and by how
  much depends on the machine, so `_clock.wait_until` hands back the time
  actually reached. Everything the seed decides does reproduce, and the
  test asserts that; the summary reports start times as observed.
