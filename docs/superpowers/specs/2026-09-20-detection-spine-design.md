# Nightkeep detection spine: design

**Date:** 20 September 2026
**Status:** approved, in build
**Scope:** MVP features F3, F4, F5, F6, F7, F8, F10, and wiring F9 to real data

---

## Why this exists

As of 20 September the repository proved F1, F2 and F10b: a believable fake
district, six erratic jobs, a simulated clock and hidden ground-truth logs,
all under 156 passing tests. Everything between the jobs and the screens was
a docstring. `watcher`, `habit`, `judge`, `vault` and `simulator` held no
code, `types.py` held no types, and the console's seven screens rendered
hard-coded constants.

Round 2 is 22 September. This design is the spine that makes the tagline
true: learns the chaos, catches the crime.

## Two corrections to the stated ground truth

1. `judge/entropy_signal.py` never existed. CLAUDE.md described it as
   pre-existing with ten passing tests and forbade rewriting it. There is
   nothing to preserve, so it is built fresh here, with its own tests, and
   that line in CLAUDE.md is corrected.
2. The three rules had no tests, because the modules they police had no
   code. They land here: rules 1 and 2 with `habit` and `judge`, rule 3
   with `vault`.

## Approach

Three shapes were considered.

**Replay a recorded run.** Fastest to build. Rejected: it kills the judges'
"pick a seed, add a job live" challenge, which is the entire point of F10b.

**Separate processes over real SMB.** Matches F7 literally. Rejected: SMB
setup on Windows is where a two-day schedule dies.

**One machine, real processes, a local read-only folder standing in for the
SMB share.** Chosen. The jobs already run as real subprocesses through
`_day.launch()`, so `psutil` attribution is genuine rather than simulated.
The Vault reads `demo/share/` and never writes to it. The PDS side holds no
vault path, which is what rule 3 actually asserts. Two-laptop SMB stays
F17/P1, where MVP already puts it.

## Modules

| Module | Public interface | What it hides |
|---|---|---|
| `types.py` | `Event`, `JobRun`, `HabitScore`, `Verdict`, `RestoreResult`, `Snapshot` | nothing; plain dataclasses, no state, no config |
| `watcher` | `events_since(t)`, `is_alive()` | watchdog observer, psutil poll, file-to-process attribution, append-only log |
| `habit` | `score(run)`, `learn(run)` | feature extraction, median/MAD ranges, novelty flags, card versions, SQLite |
| `judge` | `verdict(run, events)` | six signals, the verdict table, suspend and read-only actions and their undo |
| `vault` | `pull()`, `snapshots()`, `restore(id)` | SMB-stand-in read, content-addressed blobs, manifests, hash chain, health check, clean points, verification |
| `simulator` | three variants plus `decrypt.py` | the path check, the known key, the echoed recovery commands |
| `console` | Flask routes only | rendering |

### watcher

Watchdog observes `demo/`. A psutil poll every two seconds records which
process is writing. Attribution is "active writer in window", which is the
fallback MVP section 14 already names, and is sound here because the
scheduler runs jobs one at a time. Events append to `demo/logs/watcher.jsonl`,
which is append-only and never rewritten.

### habit

Per job identity (executable + script path + SHA-256 of the script), the
card holds start minute, files created, modified, renamed and deleted,
distinct folders, bytes written and extensions. Each feature keeps a median
and a MAD across the learning days. The score is the share of features
sitting outside median plus or minus k times MAD, clamped to 0 to 1, and it
carries its reasons in plain numbers. Cards are versioned, because
legitimate jobs change.

**Rule 1:** the score never pauses, locks or deletes anything on its own.

### judge

Signals: S1 unusual job, learned, from the habit score. S2 trap file
changed. S3 in-place rewrite with an entropy jump and a broken header. S4
ten or more renames to an unseen extension. S5 recovery-killing command
text. The verdict table is MVP section 10, unchanged. Actions are
`psutil` suspend, with resume, and a read-only data folder, with undo.
Nothing is killed and nothing is deleted.

**Rule 2:** S2 to S7 are hard-coded and live from minute one. No learning
path may widen them.

### vault

Pulls from `demo/share/` on a simulated hourly tick. Files are stored by
SHA-256 in a content-addressed blob store. One JSON manifest per snapshot
carries path to hash, size, time, entropy, header validity, record count and
the previous manifest's hash. The health check is the Vault's own judgement:
entropy, header, CSV parse and `PRAGMA integrity_check` on the database
backup, marking each snapshot CLEAN or SUSPECT. A snapshot that passes is
pinned as a clean point and automatic clean-up can never remove it.

Restore copies a clean point to a **new** folder, never over the damaged
data, then verifies hashes, headers, CSV parse, SQLite integrity and record
count before anything is swapped.

**Rule 3:** the PDS server never gets a path, credential or address for the
Vault. The Vault always opens the connection.

### simulator

Three Round 2 variants: fast encryptor, impersonator, recovery-killer. A
hard-coded path check refuses to run outside the demo folder. A known key
with a matching decrypt script. It does not spread. Recovery-killing
commands are echoed text only, never executed.

### console

`create_app()` keeps its injectable defaults so the existing tests stay
green. A new `console/live.py` reshapes already-plain-language module output
into the presentation dataclasses. It re-derives nothing; the reasons are
built inside the module that knows why, as ADR-0008 requires.

## Included beyond P0

Hash-chained manifests (F12) and the loss window (F14) are nearly free once
manifests exist, and both are already claimed on the screens. The restore
PIN gate is already drawn.

## Cut, and said openly on stage

Real SMB, the two-laptop setup (F17), S6 watcher liveness (F11) and the
slow encryptor (F13). All four are P1 in MVP already.

## Demo surface

```
python -m nightkeep demo --seed 20260922
```

Builds the district, runs seven learning days, runs three guard days with a
target of zero INCIDENT verdicts, fires the simulator, raises INCIDENT with
reasons, suspends the process and sets the folder read-only, marks the Vault
snapshot SUSPECT and pins the clean point, then verifies a restore at
5,000 of 5,000.

## Order of work

1. `types.py` and the new config blocks
2. `watcher`
3. `entropy_signal` and signals S2 to S5
4. `habit`
5. `judge` verdict and reversible actions
6. `simulator`
7. `vault` and restore
8. console wired to real run data
9. the one-command demo runner
10. repo hygiene and README

Ten tickets in two days is aggressive. The README and the repo pass are last
but guaranteed: if the spine runs out of runway, the build stops and the
README documents exactly what is real and what is not, with no overclaiming
in either direction.
