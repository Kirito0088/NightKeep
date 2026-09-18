# Nightkeep MVP Plan
### Team CodeRed · MUSA CodeX 2026 · Cyber Security · CX0204 "Ransom at the Ration Shop"

Version 5, 16 Sept 2026. Team decision: **protect the district PDS server** (the problem statement says "a district's PDS software"). The shop-device idea is kept as future work. Builds on `research/CX0204_Research_Dossier_Phase1.md` and `design/CX0204_Solution_Design_QuirkGuard.md`.

**Name:** Nightkeep. It *keeps watch* over the messy night jobs, and a "keep" is the strongest tower of a castle, which is our Vault. Earlier working names: QuirkGuard, Prahari.

**Tagline:** *Learns the chaos. Catches the crime.*

---

## 1. The MVP in one line

A demo where a fake district PDS server runs its messy nightly jobs, Nightkeep learns them, ignores the weirdness, catches a safe ransomware simulator within seconds, pauses it, and restores all 5,000 beneficiary records from a backup the infected machine could never reach.

## 2. What the MVP must prove

Judges will ask one question: *does this actually tell ransomware apart from normal legacy weirdness, and can it get the data back?* The MVP proves exactly four things and nothing more.

| # | Proof | How we show it |
|---|---|---|
| P1 | Weird legacy jobs do **not** cause alarms | 6 erratic jobs run for 7 simulated days of learning, then 3 guard days. Zero INCIDENT verdicts. One late run shows as a yellow ODD card only |
| P2 | Ransomware **is** caught fast | Simulator starts. INCIDENT verdict with plain-language reasons before 50 files are touched (target, to be measured) |
| P3 | The backup **survives** | The infected server has no path or password to the Vault. Vault marks the new snapshot SUSPECT and keeps the last clean point pinned |
| P4 | Recovery is **proven**, not assumed | Restore Wizard ticks: hashes match, headers valid, SQLite integrity OK, record count 5,000 / 5,000 |

If a feature does not help prove P1 to P4, it is not in the MVP.

## 3. Mandatory requirement checklist (from the official PS)

| Requirement | MVP answer | Status |
|---|---|---|
| Lightweight | Python + SQLite on ordinary machines. No cloud, no GPU, no deep learning | In MVP |
| Offline-capable | Everything runs on the office LAN with the internet switched off | In MVP |
| Backup layer | Pull Vault: snapshots, content-addressed store, health check, pinned clean points | In MVP |
| Anomaly-detection layer | Habit Cards (learned) + fixed ransomware signals | In MVP |
| Bolt-on to legacy software | Watches folders and processes from outside. Mock PDS app code is never changed | In MVP |
| No full rewrite | Same as above | In MVP |
| Learn the system's own quirks | Per-job Habit Cards built from 7 simulated days | In MVP |

## 4. Scope

### P0: Must have (build 18 to 21 Sept, ready for Round 2 on 22 Sept)

| ID | Feature | Acceptance criteria |
|---|---|---|
| F1 | **Mock district PDS server** | SQLite DB with 5,000 fake ration cards (**12-digit numeric card numbers, superseded by ADR-0003**, no Aadhaar-format numbers), CSV exports, per-shop allocation files |
| F2 | **6 erratic jobs + simulated clock** | Real scripts started by a scheduler, each with built-in randomness (see section 6). 1 day = about 30 s. Seeded, so a run can be replayed exactly |
| F3 | **Watcher** | `watchdog` file events + `psutil` process poll every 2 s. Prints "job X changed N files in folders Y" |
| F4 | **Habit Cards** | Per job: start window, median + MAD of files modified / created / deleted, folders, bytes, extensions, script SHA-256. Stored in SQLite. Shows reasons in plain numbers |
| F5 | **Fixed ransomware signals** | S2 trap file changed · S3 in-place rewrite + entropy jump + broken header (**already built, 10 tests passing**) · S4 10+ renames to unseen extension · S5 recovery-killing command text (`vssadmin delete shadows`, `wbadmin delete catalog`) |
| F6 | **Judge + reversible response** | Verdict table: NORMAL / ODD / SUSPICIOUS / INCIDENT. Learned score alone never pauses anything. On INCIDENT: `psutil` suspend (with Resume button) + data folder set read-only |
| F7 | **Pull Vault** | Vault pulls every simulated hour over a read-only share (SMBv1 off, share open only to the Vault's address, read-only account). The live database is **never copied directly**: the Vault pulls the nightly database backup file made by `db_backup.py` (SQLite backup API in the demo, the database's own backup tool in real life), plus exports and allocation files. Files stored by SHA-256 and marked read-only. One JSON manifest per snapshot. Health check marks CLEAN / SUSPECT. Clean points pinned. Firewall on the Vault rejects every incoming connection |
| F8 | **Restore Wizard** | Picks newest CLEAN snapshot before first alert. Restores to a new folder, and rebuilds the database from its backup file. Verifies hash, header, CSV parse, `PRAGMA integrity_check`, record count |
| F9 | **Console** (**Flask + Jinja, superseded by ADR-0002**) + **server alerts** | Console runs **only on the Vault's own screen** (bound to the Vault itself, not reachable over the network): three lights (Habit / Ransom / Recovery), verdict feed with reasons, habit cards, snapshot timeline, Restore. Restore, delete and settings need a PIN. The server shows its own **pop-up alert** from the Watcher, so staff see warnings without opening anything on the Vault |
| F10 | **Safe ransomware simulator (3 variants for Round 2)** | Fast encryptor, impersonator (replaces `nightly_export.py`), recovery-killer. The slow encryptor and watcher-killer come in P1 with the features that catch them (F13, F11). Touches the demo folder only (hard-coded path check). Known key + decrypt script. Recovery commands are only echoed text, never run |
| F10b | **Ground-truth check** | Every job secretly writes what it really did to a log Nightkeep never reads. Console shows learned Habit Card next to the real behaviour |

