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

## What it proves

The whole design exists to answer one question a judge will ask: *does this
actually tell a file-locking threat apart from normal legacy weirdness, and can
it get the data back?* Four proofs, each **measured on a real run**, not
claimed. The numbers below come from one seeded 5,000-card run
(`python -m nightkeep --demo`):

| # | Proof | Result on the reference run |
|---|---|---|
| **P1** | Weird legacy jobs raise **no** false alarms | 6 erratic jobs over 7 learning + 3 guard nights → **0** INCIDENT verdicts |
| **P2** | A file-locking threat **is** caught fast | INCIDENT after **1** file scrambled, in **0.05 s** (target: < 50 files, < 10 s) |
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
python -m nightkeep --demo --variant fast
```

Variants a judge can pick: `fast` (a fast scrambler), `impersonator` (scrambles
in place under a known job's guise), `cleanup-blocker` (also writes
system-restore-deletion command text, which is only ever text, never run).

**Open the Vault console** (binds to loopback only, never the LAN):

```bash
python -m nightkeep.console
```

Then visit <http://127.0.0.1:5000>. If a demo run has happened, the console
shows that run's real numbers and the real 5,000-card district; otherwise it
falls back to a built-in sample so the screens always come up.

**Reset a demo district** after a run (puts every scrambled file back with the
known key):

```bash
python -m nightkeep --restore
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
| `/locked` | The search screen during the incident |
| `/safety` | Data Safety home: "am I okay?", the six night tasks |
| `/alert` | The incident report, in ration-office units |
| `/restore` | The three-step restore wizard with its five checks |
| `/server-alert` | The pop-up shown on the office computer |

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
- It never runs a system command. Its "cleanup-blocker" variant writes
  system-restore-deletion text to a file as a plain string, because that string
  is what signal S5 reads; the package imports no `subprocess` and no
  `os.system`, and a test holds that.
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
  types.py      plain dataclasses shared across the two-machine boundary
  config.py     the one loader; config.yaml holds every tunable number
  __main__.py   the entrypoint: reads config once, passes values in
docs/
  MVP.md, SOLUTION_DESIGN.md, adr/   the settled decisions
CLAUDE.md       the rules the codebase obeys
CONTEXT.md      the vocabulary. Use these words
```

## Documentation

- [`docs/MVP.md`](docs/MVP.md) — the plan, the four proofs, the success metrics.
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
