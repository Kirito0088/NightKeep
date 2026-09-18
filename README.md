# Nightkeep

**Learns the chaos. Catches the crime.**

A district PDS server runs messy nightly jobs. Nightkeep learns them, ignores
the weirdness, catches a safe ransomware simulator within seconds, pauses it,
and restores all 5,000 ration cards from a backup the infected machine could
never reach.

Prototype for MUSA CodeX 2026, problem statement CX0204 "Ransom at the Ration
Shop". Team CodeRed. Mock data only, an invented district, no real personal
data anywhere.

## Running it

Python 3.11.

```bash
python -m pip install -e ".[dev]"
python -m nightkeep
python -m pytest
```

`python -m nightkeep` reads `nightkeep/config.yaml` and reports what it is set
up to watch. Point it at another file to try different numbers:

```bash
python -m nightkeep path/to/config.yaml
```

## Where things are

| Path | What |
|---|---|
| `nightkeep/config.yaml` | every tunable number, in one place |
| `nightkeep/config.py` | the one loader that reads it, at start-up, and fails loudly |
| `nightkeep/__main__.py` | the entrypoint, which passes those values to the modules |
| `nightkeep/mock_pds/` | the fake district: data, six erratic jobs, the simulated clock |
| `nightkeep/watcher/` `habit/` `judge/` | on the PDS server: what changed, what is normal, what to do |
| `nightkeep/vault/` `console/` | on the Vault: snapshots, restore, the screen staff read |
| `nightkeep/simulator/` | the safe ransomware simulator and its decrypt script |
| `CLAUDE.md` | the rules the codebase obeys |
| `CONTEXT.md` | the vocabulary. Use these words |
| `docs/adr/` | settled decisions |