### P1: Should have (build 23 to 26 Sept, ready for the Finale on 27 Sept)

| ID | Feature | Why it matters on stage |
|---|---|---|
| F11 | S6 Watcher liveness check (Vault asks every 10 s) + **watcher-killer simulator variant** | "Kill the agent" live on stage and the Vault still raises the alarm |
| F12 | Hash-chained manifests | Shows backup history can't be silently edited |
| F13 | 24-hour slow counter + **slow-encryptor simulator variant** | Answers the "slow ransomware" question |
| F14 | Loss window report | "Re-check these 37 files" instead of "trust us" |
| F15 | Evidence bundle + CERT-In style report draft | Ties to CERT-In's 6-hour reporting rule |
| F16 | Outbox + offline scene | Wi-Fi off, attack still caught, 3 reports queued, sent on reconnect |
| F17 | Two-laptop setup | Makes "the server has no path to the Vault" physically obvious |
| F18 | Poisoning guard | A job that trips a fixed signal during learning never gets a habit card |
| F19 | Weekly offline copy | Vault writes an encrypted copy to a USB drive, then asks the operator to unplug it. Shows the "third layer" that survives even a hacked Vault |
| F20 | "No door" proof on stage | Simulator scans the network for shares and tries the Vault's ports: nothing found, connection refused, shown live |

### Not in the MVP (said honestly in the pitch as future work)

- Windows 7-era Watcher build (Python 3.8 polling or compiled binary). MVP runs on a modern OS; **sensor-less mode** is the answer for very old servers
- Sysmon / ETW for exact process attribution
- Encrypted, immutable (WORM) vault storage and rotating offline drive
- Several servers or PCs per Vault, district or state dashboard
- Data-theft (exfiltration) detection
- Isolation Forest comparison
- Hardened Vault appliance
- **Shop edition:** Nightkeep as one Android app on the ration shop ePoS device (see version 2 notes)

## 5. What the demo machines stand for

The two laptops are demo stand-ins. Both represent machines at the **district level**, not the ration shop.

| In the demo | In a real district |
|---|---|
| **Laptop A** | The **district PDS server**: an old machine running the district's own PDS software, its database, exports and nightly jobs. This is the machine the problem statement says gets hit |
| **Laptop B (or a VM)** | The **Vault**: a small, low-cost backup server in the same office, or an existing spare server set aside only for this job |

The ration shop ePoS device is **not** protected in this MVP. A shop edition is listed as future work.

### Our scenario assumption (say this openly)

In most real states, the PDS database sits in a **state data centre**, and district offices use it through a website. A 2016 CAG audit of Uttar Pradesh found exactly that: an NIC-built web application with the central database at the State Data Centre, Lucknow, and district offices with a handful of computers used to open it. Maharashtra's ration card system (RCMS) is also a website hosted by NIC.

Our scenario follows the problem statement instead: **a district that runs its own local PDS server** (a local or vendor-installed setup, or a local copy that syncs with the state). We say this plainly in the pitch. The same Nightkeep design also protects a state data centre server: the Watcher sits on the database server and the Vault sits beside it.

## 6. How the demo gets habits when we don't know real ones

### What "nightly jobs" means here

