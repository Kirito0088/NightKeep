# Nightkeep

Prototype for MUSA CodeX 2026, problem statement CX0204 "Ransom at the Ration Shop". Team CodeRed.
Round 2 demo 22 Sept 2026, Grand Finale 27 Sept 2026. This is a 4-day build. Bias hard toward a working demo over completeness.

**Tagline:** Learns the chaos. Catches the crime.

A district PDS server runs messy nightly jobs. Nightkeep learns them, ignores the weirdness, catches a safe ransomware simulator within seconds, pauses it, and restores all 5,000 ration cards from a backup the infected machine could never reach.

---

## Source of truth, in precedence order

1. `docs/MVP.md` (v5, 16 Sept 2026)
2. `docs/SOLUTION_DESIGN.md` (16 Sept 2026)
3. The Session 1 kickoff prompt

Where 1 and 2 disagree, **MVP.md wins**. See `docs/adr/0001-document-precedence.md`. Resolved overrides that beat this order are recorded as ADRs in `docs/adr/` and listed under "Settled decisions" below. If a new instruction contradicts all of these, stop and ask.

---

## The three rules the whole codebase obeys

1. **The learned habit score never pauses, locks or deletes anything on its own.** Every INCIDENT verdict needs at least one fixed ransomware or recovery signal.
2. **Tripwires are never learned.** Signals S2 to S7 are hard-coded rules, active from minute one. No learning path may widen them.
3. **The PDS server never gets a path, credential or address for the Vault.** The Vault always opens the connection.

Each rule has a test. The tests land with the module they police: rules 1 and 2 with `habit` and `judge`, rule 3 with `vault`. **If a change would break one of these rules, refuse it and say so.** Do not write a vacuous test that passes because the module it guards does not exist yet.

---

## Architecture: deep modules, shallow glue

A small number of **deep modules**, each hiding a lot of machinery behind a tiny interface, joined by **shallow, dumb glue**. No pass-through layers. No `XManager` that only forwards calls. No interface as complicated as the thing it hides.

This is the entire public surface. **If a module needs a bigger interface than this, stop and say why before widening it.**

| Module | Public interface | What it hides |
|---|---|---|
| `mock_pds` | `build_district(seed, district, out_dir)`, `run_day(day_no, *, seed, clock, jobs, district_dir) -> None` | 5,000 records, 6 jobs, their randomness, the simulated clock, the hidden truth log |
| `watcher` | `events_since(t) -> [Event]`, `is_alive()` | watchdog wiring, psutil polling, file-to-process attribution, the append-only log |
| `habit` | `score(run) -> HabitScore(value, reasons)`, `learn(run)` | feature extraction, median/MAD ranges, novelty flags, card versions, SQLite storage |
| `judge` | `verdict(run, events) -> Verdict(level, reasons, actions)` | all six signals, the verdict table, suspend/read-only actions and their undo |
| `vault` | `pull()`, `snapshots()`, `restore(snapshot_id) -> RestoreResult` | SMB read, content-addressed blobs, manifests, hash chain, health check, clean points, verification |
| `console` | Flask routes only | rendering, nothing else |

Rules that follow:

- **A module's callers never import its internals.** `judge` calls `habit.score(run)`. It does not know a median from a MAD.
- **`HabitScore`, `Verdict` and `RestoreResult` carry their reasons in plain language**, built inside the module that knows why. The console renders those strings. It never re-derives them. That one decision is what keeps the UI simple.
- **`console` is deliberately shallow.** Routes, template context, nothing more. Any logic that appears there belongs in a module.
- **`config.yaml` is read once, at startup, by one loader.** Modules take values as arguments. They never reach for config themselves. The entrypoint is the glue that reads config and passes values in.

### The two independent witnesses

`watcher` / `habit` / `judge` run on the PDS server. `vault` / `console` run on the Vault. They share **no code that carries state** and no credentials. A shared `types.py` of plain dataclasses is fine. Anything else crossing that line is a bug.

---

## Stack (fixed, do not substitute)

- **Python 3.11** (`python` on this machine; `py` is 3.14 and is not the target). Standard library first.
- `watchdog`, `psutil`, `numpy`/`pandas`, `sqlite3`, `hashlib`, `PyYAML`.
- **Console: Flask + Jinja templates + hand-written CSS.** No Streamlit, no React, no Node, no build step. Bound to `127.0.0.1` only. It must not listen on the LAN. See `docs/adr/0002-flask-console.md`.
- `pytest`. No Docker, no cloud, no GPU, no deep learning.
- **Every tunable number lives in `config.yaml`.** No magic numbers in code.

---

## Folder layout

