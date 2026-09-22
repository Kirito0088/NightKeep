# Nightkeep

**Learns the chaos. Catches the crime.**

[![CI](https://github.com/Kirito0088/NightKeep/actions/workflows/ci.yml/badge.svg)](https://github.com/Kirito0088/NightKeep/actions/workflows/ci.yml)
[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/downloads/release/python-3110/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

A district Public Distribution System (PDS) server runs messy, undocumented
jobs every night. Those jobs touch thousands of files in seconds, at 2 am,
zipping, renaming and deleting. To an ordinary security tool they look exactly
like a file-locking threat. Nightkeep **learns** each job's habits, ignores the
weirdness, catches a safe threat simulator within seconds, pauses it, and
restores all 5,000 ration cards from a backup the infected machine could never
reach.

Prototype for **MUSA CodeX 2026**, problem statement **CX0204 "Threat at the
Ration Shop"**, by **Team CodeRed**. Everything runs offline on ordinary
laptops, on invented data, with no cloud, no GPU and no deep learning.

> Prototype on invented data. Not a live government system. No real personal
> data appears anywhere, and no Aadhaar-shaped numbers are ever generated.

---

## Repository

https://github.com/Kirito0088/NightKeep

---

## What it proves

The whole design exists to answer one question a judge will ask: *does this
actually tell a file-locking threat apart from normal legacy weirdness, and can
it get the data back?* Four proofs, each **measured on a real run**, not
claimed. The numbers below come from one seeded 5,000-card run
(`python -m nightkeep --demo-run`):

| # | Proof | Result on the reference run |
|---|---|---|
| **P1** | Weird legacy jobs raise **no** false alarms, and the odd night is shrugged off | 6 erratic jobs over 7 learning + 3 guard nights → **0** INCIDENT verdicts, and one deliberately unusual night (a big catch-up upload) reads as a harmless **ODD** |
| **P2** | A file-locking threat **is** caught fast, and stopped | INCIDENT after **13** files, in **2.1 s**, and the scramble is halted there (target: < 50 files, < 10 s) |
| **P3** | The backup **survives** | The scrambled copy is quarantined **SUSPECT**; the last clean copy stays **pinned** |
| **P4** | Recovery is **proven**, not assumed | **5,000 / 5,000** ration cards verified from the clean copy, all five checks passed |

Run it yourself and the numbers land in `demo/pds/reports/run.json`, which is
exactly what the console then renders. No screen shows an invented figure.

---

## Quickstart

Requires **Python 3.11** (`python` on the build machine; note `py` is 3.14 and
is not the target).

```bash
python -m pip install -e ".[dev]"
```

**Live the whole story once** — build the district, learn the week, guard three
nights, run the threat simulator, pull and restore:

```bash
python -m nightkeep --demo-run --variant fast
```

Variants a judge can pick: `fast` (a fast scrambler), `impersonator` (scrambles
in place under a known job's guise), `recovery-killer` (also writes
system-restore-deletion command text, which is only ever text, never run).

**Open the Vault console** (binds to loopback only, never the LAN).
Start it wired to the demo run directory so every screen reads real state:

```bash
python -m nightkeep --console --out-dir demo/demo_run
```

Then visit <http://127.0.0.1:5000>. If a demo run has happened, the console
shows that run's real numbers and the real 5,000-card district; otherwise it
shows calm, honest screens until a run creates state. The console picks up
the run's state on each request, so no restart is needed after a run.

`python -m nightkeep.console` with no config is the isolated UI mode for
screen work only: it starts with sample records and calm, honest screens
and is never wired to a real demo run.

**One-click showcase** — the polished demo flow. Start the wired console
(`python -m nightkeep --console --out-dir demo/demo_run`), open
<http://127.0.0.1:5000/showcase>, and click **Run Full MVP Demo**. That button
starts the real end-to-end runner (`python -m nightkeep --demo-run --variant
recovery-killer`) as a subprocess and tracks it live: learning, guard, attack,
containment, Vault protection, recovery, and the final proof, each read from
the demo's own output. Every figure shown comes from the run's own report;
nothing is animated or invented. When the run completes, the page links to the
real Incident Report, Restore, Locked Screen, and IT View. Starting a second
run while one is already going is refused.

**Open the Vault console against a finished demo run:**

```bash
python -m nightkeep --console --out-dir demo/demo_run
```

This shows the run's real state on every screen, including the read-only
**IT View** at `/it-view` (incident diagnostics, watcher liveness, habit
cards, Vault snapshots and manifests, or an honest "unavailable" message when
no run is loaded).

**Reset a demo district** after a run (puts every scrambled file back with the
known key, `simulator.key` in `nightkeep/config.yaml`):

```bash
python -m nightkeep.simulator.decrypt --root demo/demo_run/district \
    --key "$KEY" --locked-extension .locked \
    --ransom-note-name HOW_TO_GET_YOUR_FILES_BACK.txt
```

**Run the tests:**

```bash
python -m pytest              # everything
python -m pytest -m "not slow"  # skip filesystem, subprocess and clock tests
```

**Prove the jobs really are erratic** (a standalone report):

```bash
python -m nightkeep --prove-erratic
```

### Console screens

| Route | Screen |
|---|---|
| `/` or `/search` | Ration card search (the PDS system) |
| `/card/<card_no>` | Card detail: members, entitlements, ePoS history |
| `/locked` | The search screen during the incident (labelled "DEMONSTRATION DRILL" until a real INCIDENT) |
| `/safety` | Data Safety home: "am I okay?", the six night tasks |
| `/alert` | The incident report, in ration-office units ("STATUS: ALL CLEAR" when unwired) |
| `/restore` | The three-step restore wizard with its five checks |
| `/server-alert` | The pop-up shown on the office computer |
| `/showcase` | One-click Full MVP Demo: launches and tracks the real demo run |
| `/it-view` | Read-only IT diagnostics (incident, watcher, habit, Vault) |

> **Console `--out-dir` matters.** `--demo-run` writes to `demo/demo_run/`.
> To see a finished run's real state, launch
> `python -m nightkeep --console --out-dir demo/demo_run`.
> If you launch `python -m nightkeep.console` bare (no config), it starts with sample
> records and calm, honest screens — it never fabricates an incident.

### Operator notes

**S5 (recovery-command text) is machine-wide by design.** The judge scans
command lines of all shell / script-host / recovery-tool processes for
configured needles (`vssadmin delete shadows`, `wbadmin delete catalog`,
`bcdedit /set recoveryenabled no`). During a demo, keep unrelated terminals
closed and avoid typing these strings in active command lines.

**F14 naming collision.** F14 in the authoritative `docs/MVP.md` is the Loss
Window Report. An older branch reused F14 for heartbeat containment
(PR #16's branch `fix/f14-heartbeat-survives-containment`); that is a naming
collision in history, not the feature ID.

---

## How it works

Nightkeep is built as a few **deep modules** joined by shallow glue, split
across two machines that share no stateful code and no credentials.

```
 PDS server (Laptop A)                         Vault (Laptop B or a VM)
 ┌───────────────────────────────┐  read-only  ┌──────────────────────────────┐
 │ mock_pds: 5,000 cards, 6 jobs │◀─── PULL ───│ vault: content-addressed      │
 │        │                      │             │  blobs, hash-chained          │
 │        ▼                      │             │  manifests, health check,     │
 │ watcher ─▶ habit ─▶ judge     │── status ──▶│  pinned clean points, verify  │
 │ pause / read-only, reversible │  (pulled)   │ console: the 7 screens        │
 └───────────────────────────────┘             └──────────────────────────────┘
   The Vault always opens the connection. The PDS server holds no path,
   credential or address for it, so a threat on the server has nothing to follow.
```

| Module | It hides |
|---|---|
| `mock_pds` | 5,000 records, 6 erratic jobs, a simulated clock, hidden ground-truth logs |
| `watcher` | watchdog wiring, psutil attribution, an append-only event log |
| `habit` | feature extraction, median/MAD ranges, novelty flags, SQLite storage |
| `judge` | six detection signals, the verdict table, reversible suspend / read-only actions |
| `vault` | the read-only pull, content-addressed blobs, manifests, the hash chain, health, clean points, verified restore |
| `console` | Flask routes and templates, and nothing else |
| `simulator` | the safe, reversible threat simulator and its recovery function |

### The three rules the whole codebase obeys

1. **The learned habit score never pauses, locks or deletes anything on its
   own.** Every INCIDENT verdict needs at least one fixed canary or recovery
   signal.
2. **Canary signals are never learned.** Signals S2–S7 are hard-coded rules,
   live from minute one. No learning path may widen them.
3. **The PDS server never gets a path, credential or address for the Vault.**
   The Vault always opens the connection.

Each rule is enforced by a test that fails if the rule is broken, and each was
confirmed by mutation, not just by passing once.

### The threat simulator is safe by construction

- It refuses to run outside a real demo district (checked against the district
  database's own schema, not a folder name).
- It is fully reversible: files are XORed against a stream from a **known key**,
  and a matching recovery function puts every one back byte for byte.
- It never executes a destructive command. Its "recovery-killer" variant puts
  system-restore-deletion text into a shell command line as echoed text —
  never run as a real command — because that text is what signal S5 reads.
  The simulator package does use `subprocess` (the live attack is launched
  via `Popen`, and the echo shells are spawned the same way), but the
  recovery commands themselves are simulated text only and are never
  executed.
- It does not spread, and it holds no path to the Vault.

---

## Repository layout

```
nightkeep/
  mock_pds/     invented district, 6 erratic jobs, simulated clock, ground-truth logs
  watcher/      what changed on the PDS server, and who caused it
  habit/        what each job normally does (learned)
  judge/        the six signals, the verdict table, reversible actions
  vault/        snapshots, hash chain, health check, verified restore
  console/      Flask app: 7 screens + pop-up, hand-written CSS
  simulator/    the safe threat simulator and its recovery function
  demo.py       one seeded end-to-end run, writes reports/run.json
  demo_run.py   multi-process integration harness (--demo-run)
  types.py      plain dataclasses shared across the two-machine boundary
  config.py     the one loader; config.yaml holds every tunable number
  __main__.py   the entrypoint: reads config once, passes values in
docs/
  MVP.md, SOLUTION_DESIGN.md, adr/   the settled decisions
  demo-runbook.md                    Windows demo operator procedure
CLAUDE.md       the rules the codebase obeys
CONTEXT.md      the vocabulary. Use these words
```

## Documentation

- [`docs/MVP.md`](docs/MVP.md) — the plan, the four proofs, the success metrics.
- [`docs/demo-runbook.md`](docs/demo-runbook.md) — the Windows demo operator procedure.
- [`docs/adr/`](docs/adr) — every settled decision, with its reasoning.
- [`CLAUDE.md`](CLAUDE.md) — the architecture, the three rules, the stack.
- [`CONTEXT.md`](CONTEXT.md) — the domain and system vocabulary.
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — how to work in this repo.

## Tech stack

Python 3.11, standard library first: `watchdog`, `psutil`, `numpy`/`pandas`,
`sqlite3`, `hashlib`, `PyYAML`, and **Flask + Jinja + hand-written CSS** for the
console (no Streamlit, no React, no build step). Tests with `pytest`.

## License

[MIT](LICENSE) © Team CodeRed. Built for MUSA CodeX 2026 on invented data.