Tasks the PDS software runs by itself, with nobody clicking anything, usually at night or when the network comes back: day-end upload to the state server, stock matching, next month's allocation files, zipping and deleting old logs, and syncing transactions stored during an outage. "Undocumented" means nobody wrote down what they do. "Erratic" means their timing and size change from day to day. They matter because they **look like ransomware**: thousands of files touched in seconds, at 2 am, zipped (random-looking), renamed and deleted.

### Why we don't need to know the real habits

Nobody outside the government knows what a real district PDS server's nightly jobs look like. **Nightkeep doesn't need to know them in advance.** It watches whatever runs and learns from that. So the demo must prove one thing: *given a messy system it has never seen, it learns the mess on its own.*

### Step 1: We build a believable fake district PDS server

A folder that looks like a district PDS setup: `pds.db` (5,000 fake beneficiaries, 50 ration shops, stock and transactions), plus `exports/`, `allocations/`, `reports/`, `archive/`, `logs/`.

Then we write the jobs a district PDS setup really needs, and make each one messy on purpose:

| Job | Real-world purpose | Built-in weirdness |
|---|---|---|
| `nightly_export.py` | Day-end export of transactions for the state server | Starts anytime 01:00 to 02:30. Row count moves ±30% with the day's sales. Skips "network down" days |
| `allocation_gen.py` | Next month's grain quota file for each of 50 shops | Big run on the 1st, small top-ups mid-month. Sometimes runs twice (a "vendor bug") |
| `archive_old.bat` | Zip old exports, delete originals | Only runs when the folder crosses a size limit, so on random nights |
| `db_backup.py` | Nightly database backup file, placed in the shared folder for the Vault to pull | Runs after the export, so its start time drifts with the export. File size grows with the month's transactions |
| `fix_dat.vbs` | The "undocumented script" nobody remembers | Renames `.tmp` to `.dat` and rewrites allocation files in place, some nights only |
| Operator activity | Clerks editing records in office hours | Random edits 10:00 to 17:00, none on Sundays |
| Harvest surge switch | Peak season | Doubles volumes for chosen days |

### Step 2: Nightkeep learns blind

- The jobs have **no code from Nightkeep** and don't talk to it.
- Nightkeep only sees what the operating system shows: which files changed, which program was running, how much it wrote.
- After 7 simulated days (about 3.5 minutes, pre-run before the demo), it has one Habit Card per job. Then 3 guard days show it staying quiet.

### Step 3: We prove it learned correctly

Each job also writes its true behaviour to a hidden log that Nightkeep never reads. The console puts them side by side:

| | Real (hidden log) | Learned by Nightkeep |
|---|---|---|
| `nightly_export.py` start time | 01:00 to 02:30 | 01:04 to 02:27 |
| Files written per run | 180 to 320 | 176 to 318 |

*(Example layout only. The real numbers come from the run.)*

### Step 4: The judges test it, so it isn't rigged

On stage a judge picks from a menu:

- **Legit surprises:** move a job to 04:00, switch on harvest surge, or add a brand-new harmless job. Expected: ODD card, nothing blocked.
- **Attacks (Round 2):** fast encryptor, impersonator or recovery-killer. Expected: INCIDENT, process paused, backup safe, verified restore.
- **Extra attacks (Finale only):** slow encryptor and watcher-killer, once F13 and F11 are built.

In a real office this becomes a 1 to 2 week "observe only" period before Nightkeep is allowed to act.

## 7. Users and the MVP user stories

| User | Story | Feature |
|---|---|---|
| District IT / data entry operator | "When a job runs late, I want a calm yellow card, not a siren, so I don't ignore real alerts." | F4, F6, F9 |
| District IT / data entry operator | "When ransomware starts, I want it paused and a clear reason shown, so I know what happened." | F5, F6, F9 |
| District Supply Officer | "I want proof that restored records are complete, so ration distribution restarts safely." | F7, F8 |
| State PDS / NIC team | "I want a short incident summary without beneficiary data, so we can report to CERT-In in time." | F15, F16 |

## 8. Why ransomware can't reach the Vault (and when it still could)

### How ransomware normally destroys backups

In most offices the backup server is just another machine the main server or office PCs can reach:

- a **mapped drive** on the server (like `Z:\Backups`),
- a **saved password** or admin account that also works on the server,
- the server **pushes** copies to it every night.

Ransomware on the server uses that same drive and password to encrypt or delete the backups. MITRE ATT&CK lists this as a standard step (T1490, Inhibit System Recovery).

### The Vault is a backup server with strict rules

Yes, in a real office the Vault **is** a server. What protects it is not the hardware but five rules:

