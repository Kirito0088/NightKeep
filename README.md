# Nightkeep

**Learns the chaos. Catches the crime.**

A district PDS server runs messy nightly jobs. Nightkeep learns them, ignores
the weirdness, catches a safe ransomware simulator within seconds, pauses it,
and restores all 5,000 ration cards from a backup the infected machine could
never reach.

Prototype for MUSA CodeX 2026, problem statement CX0204 "Ransom at the Ration
Shop". Team CodeRed. The geography is real Thane context (Thane and Kalyan
talukas, ADR-0006); every record, person and transaction is invented mock
data. No real personal data anywhere, and Nightkeep never connects to a live
government system.

Prototype on invented data. Not a live government system.

## Running it

Python 3.11.

```bash
python -m pip install -e ".[dev]"
python -m nightkeep
python -m pytest
```

`python -m nightkeep` reads `nightkeep/config.yaml`, reports what it is set
up to watch, and builds the district data under `demo/`. Point it at another
file to try different numbers:

```bash
python -m nightkeep path/to/config.yaml
```

### The end-to-end demo

```bash
python -m nightkeep --demo-run --variant recovery-killer
```

Variants: `fast`, `impersonator`, `recovery-killer`. The run writes to
`demo/demo_run/`. See the full operator procedure in
[`docs/demo-runbook.md`](docs/demo-runbook.md).

### The live-week proof

```bash
python -m nightkeep --prove-erratic --out-dir demo/erratic_week
```

### Running the Vault Console

The console runs locally on the Vault screen bound strictly to loopback
(`127.0.0.1:5000`), never exposed to the network (ADR-0002). Point it at
the demo run's own output directory:

```bash
python -m nightkeep --console --out-dir demo/demo_run
```

`--out-dir` matters: `--demo-run` writes to `demo/demo_run/`, but
`--console` defaults to `demo/erratic_week/`. Omitting `--out-dir
demo/demo_run` after a demo run shows the wrong runtime state.

`python -m nightkeep.console` (bare, no config) starts with sample records
and calm, honest screens for isolated UI work. It never presents a
fabricated incident: with no backend state wired in, the alert screen shows
"STATUS: ALL CLEAR" and the lock screen is labelled a demonstration drill.

Available screens:
- `/`: Ration Card Search (PDS Normal)
- `/search`: Ration Card Search (same as `/`)
- `/card/<card_no>`: Ration Card Detail with members & ePoS history
- `/locked`: PDS lock screen — live wording only after a real INCIDENT,
  otherwise labelled a demonstration drill
- `/safety`: Nightkeep Data Safety Home
- `/alert`: Data Safety Alert (INCIDENT, SUSPICIOUS under review, or all clear)
- `/restore`: Restore Wizard
- `/server-alert`: Office computer pop-up alert

## Detection notes

S5 (recovery-killing command text) is machine-wide by design: the judge
scans command lines of shell/script-host/recovery-tool processes for the
configured needles. Current configured needles
(`nightkeep/config.yaml`):

- `vssadmin delete shadows`
- `wbadmin delete catalog`
- `bcdedit /set recoveryenabled no`

Substring match, case-insensitive. S5 alone is SUSPICIOUS; S5 plus S2/S3/S4
is INCIDENT. During the demo, keep unrelated terminals closed and avoid
typing these strings in active shell command lines.

F14 in the authoritative `docs/MVP.md` is the Loss Window Report ("Re-check
these 37 files"). An older branch/commit label reused F14 for heartbeat
containment (PR #16's branch `fix/f14-heartbeat-survives-containment`); that
is a naming collision in history, not the feature ID.

## Where things are

| Path | What |
|---|---|
| `nightkeep/config.yaml` | every tunable number, in one place |
| `nightkeep/config.py` | the one loader that reads it, at start-up, and fails loudly |
| `nightkeep/__main__.py` | the entrypoint, which passes those values to the modules |
| `nightkeep/mock_pds/` | the fake district: data, six erratic jobs, the simulated clock |
| `nightkeep/watcher/` `habit/` `judge/` | on the PDS server: what changed, what is normal, what to do |
| `nightkeep/vault/` | on the Vault: snapshots, restore engine, pinned clean points |
| `nightkeep/console/` | on the Vault: 7 screens + pop-up, Flask routes and templates |
| `nightkeep/simulator/` | the safe ransomware simulator and its decrypt script |
| `docs/demo-runbook.md` | the Windows demo operator procedure |
| `CLAUDE.md` | the rules the codebase obeys |
| `CONTEXT.md` | the vocabulary. Use these words |
| `docs/adr/` | settled decisions |

