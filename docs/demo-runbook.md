# Nightkeep Demo Runbook

Operator procedure for the MUSA CodeX 2026 Round 2 demo. This is an
operator runbook, not marketing copy. Every command below exists in the
current codebase; nothing here is invented.

Prototype on invented data. Not a live government system.

---

## 1. Environment

- **Demo machine: Windows.** The six erratic night jobs include
  `fix_dat.vbs` (runs under `cscript.exe`) and `archive_old.bat` (runs
  under `cmd.exe`). On a machine without those interpreters the demo
  runner exits with "Nightkeep cannot run the proof here" instead of a
  real run.
- **Python 3.11**, with the repo installed (`python -m pip install -e ".[dev]"`).
- **Repository state:** branch `main`, clean working tree. `main` is the
  current integrated showcase version: demo from `main`, not from
  `fix/live-ransomware-orchestration` or a teammate's branch.
- **Two laptops (planned):** the PDS server (watcher, judge, simulator,
  pop-up) on one machine, the Vault (snapshots, restore, console) on the
  other. The console binds to `127.0.0.1:5000` only and is viewed on the
  Vault machine's own screen. Two-laptop networking over SMB/firewall is
  still to be verified on the real machines.

## 2. Pre-flight

1. **Close unrelated shells and terminals where practical.** S5 is
   machine-wide by design: the judge scans command lines of
   shell/script-host/recovery-tool processes for the configured needles
   (`vssadmin delete shadows`, `wbadmin delete catalog`,
   `bcdedit /set recoveryenabled no`, case-insensitive substring match).
   An operator shell whose command line contains one of those strings can
   raise S5 (SUSPICIOUS alone, INCIDENT with S2/S3/S4). This is
   specification-consistent; the mitigation is hygiene, not a code change.
2. **Avoid typing recovery-command substrings** into any open command line
   during the run.
3. **Confirm no stale watcher processes:** no leftover
   `python -m nightkeep.watcher --run` from an earlier attempt. A stale
   heartbeat writer would mask a real S6 story.
4. **Start from a clean demo directory:** delete `demo/demo_run/` from any
   previous attempt. The runner writes the whole run there.
5. **Keep the two runs apart:** `--demo-run` writes to `demo/demo_run/`;
   `--console` runs its own live session in `demo/live/` and wipes that
   folder on every start. Never point `--console --out-dir` at
   `demo/demo_run/`, or it deletes the proof.

## 3. Main demo sequence

All commands run from the repository root.

### Step 1 — the end-to-end proof

```bash
python -m nightkeep --demo-run --variant recovery-killer
```

Variants: `fast`, `impersonator`, `recovery-killer`. The run writes to
`demo/demo_run/`.

What the runner does, in order (`nightkeep/demo_run.py`):

1. **Learning days (7):** the six erratic night jobs run against the
   simulated clock; every observed run is folded into Habit. Expect zero
   incidents.
2. **Guard days (3):** the jobs run again; every run is scored and judged.
   Expect zero incidents, one expected yellow ODD.
3. **Attack:** the safe ransomware simulator is launched live under
   `Popen` (not run-to-completion). The Judge judges cumulative event
   windows while the attack is still running and stops at the first
   INCIDENT. On INCIDENT: the attacker process is suspended, the data
   surface is locked read-only, the detection timestamp is recorded.
4. **Vault after the attack:** post-attack pull, snapshot health recorded.
5. **Recovery:** the pinned clean snapshot is restored; all 5,000 records
   verified.
6. The report lands at `demo/demo_run/district/reports/demo_run.json`.

One simulated day takes `clock.simulated_day_seconds` (10 s in
`nightkeep/config.yaml`, ADR-0012); `--day-seconds` overrides it.

### Step 2 — the pop-up

When the INCIDENT verdict is decided, the PDS server raises a native
pop-up (`nightkeep/server_alert.py`):