| # | Rule | What it blocks |
|---|---|---|
| 1 | **Vault pulls, the server never pushes.** The PDS server holds no drive, address or password for the Vault | Ransomware on the server has nothing to follow |
| 2 | **Server shares one folder read-only, safely.** Old file sharing (SMBv1) is switched off, the share is open only to the Vault's address, and the Vault uses a read-only account with its own password | The Vault never needs write access. WannaCry (2017) spread through SMBv1 on unpatched Windows, so that door stays shut |
| 3 | **No open doors on the Vault.** No file sharing, no remote desktop, no web page reachable from the network. Firewall rejects all incoming connections | Nothing on the network to break into |
| 4 | **Stored copies are locked.** Read-only blobs, pinned clean points, deletion only with a PIN at the Vault itself | Old backups can't be edited or wiped |
| 5 | **Every new copy is health-checked.** Scrambled copies are marked SUSPECT and never replace the last clean one | A backup taken mid-attack can't poison recovery |

Plain version: a courier comes to your house every hour to collect photocopies and takes them to a warehouse. A thief in your house can burn your papers, but your house doesn't have the warehouse's address or key.

### When the Vault could still be attacked

| How | Protection |
|---|---|
| Attacker reaches the Vault from another machine on the network | No inbound services, its own admin password, **not joined to the office login system** |
| Someone logs into the Vault from an infected server or PC | Admin actions only at the Vault's own screen and keyboard |
| The Vault's own software is outdated | Small, current Linux with almost nothing installed |
| Physical access, or the Vault is fully taken over | **Weekly offline drive**, unplugged and locked away |

### Three layers of backup in a real office

1. **Vault:** fast restore, copies minutes to an hour old.
2. **Weekly offline drive:** survives even if the Vault is hacked. Matches CERT-In's rule that government offices keep offline, encrypted backups.
3. **Optional copy to the state data centre** when the network allows.

This matches the AIIMS Delhi case (Nov 2022): e-Hospital data came back from a backup server the attackers never reached.

### Fix we made to our own design

The earlier plan let office PCs open the Console on the Vault as a web page. That would be a door we built ourselves, and it clashed with rule 3. Now **the Console exists only on the Vault's own screen**. Staff at the server still get a pop-up alert from the Watcher, so nobody needs to open the Vault remotely.

## 9. Architecture for the MVP

```
 LAPTOP A = district PDS server                    LAPTOP B (or VM) = Vault server
 ┌──────────────────────────────────┐             ┌─────────────────────────────────┐
 │ Mock PDS data + 6 weird jobs     │  read-only  │ Pull Vault                      │
 │        │                         │◀── PULL ────│  snapshots · manifests          │
 │        ▼                         │             │  health check · clean points    │
 │ Watcher ─▶ Habit Cards ─▶ Judge  │── status ──▶│ Console (Vault's own screen)    │
 │ pop-up alert · pause / read-only │  (pulled)   │  3 lights · timeline · restore  │
 └──────────────────────────────────┘             └─────────────────────────────────┘
        No password, no path from A to B. B always starts the connection.
        Vault firewall: all incoming rejected. Console only on B's own screen.
        A shares one folder read-only: SMBv1 off, open only to B, read-only account.
        Third layer: weekly encrypted copy to an unplugged USB drive (P1).
```

**Tech stack:** Python 3.10+, `watchdog`, `psutil`, `sqlite3`, `hashlib`, `numpy`/`pandas`, Flask + Jinja (**superseded by ADR-0002**, was Streamlit). No Docker, no cloud, no GPU.

**Three rules the whole team codes against:**
1. Learned score alone never pauses anything.
2. Tripwires are never learned.
3. The PDS server never gets a path to the Vault.

## 10. Detection logic in the MVP

| Verdict | Trigger | Action |
|---|---|---|
| NORMAL | Habit score < 0.5, no fixed signal | Log |
| ODD | Habit score ≥ 0.5, no fixed signal | Yellow review card, "This is normal" button |
| SUSPICIOUS | One fixed signal without unusual habit | Alert + Vault Protect mode (pin clean point, new snapshots = SUSPECT) |
| INCIDENT | Trap changed, **or** S3/S4 + habit ≥ 0.5, **or** S5 + any ransom signal | Pause process, folder read-only, start Restore Wizard |

Entropy rule (built and tested): a file is only suspicious when an **existing** file is rewritten **and** entropy jumps **and** its header breaks. A new valid ZIP or JPEG at entropy 8.0 stays NORMAL.

## 11. Success metrics (targets we will measure, not claims)

