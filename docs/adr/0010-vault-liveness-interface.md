# ADR-0010: S6 liveness is owned by the Vault, and widens its interface

**Date:** 21 Sept 2026
**Status:** Accepted

## Context

F11 (MVP.md section 4, P1) adds S6: the Vault notices when the Watcher on the
PDS server has gone silent, and says so on its own. The watcher-killer
simulator variant terminates the real agent process live on stage, so the
answer has to come from somewhere the killer cannot reach.

CLAUDE.md gives `vault` exactly three public functions, `pull()`,
`snapshots()` and `restore(snapshot_id)`, and says to stop and say why before
widening that. S6 cannot be built inside those three. This ADR is that
"stop and say why".

Three rules decide where liveness can live.

- **The two independent witnesses.** `watcher` / `habit` / `judge` run on the
  PDS server; `vault` / `console` run on the Vault. A liveness check that the
  server answers for itself is not a second witness: the watcher-killer would
  take the alarm down with the agent. The Vault has to reach its own
  conclusion without asking the server anything.
- **Rule 3: the PDS server never gets a path, credential or address for the
  Vault.** So the heartbeat cannot be pushed. The agent writes
  `share/.watcher-heartbeat`; the Vault reads it through the same one-way
  pull channel it already uses, on its own clock, and never writes back.
- **Snapshot health is about the data.** S7 (a damaged snapshot) already
  lives on `Snapshot.health`. S6 is about the *observer*, not the records, so
  it cannot be folded into that field without making a snapshot's health mean
  two different things.

## Decision

**Liveness is Vault-owned state, and the Vault's public interface grows to
carry it.** The Vault independently detects the silence, enters Protect mode,
records the alert, and composes the S6/S7 verdict. Each of those four is a
decision the Vault makes alone, and a decision that is made somewhere has to
be readable from there: that is the same reasoning that puts reasons inside
`HabitScore` and `Verdict` rather than in the console.

The new surface, in three tiers.

**Tier 1, required by production behaviour.** These are the S6 loop and its
documented response, and they are part of the contract.

| Name | Why it must be public |
|---|---|
| `check_watcher_liveness() -> WatcherLiveness` | One honest answer about the heartbeat, on demand |
| `start_liveness_monitor(...)` / `stop_liveness_monitor()` | The Vault's own 10 s clock. Without it, S6 only fires when someone asks, which is not independent detection |
| `vault_verdict` | NORMAL / SUSPICIOUS / INCIDENT, composed from S6 and S7 by `combined_verdict()` |
| `protect_mode` | The documented SUSPICIOUS response: loud alert, extra evidence, clean pin held |
| `vault_state -> VaultState` | One consistent read of all four at once, so the console never samples a half-changed state |
| `alerts()` | The durable evidence log the response is required to leave behind |
| `combined_verdict(...)` | The S6/S7 table itself. Module-level and pure, so the table can be read and tested without a Vault on disk |

**Tier 2, evidence only.** `liveness_check_count` is **not** test-only: the
demo runner reads it into `demo_run.json` as `vault_liveness_checks`, which is
how a slide can say the Vault checked on its own clock N times rather than
claiming it. It stays public as a measured number and nothing else. **No
module may branch on it**, and it is not an input to any verdict.

**Tier 3, not required by any caller.** `last_liveness` has no caller outside
the Vault's own internals and the tests; `vault_state.watcher_alive` already
gives the console what it needs. It should become `_last_liveness`. That is a
rename, not a behaviour change, and F11 is frozen for the Round 2 demo, so it
is a follow-up ticket rather than a change here.

## What this ADR does not widen

- **`Snapshot.health` still describes only the data.** S6 suspicion never
  rewrites it, and the heartbeat file is skipped by `_pull_files` so a beat
  can never become a snapshot entry.
- **The learned habit score is untouched.** Rule 1 holds: S6 is a fixed
  signal, and the Vault's verdict has no habit input and therefore no ODD
  level.
- **Rule 3 holds.** The share path and every threshold arrive as arguments at
  the Vault's own startup. The server is never told them, the Vault only ever
  reads the share, and the heartbeat is a file the agent drops, not a
  connection it opens.
- **The server-side Judge is not told.** Under the watcher-killer the Judge
  correctly sees NORMAL, because no files were touched. The two witnesses
  disagreeing, and the Vault being right, is the point of the demo.

## Consequences

- The module table in CLAUDE.md now points at this ADR for `vault` instead of
  listing three functions that no longer describe it.
- Any further growth of `vault` needs its own ADR. "S6 already widened it" is
  not a precedent.
- Follow-up ticket: demote `last_liveness` to `_last_liveness` after the
  Round 2 demo, updating `tests/test_vault_protect_mode.py` and
  `tests/test_watcher_liveness.py` with it.
- The console reads `vault_state` and `alerts()` and renders them. It still
  decides nothing, which is ADR-0008 unchanged.