```
CLAUDE.md
CONTEXT.md
pyproject.toml  # Python 3.11 pin, dependencies, pytest settings
docs/adr/
tests/
nightkeep/
  mock_pds/     # fake district PDS data, 6 erratic jobs, simulated clock, hidden ground-truth logs
  watcher/
  habit/
  judge/
  vault/
  console/      # Flask app, Jinja templates, static CSS
  simulator/    # safe ransomware simulator + decrypt script
  types.py      # plain dataclasses shared across the boundary
  config.py     # the one loader
  config.yaml
  __main__.py   # the entrypoint: reads config once, passes values in
```

Imports are absolute and package-qualified: `from nightkeep.habit import score`.
`nightkeep/` is a package inside the repository root, not the root itself, because
a root-level `types.py` shadows the standard library's `types` module. See
`docs/adr/0004-package-under-nightkeep.md`.

`judge/entropy_signal.py` (Shannon entropy jump + header/structure check, 10 passing tests) is **pre-existing and must not be rewritten**. Wire S3 to it. It is not yet in the repo at the time of writing.

---

## Hard safety rails (as tests, not comments)

- **The jobs contain zero imports from Nightkeep and do not know it exists.** They are launched as subprocesses and receive everything through argv.
- **Nothing outside `mock_pds/` and `tests/` may read `logs/_truth/`.** A test asserts no module under `watcher/`, `habit/`, `judge/` or `vault/` opens it.
- **The simulator** hard-codes a path check and refuses to run outside the demo folder, uses a known key with a matching decrypt script, does not spread, and only **echoes** recovery-killing command text. It never executes `vssadmin`, `wbadmin` or `bcdedit`.
- **No real personal data anywhere, ever.** Names come from a fixed invented pool. Every ration card, member, FPS shop, transaction and officer is invented. See ADR-0006 for what this no longer covers.
- **No Aadhaar-shaped numbers, ever.** No field named `aadhaar_no`. Aadhaar is stored as a seeded yes/no per member only.
- **Every console screen carries "Prototype on invented data. Not a live government system." in its top strip.** A rebuild of the console that drops this line is a regression. See ADR-0005.

---

## PDS data conventions

All of these are constants in **one file, `mock_pds/conventions.py`**. Every generator and every template uses that file. Judges will notice if the data is wrong.

| Field | Convention |
|---|---|
| Ration card number | 12-digit number, no prefix, no dashes, e.g. `110300512847`. **Never an `RC-` style ID.** Leading digits are fixed at `11` so a card number can never fall in the Aadhaar range. See `docs/adr/0003-ration-card-numbers.md` |
| FPS (fair price shop) ID | 11-digit numeric shop ID, e.g. `27030300145`, plus a shop name like "Jai Bhavani Swasta Dhanya Dukan" |
| Scheme | `AAY` (Antyodaya), `NFSA-PHH` (Priority Household), `Kesari (APL)`. No invented category names |
| Entitlement, PHH | 5 kg foodgrain per member per month, issued in Maharashtra as 3 kg rice + 2 kg wheat per member |
| Entitlement, AAY | 35 kg foodgrain per card per month regardless of family size, plus 1 kg sugar |
| Issue price | Free under PMGKAY, extended five years from 1 Jan 2024. Do not print the old Rs 3 / Rs 2 NFSA rates as current |
| Transactions | ePoS records: date and time, allotment month, quantity in kg to 3 decimals, authentication mode (Biometric / Iris / OTP / Nominee) |
| Members | Name, sex, age, relation to head, e-KYC status (Done / Pending) |
| Aadhaar | **A seeded yes/no per member only. Never a 12-digit Aadhaar-shaped number, never a field named `aadhaar_no`** |
| Mobile | Masked, e.g. `98XXXXXX41` |
| Names | Realistic Marathi names with a middle name (father's or husband's given name), e.g. "Sunita Ramesh Kadam" |
| District | **Thane**, Maharashtra: a real district. Talukas modelled: **Thane** and **Kalyan**, both real. Every card, member, shop and transaction attached to it is still invented. See ADR-0006 |
| Card status | `Active` or `Suspended`. Seeded per card; a small minority suspended |
| Card type | The scheme's own official name (`Priority Household` for NFSA-PHH, `Antyodaya` for AAY, `Kesari` for Kesari (APL)). **No colour is printed.** No sourced colour convention exists yet. See ADR-0005 |
| Address | A generated street-level line: plot/house number and a locality name from a fixed invented pool, plus the card's taluka. No real street data |
| Village | Distinct from taluka, drawn from a fixed invented pool per taluka |
| Card issue date | A seeded date, plausible for an active card |
| Transaction status | `Collected` or `Part collected` on an ePoS row. Seeded so most rows are `Collected` |

See ADR-0005 for why these six were added after the mockups.

---

## UI direction