| Metric | MVP target |
|---|---|
| False INCIDENTs across 7 learning + 3 guard days of weird jobs | 0 |
| Files encrypted before INCIDENT | < 50 of 5,000 |
| Time from first encrypted file to INCIDENT | < 10 s real time |
| Records verified after restore | 5,000 / 5,000 |
| Watcher CPU / RAM on demo laptop | < 5% / < 100 MB |
| Full demo runs back to back without touching code | 2 times |

All numbers shown on slides after 22 Sept must come from real runs.

## 12. Build timeline

| Date | Milestone | Owner |
|---|---|---|
| 16 to 17 Sept | Round 1 PPT submitted (deadline 17 Sept, 11:59 pm IST) | All |
| 17 Sept | **Check the Round 2 format** on the official site (online or in person, live demo or video, time limit). Pick demo plan A or B in section 13 | Jayesh |
| 18 Sept | F1, F2, F10b: mock district PDS server + 6 jobs + clock + hidden ground-truth logs | Member 2 |
| 18 to 19 Sept | F3 Watcher, F5 signals wired to existing entropy module | Jayesh |
| 19 to 20 Sept | F7 Pull Vault, F10 simulator | Member 3 |
| 20 Sept | F4 Habit Cards, F6 Judge | Member 2 + Jayesh |
| 21 Sept | F8 Restore Wizard, F9 Console, first full run | Member 3 + Member 4 |
| 22 Sept | **Round 2** · P0 demo | All |
| 24 Sept | **Top 15 announced** | All |
| 23 to 25 Sept | F11 to F20 | Split by owner |
| 26 Sept | Two dry runs, record backup video of demo | All |
| 27 Sept | **Grand Finale, Mumbai** | All |

## 13. The 4-minute demo script

**Plan A (in person):** both laptops on the table, screens on the projector.
**Plan B (online round):** one screen-share showing both machines side by side (for example with OBS), the judge picks from the menu by chat or voice, and a recorded video of a clean run is ready as backup.

1. **Normal life (0:00):** jobs fire at odd hours on the simulated clock.
2. **Learning (0:30):** habit cards appear one by one. Tripwires already on.
3. **Weird but fine (1:10):** export runs at 03:40. Yellow ODD card. Nothing blocked.
4. **Attack (1:30):** simulator renames files to `.locked`.
5. **Detection (1:50):** three lights turn red. INCIDENT with reasons.
6. **Protect (2:20):** process paused, folder read-only, "37 affected, 4,963 untouched" (real numbers from the run).
7. **Backup safe (2:40):** simulator scans for shares and tries the Vault: nothing found, connection refused. Vault snapshot SUSPECT, clean point pinned.
8. **Recovery (3:00):** Restore Wizard ticks green, 5,000 / 5,000.
9. **Judge's choice (3:30):** a judge picks one legit surprise and one Round 2 attack (fast, impersonator or recovery-killer). Both behave as expected, live. Slow and watcher-killer attacks are added for the finale.

## 14. Risks to the MVP and our fallback

| Risk | Fallback |
|---|---|
| Process-to-file linking is messy on Windows | Demo jobs never overlap. Fall back to "active writer in window" |
| Only one working laptop on the day | Vault runs in a VM or a second user account with no access to the data folder |
| Round 2 turns out to be online or video-only | Plan B in section 13: side-by-side screen-share plus a recorded backup run |
| File sharing on the old server becomes a way in | SMBv1 off, share open only to the Vault's address, read-only account |
| ~~Streamlit refresh lag looks slow on stage~~ (**retired by ADR-0002**, the console is Flask) | Pre-recorded video of a clean run kept ready anyway |
| Thresholds cause a false alarm live | All thresholds in `config.yaml`, tuned over 3 dry runs |
| Judge asks "you wrote the jobs, so of course it learns them" | The jobs never talk to Nightkeep, use random seeds the judge can pick, and the judge can add a new job live |
| Judge asks "won't ransomware hit the backup server too?" | Show section 8: pull-only, no open doors, locked copies, weekly offline drive. Demo the refused connection live |
| Real district job behaviour is unknown | Say it openly. The design learns whatever is there; production starts with an observe-only period |
| Antivirus flags our simulator | Run demo folder under an exclusion, sign nothing, explain openly |

## 15. What we will say, and not say

- Say "designed specifically for erratic legacy systems", not "first ever".
- Say "reduces risk while an OS upgrade is pending". CERT-In says end-of-support OS should not be on the network, and we don't pretend otherwise.
- Say "prototype on mock data". Never imply real PDS data or a real deployment.
- Say "most states keep PDS data in a state data centre; our scenario is a district running its own PDS server, as the problem statement describes, and the same design protects a data centre server".