- The headline says **"It was paused."** only when the Judge actually
  paused the process (a `paused ...` entry in the verdict's actions).
  Otherwise it says **"It was not paused."** — never a false pause claim.
- The detection timestamp is stamped inside the Judge *before* the
  blocking native pop-up, so **dismissing the pop-up cannot inflate the
  reported detection latency**.
- Dismiss the pop-up when it appears and let the run finish.

### Step 3 — the console

The console runs its own live session (ADR-0011) and does not read the
`--demo-run` report. Start it with the default folder:

```bash
python -m nightkeep --console
```

Open `http://127.0.0.1:5000` on the Vault machine, run an attack from the
**Live Demo** tab (below), then walk the screens:

1. **`/safety`** — Data Safety Home. `STATUS: NORMAL`, "Your records are
   safe", the night-tasks table, the clean point.
2. **`/alert`** — `STATUS: ATTACK STOPPED`, the real tripwire signals,
   the loss window ("counter entries to re-check"), the office follow-up
   steps.
3. **`/restore`** — the wizard with the real clean point, Pending checks,
   and the measured loss window. Enter the supervisor PIN
   (`console.supervisor_pin` in `nightkeep/config.yaml`) to run the
   restore from the console.
4. **`/server-alert`** — the pop-up wording for this run ("paused" only
   if the process really was paused).
5. **`/locked`** — shows the live lock wording only because a real
   INCIDENT is behind it. Without one it is labelled a demonstration
   drill.
6. **`/it-view`** — read-only IT diagnostics: the incident verdict with
   signals, reasons and actions taken; watcher liveness and Vault
   protect mode; learned habit cards with medians, spreads and
   observation counts; Vault snapshots with health and manifest hashes;
   Vault alert records. With no run loaded it says so honestly instead
   of fabricating diagnostics.

### Live Demo page (recommended for the recorded demo)

The **Live Demo** tab runs the whole story from one button, on the same live
session every other screen reads:

1. **Install:** `python -m pip install -e ".[dev]"` (Python 3.11).
2. **Start the console:** `python -m nightkeep --console` and open
   `http://127.0.0.1:5000/showcase` (click **Live Demo** in the nav).
3. **Click "Start guided demo".** It restarts the live session on autopilot:
   seven learning days, three guard days, then the `recovery-killer`
   simulator (`console.full_demo_variant`), containment, the Vault pull and
   the restore, all by themselves. The button disables while the run is
   active; a second click cannot start a second run.
4. **What the operator sees:** the guided demo status (Ready, Learn, Guard,
   Attack, Contain, Protect, Recover, Demo complete), each stage read from
   the engine's own status, with the run log below. The page refreshes
   itself once per simulated day.
5. **During the attack:** the native Windows security pop-up appears on the
   demo machine. It is a warning, never a gate: containment, the Vault pull
   and the restore carry on whether or not anyone clicks OK (ADR-0011).
6. **Where the final proof appears:** on Demo complete the page shows the
   run's own report figures (records recovered, detection latency, files
   affected before the incident) and links to the Incident Report
   (`/alert`), Restore (`/restore`), Locked Screen (`/locked`) and IT View
   (`/it-view`).

**Step by step instead:** the same page carries the **Step-by-step
controls** (ADR-0013): the harvest surge switch, the simulated attack
picker with **Launch simulated attack** (unlocks after day 1), and
**Restart from day 1**. After an attack, restore from **Data Safety** with
the supervisor PIN.

### What the unwired console does

`python -m nightkeep.console` with no config is for isolated UI work. It
shows sample records and calm screens; it can never present a fabricated
attack: `/alert` shows `STATUS: ALL CLEAR`, `/restore` shows "No clean
copy yet", `/server-alert` makes no pause claim, and `/locked` is
labelled a demonstration drill.

## 4. Watcher-killer / F11 scenario

This is the "the watcher itself dies" story. The judge on the server may
legitimately see nothing, and the Vault still protects the data.

- The variant is `watcher-killer`. It is **not** one of the CLI
  `--variant` choices; it is exercised through
  `demo_run.run_demo(config, out_dir, variant="watcher-killer")` (see
  `tests/test_demo_run_watcher_killer.py`).
- The killer terminates the watcher agent without touching a file.
- **Judge: NORMAL.** Nothing file-shaped happened, so the server-side
  Judge rightly reports NORMAL.
- **Vault: S6 → SUSPICIOUS + Protect mode.** The Vault's own liveness
  monitor (10 s interval, 30 s silence threshold) detects the missing
  heartbeat and records S6 itself.
- **The clean pin is held:** a later unchanged CLEAN pull does *not*
  advance the clean pin while Protect mode is active. The snapshot stays
  CLEAN — S6 says nothing about the data.
- **Restore remains available** from the held clean point.
- On the console: `/safety` shows `STATUS: PROTECTING` with "Nightkeep
  is protecting your records", and `/alert` shows `STATUS: UNDER
  REVIEW` — never a silent all-clear.

## 5. F14 glossary

- **F14 in the authoritative `docs/MVP.md` = Loss Window Report:**
  "Re-check these 37 files" instead of "trust us". The console's restore
  screen renders it from the database (`counter entries to re-check`).
- **Heartbeat survival** (the watcher heartbeat surviving containment
  read-only locks) shipped on branch
  `fix/f14-heartbeat-survives-containment`. That F14 label is a branch /
  commit naming collision in history, not the MVP feature ID. Do not
  renumber history to fix it.

## 6. Limitations — still needs the Windows demo machine

Not verifiable on Linux; confirm on the real demo hardware:

- `cscript.exe` / `cmd.exe` job execution (`fix_dat.vbs`, `archive_old.bat`)
- native Windows pop-up rendering
- Windows process suspend of the attacker
- the full 7-learning + 3-guard-day run end to end
- two complete back-to-back full demos
- two-laptop deployment (SMB share, firewall rules)
- CPU under 5% and memory under 100 MB during the run