**The console is built from the mockups, not from this section alone.** The
seven screens exist as a Claude Design canvas, "Nightkeep Prototype Screens":
https://claude.ai/artifact/Gye9zkkioeiLxXLUgiMbMw, with its full change
history and the reasoning behind every decision recorded at
`docs/design/mockup-log.md`. Before writing or changing a console template,
read the matching artboard(s) from that canvas and the relevant section of
the log. This section is a summary for orientation, not a substitute.

Seven screens, and only these. Anything else (architecture write-up, research, demo video, threat model) goes on the separate project website, not in the console.

**Three screens of the PDS system itself**, which is what gets attacked and what makes the demo legible: ration card search with results, ration card detail with members and ePoS history, and the same search screen during the attack. GIGW house style: blue utility strip, tri-colour hairline, district seal, bilingual header, navy nav with one orange active tab, dense bordered tables, labels above inputs, square corners everywhere.

**Three screens of Nightkeep plus one pop-up**, written for a counter clerk and a District Supply Officer:

- One sentence at the top answers "am I okay?". "Your records are safe" or "Someone tried to lock your files. It was stopped."
- Counts in ration-office units: 5,000 ration cards, 37 files damaged, 19 counter entries to re-check. On the main path, never "entropy", "SHA-256", "habit score", "MAD", "manifest", "snapshot", "verdict".
- Night tasks are named by what they do: "Day-end upload", "Allotment file creation", "Safe copy of the database", "Old file clean-up". Never by filename on the main path.
- Recovery is three numbered steps with one primary button. Checks read as sentences, e.g. "Every one of the 5,000 ration cards is present and readable".
- Every technical view sits behind a "For the IT person" link. Nothing is deleted, just demoted.
- The pop-up on the office computer says what happened, then three numbered instructions.

### CSS house rules

- **One radius: square.** No rounded cards, no pills, no shadows except the pop-up.
- **One accent: navy `#14387f`.** Orange `#b0451a` marks the active nav tab and nothing else.
- **Three semantic colours only**, used only for real state: green `#1a6b3c` safe, amber `#8a5200` needs review, red `#9b2226` incident.
- **One typeface: Noto Sans**, with Noto Sans Devanagari for the Marathi line. Weight carries hierarchy, not size jumps.
- **Zero em-dashes anywhere in the UI copy.** Use a full stop or a comma.
- No decorative status dots, no separator dot chains, no section-number labels, no icon flourishes.
- Numbers in tables use `font-variant-numeric: tabular-nums` and align consistently.

Same rule as the architecture: put the reasoning in the module, and let the screen say one clear thing.

---

## Settled decisions

Recorded as ADRs in `docs/adr/`. These beat the plain document precedence order.

| ADR | Decision |
|---|---|
| 0001 | `MVP.md` wins over `SOLUTION_DESIGN.md` |
| 0002 | Flask + Jinja + hand-written CSS for the console, not Streamlit |
| 0003 | 12-digit numeric ration card numbers, not `RC-` IDs |
| 0004 | Code lives in a `nightkeep/` package inside the repo root, not at the root |
| 0005 | Six PDS fields (card status, card type, address, village, issue date, transaction status) added from the mockups; console built from the Claude Design canvas, not from prose alone |
| 0006 | The district is the real Thane, talukas Thane and Kalyan; every record attached to it stays invented |

Resolved without an ADR, because the newer document already says so: the product is **Nightkeep** (not QuirkGuard); the console binds to `127.0.0.1` only (MVP.md section 8 reverses SOLUTION_DESIGN's LAN web page); there are **6** erratic jobs (not 3); learning is **7** simulated days plus **3** guard days (not 5 nights); one simulated day is **30 s** (not 20 s).

---

## How to work in this repo

- **Plan first, show the plan, wait for the go.** No code before approval.
- **One feature per commit, tests alongside.** Run the tests yourself before saying something works.
- Use `/tdd` at pre-agreed seams. Use `/code-review` when a feature is done.
- **Never add a `Co-Authored-By` line to a commit.**
- If you are about to build something outside the approved ticket, stop and ask.
- **When a ticket touches data shape (`mock_pds`) or the console UI, check the mockups first.** Read the relevant artboard(s) from the "Nightkeep Prototype Screens" canvas (https://claude.ai/artifact/Gye9zkkioeiLxXLUgiMbMw) and `docs/design/mockup-log.md` before inventing a field, a label or a layout. The mockups are the reference judges will compare the build against, not a nice-to-have.

## Agent skills

### Issue tracker

Issues are tracked in GitHub Issues for Kirito0088/NightKeep via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Domain docs

Single-context layout. Root `CONTEXT.md` + `docs/adr/`. See `docs/agents/domain.md`.
