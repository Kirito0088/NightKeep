# CodeRed | Solution Design Blueprint
## MUSA CodeX 2026 · Cyber Security · CX0204 "Ransom at the Ration Shop"

Prepared: 16 September 2026. Builds on: *Research Dossier, Phase 1* (saved in the project as `research/CX0204_Research_Dossier_Phase1.md`).
Status: design only. No slides yet.

### How to read this document

| Tag | Meaning |
|---|---|
| **[PROTOTYPE]** | What our team can actually build and show in the hackathon |
| **[PRODUCTION]** | What a real government deployment would need on top. We do not claim to have built it |
| **[RESEARCH]** | Backed by a source already cited in the Phase 1 dossier |
| **[DESIGN CHOICE]** | Our decision. Reasonable, not proven |
| **[TUNE]** | A number we picked to start with. We must test and adjust it |

The mandatory requirements from the official problem statement (CX0204), used as a checklist everywhere below:

1. Lightweight
2. Offline-capable
3. Backup layer
4. Anomaly-detection layer
5. Bolt-on to legacy government software
6. No full system rewrite
7. Learn the legacy system's own "weird but legitimate" behaviour as a baseline

---

# STEP 1: Five possible solution concepts

These are deliberately different. No winner is chosen in this step.

## Concept 1: HabitPrint

**One line:** A small program on the legacy PC learns a "habit card" for every job that normally runs, then flags anything that doesn't fit a card.

**How it works**
- Watches the data folders for file changes (created, changed, renamed, deleted).
- Every few seconds, lists running processes and notes which ones are writing to disk.
- Links file changes to the job that caused them (for example `nightly_export.py`).
- During a learning period, builds one habit card per job: usual start time, usual number of files touched, usual file types, usual write size, script fingerprint (hash).
- After learning, scores each job run: "how far is this from its own habit card?"

**What makes it different:** it learns *per job*, not one average for the whole machine. A messy nightly script is compared with its own past, so its messiness stops looking suspicious.

**Main technical components:** file watcher, process poller, job-linking logic, habit store (SQLite), scoring function, alert window.

**Where AI/ML is used:** simple statistics per job (typical ranges, how often a job appears at each hour). No deep learning.

**What we would prototype:** a Python agent + a fake "legacy PDS" folder with 3 weird nightly jobs + a live score view.

**Difficulty:** Medium. **Ease of explanation:** Easy ("it learns each job's habits").

**Main weakness:** detection only. No backup. If the attacker kills the agent, nothing is left. Also, linking a file change to the exact process is not always clean on Windows without deeper tools.

---

## Concept 2: TripVault

**One line:** Plant fake "trap" files among the real records and keep versioned backups; if a trap file is changed, freeze everything and restore.

**How it works**
- Place decoy files that look like real beneficiary exports in each data folder. No real job ever uses them.
- If a decoy is modified, renamed or deleted, raise the alarm.
- A backup script copies data to a versioned store every hour.
- On alarm, restore from the last backup before the alarm.

**What makes it different:** almost no false alarms when set up well, because normal jobs never touch the traps. Very easy to show on stage.

**Main technical components:** decoy generator, decoy watcher, versioned copy script, restore script.

**Where AI/ML is used:** none.

**What we would prototype:** decoy files + watcher + hourly copy + restore button.

**Difficulty:** Easy. **Ease of explanation:** Very easy ("tripwires plus time machine").

**Main weakness:** ignores the official twist (no baseline learning). Ransomware that skips the decoys, or starts with the real database, is missed until damage is done. A legacy cleanup script that deletes "old files" might delete the decoys and cause false alarms. If backups sit where the host can write, ransomware can encrypt them too.

---

## Concept 3: PullSafe

**One line:** Install nothing on the legacy PC. A separate small box pulls snapshots of the data over the local network, and judges every snapshot against how much the data *normally* changes at that hour.

**How it works**
- A separate machine (old PC, mini PC or Raspberry Pi class device) on the same LAN reads the legacy PC's data folder through read-only access.
- It takes a snapshot every N minutes and stores files by their hash (duplicates stored once).
- For every new snapshot it runs a "health check": how many files changed, how many now look encrypted (random-looking content, broken file headers), how many got new extensions, whether the beneficiary record count dropped.
- It learns the normal change pattern per hour ("between 1 am and 2 am, around 5% of files change; all still readable").
- If a snapshot fails the health check, it is marked SUSPECT and never replaces the last clean point.

**What makes it different:** works even on an OS too old to run any new software, and the legacy PC has no way to reach or delete the backups, because the box pulls and the PC never pushes.

**Main technical components:** pull service, content-addressed store, manifest per snapshot, health checker, restore tool, LAN web console.

**Where AI/ML is used:** simple per-hour change baseline for snapshots.

**What we would prototype:** two laptops (or laptop + VM): one "legacy PDS PC", one "vault box". Snapshot timeline turns red when encryption shows up.

**Difficulty:** Medium. **Ease of explanation:** Easy ("a separate box that takes photos of the data and notices when a photo looks wrong").

**Main weakness:** slow detection (only as fast as the snapshot interval) and no idea which process did it, so it cannot stop the attack while it is happening.

---

## Concept 4: HoneyLedger

**One line:** Work at the level of beneficiary *records*, not files: insert fake beneficiary records and track record-level fingerprints so we know exactly which records were damaged.

**How it works**
- Add a handful of clearly fake "honey" beneficiary records to the database and exports.
- Keep a fingerprint (hash) of every record row from each backup.
- Watch for honey records being changed, and for sudden jumps in the number of changed or unreadable rows.
- On restore, compare row fingerprints to show exactly which records are safe, lost, or changed.

**What makes it different:** speaks the language of the PDS office ("312 beneficiary records damaged, 4,688 intact") instead of "files".

**Main technical components:** DB/CSV reader, row hasher, honey record inserter, diff engine, report.

**Where AI/ML is used:** simple baseline of how many rows normally change per day.

**What we would prototype:** a SQLite + CSV mock PDS with row-level diff and a damage report.

**Difficulty:** Medium to Hard. **Ease of explanation:** Easy for the story, harder technically.

**Main weakness:** needs to understand the legacy database format, which breaks the "bolt-on without rewrite" spirit for unknown real systems. Inserting fake records into a government database is a policy problem. Ransomware usually encrypts whole files, so row-level watching may never get a chance to see individual row changes.

---

## Concept 5: Change Budget

**One line:** Give every known job a learned "change budget" (how many files it may rewrite per run); anything that goes over budget is paused until a human says yes.

**How it works**
- Learn each job's normal maximum files changed and bytes written.
- While a process runs, count its changes live.
- When the count crosses the budget, pause the process and ask the operator.
- Unknown processes get a very small budget.

**What makes it different:** stops damage early with one simple rule people understand, like a spending limit on a card.

**Main technical components:** live counter per process, budget store, pause/resume control, approval prompt.

**Where AI/ML is used:** learning the budget (typical high value per job).

**What we would prototype:** a live bar per job filling up; ransomware hits the limit and gets paused.

**Difficulty:** Medium. **Ease of explanation:** Very easy.

**Main weakness:** the "undocumented weird job" may sometimes legitimately blow its budget (month-end, harvest-season surge), and a pause interrupts real work. No backup layer. Slow ransomware stays under budget.

---

# STEP 2: Design filters (no scores, strengths and weaknesses only)

## Concept 1: HabitPrint

| Filter | Strengths | Weaknesses |
|---|---|---|
| A. Fit to PS | Directly answers the twist (learns quirks) | No backup layer, so half the brief is missing |
| B. Uniqueness | Per-job habits are more specific than whole-machine anomaly detection | Behaviour baselining in general is a known idea |
| C. Feasibility | Python file watcher + process list is doable | Linking files to processes is fiddly |
| D. Explanation | "Each job has a habit card" is easy | |
| E. Offline | Fully local | |
| F. Legacy OS | Light Python agent | Modern Python (3.9+) refuses to install on Windows 7 (python.org); needs an older build or polling approach |
| G. Detection | Catches unusual jobs quickly | Unusual is not the same as ransomware: alone it produces "weird" alerts |
| H. Backup | None | Must be added from elsewhere |
| I. False positives | Per-job learning cuts them | A job that changes legitimately still looks odd |
| J. Poisoning | | If malware runs during learning it gets its own habit card |
| K. Demo | Live score bars look good | Without recovery the demo ends at "we noticed" |
| L. Scale | One agent per PC | Each site learns separately |

## Concept 2: TripVault

| Filter | Strengths | Weaknesses |
|---|---|---|
| A. Fit | Has backup + a detection signal | Misses the mandatory baseline learning twist |
| B. Uniqueness | | Decoy files already used by products like Elastic Defend and Canarytokens [RESEARCH] |
| C. Feasibility | Very easy | |
| D. Explanation | Very easy | |
| E. Offline | Local decoys work offline | Canarytokens-style internet callbacks would not; we must alert locally |
| F. Legacy OS | Decoys are just files | |
| G. Detection | Near-certain signal when a decoy is changed | Blind until ransomware reaches a decoy |
| H. Backup | Simple versioned copies | Backups on a host-writable location can be encrypted too |
| I. False positives | Low | A legacy cleanup job could delete decoys |
| J. Poisoning | Nothing to poison | |
| K. Demo | Clear moment when trap trips | Judges may say "this is a known trick" |
| L. Scale | Cheap | |

## Concept 3: PullSafe

| Filter | Strengths | Weaknesses |
|---|---|---|
| A. Fit | Backup + anomaly detection + bolt-on + offline, and learns change patterns | Learns *data* patterns, not *job* patterns |
| B. Uniqueness | "Pull-only, judged snapshots" is a strong angle for legacy systems | Pull backups themselves are common in IT |
| C. Feasibility | Two machines + Python copy + hashing is doable | Needs a second device for the demo |
| D. Explanation | "A separate box takes photos and checks them" | |
| E. Offline | Works on LAN with no internet | |
| F. Legacy OS | Best of all concepts: nothing installed on the old PC | |
| G. Detection | Independent of the old PC, so still works if the PC is fully taken over | Delayed by snapshot interval; cannot pause the attacker |
| H. Backup | Strongest: host cannot write to the vault | Data changed after the last clean snapshot is lost |
| I. False positives | Checks readability and headers, not just "lots of change" | Big legitimate batch changes can look like damage at data level |
| J. Poisoning | Health check rules (readable files, valid headers) are not learned, so hard to poison | Change-volume baseline could still be skewed |
| K. Demo | Red snapshot on a timeline is very visual | Less live "action" |
| L. Scale | One box per office; can serve several PCs | Storage grows with data |

## Concept 4: HoneyLedger

| Filter | Strengths | Weaknesses |
|---|---|---|
| A. Fit | Good recovery reporting | Needs to understand the legacy database: conflicts with bolt-on |
| B. Uniqueness | Record-level damage report is unusual | |
| C. Feasibility | Fine for our mock SQLite/CSV | Unrealistic for unknown real formats |
| D. Explanation | Story is easy | Row hashing details are harder |
| E. Offline | Local | |
| F. Legacy OS | Could run on a separate box | Needs DB access drivers for old DB engines |
| G. Detection | Honey records are a strong signal | Whole-file encryption hides row changes |
| H. Backup | Improves restore verification | Doesn't by itself protect backups |
| I. False positives | Low for honey records | Adding fake records to government data is a policy risk |
| J. Poisoning | Honey records not learned | |
| K. Demo | "312 records damaged" is powerful | |
| L. Scale | | Different schema per state |

## Concept 5: Change Budget

| Filter | Strengths | Weaknesses |
|---|---|---|
| A. Fit | Learns per-job behaviour | No backup layer |
| B. Uniqueness | Simple and memorable | Quota/rate-limit ideas exist |
| C. Feasibility | Doable with psutil pause/resume | |
| D. Explanation | Very easy | |
| E. Offline | Local | |
| F. Legacy OS | Same limits as Concept 1 | |
| G. Detection | Stops fast ransomware early | Slow ransomware stays under budget |
| H. Backup | None | |
| I. False positives | | Legitimate surges get paused: real disruption |
| J. Poisoning | | Budget learned during an infection is too generous |
| K. Demo | Live filling bar is great | |
| L. Scale | | Budgets need care per site |

### What the comparison tells us
- **No single concept meets all 7 mandatory requirements.** Concepts 1 and 5 have no backup. Concept 2 skips the twist. Concept 4 breaks "bolt-on". Concept 3 is closest but is slow and blind to processes.
- **The best parts fit together:** Concept 1's per-job habits (twist), Concept 2's traps (high-confidence signal), Concept 3's pull-only vault with snapshot health checks (backup + independence from the old PC), Concept 4's record count check (trustworthy restore), Concept 5's "pause, don't kill" instinct (reversible response).

---

# STEP 3: Final solution architecture

## Name: **QuirkGuard**
**Tagline:** *Knows your system's weird. Stops what isn't.*

(Name note: a quick web search found no obvious security product called QuirkGuard. This is not a trademark check.)

## The core idea in one sentence
Two independent "witnesses" watch the legacy system: a small **Watcher** on the old PC that knows each job's habits, and a separate **Vault box** that pulls backups and checks whether the data still looks healthy. Weird jobs are allowed. Destroying data is not.

## The 5 components (+1 optional)

```
 ┌──────────────────────── LEGACY PDS PC (old OS, untouched app) ────────────────────────┐
 │                                                                                         │
 │  Legacy PDS app + weird nightly jobs      Data folders (DB, exports, allocations)       │
 │            │                                   ▲        │                                │
 │            ▼                                   │        │ read-only share               │
 │  ┌───────────────┐   events   ┌──────────────┐ │        │                                │
 │  │ 1. WATCHER    │──────────▶ │ 3. JUDGE     │ │        │                                │
 │  │ files+process │            │ Habit+Traps  │─┘ pause/ │                                │
 │  └───────────────┘            │ +Recovery    │   lock   │                                │
 │          ▲                    └──────┬───────┘          │                                │
 │          │ uses                      │ status + evidence│                                │
 │  ┌───────────────┐                   │ (Vault pulls)    │                                │
 │  │ 2. HABIT BOOK │                   │                  │                                │
 │  └───────────────┘                   │                  │                                │
 └──────────────────────────────────────┼──────────────────┼────────────────────────────────┘
                                        │ LAN only         │ PULL (vault starts every connection)
                                        ▼                  ▼
 ┌──────────────────────────── VAULT BOX (separate small machine) ─────────────────────────┐
 │  ┌──────────────────────────┐   ┌──────────────────────────┐   ┌──────────────────────┐ │
 │  │ 4. PULL VAULT            │──▶│ 5. CONSOLE & RESTORE     │──▶│ 6. OUTBOX (optional) │ │
 │  │ snapshots + health check │   │ LAN web page, alarms,    │   │ sends summaries when │ │
 │  │ + clean points           │   │ restore wizard, evidence │   │ internet returns     │ │
 │  └──────────────────────────┘   └──────────────────────────┘   └──────────────────────┘ │
 └──────────────────────────────────────────────────────────────────────────────────────────┘
```

| # | Component | Runs on | Job in plain words | Comes from |
|---|---|---|---|---|
| 1 | **Watcher** | Legacy PC | Notices file changes in the data folders and which processes are running and writing | Concept 1 |
| 2 | **Habit Book** | Legacy PC (copy on Vault) | Stores one habit card per known job, learned from the system's own behaviour | Concept 1 + 5 |
| 3 | **Judge** | Legacy PC | Combines three questions (Is it unusual? Does it look like encryption? Is someone attacking recovery?) into a verdict, then takes only reversible actions | Concepts 1, 2, 5 |
| 4 | **Pull Vault** | Separate box | Pulls snapshots, stores them where the PC can't reach, runs its own health check on every snapshot, keeps "clean points" | Concept 3 |
| 5 | **Console & Restore** | Separate box (LAN web page) | Shows alerts, habit cards, snapshot timeline; guided restore with checks | Concepts 3 + 4 |
| 6 | **Outbox** (optional) | Separate box | Queues incident summaries; sends them when a connection exists. Never needed for protection | New |

**Why two machines?** [RESEARCH] AIIMS Delhi recovered because one backup server was unaffected; ransomware routinely deletes recovery options first (MITRE T1490). A backup the infected PC can write to is not a safe backup. The second box is the cheapest way to make that true.

**Sensor-less mode** [DESIGN CHOICE]: if a PC is too old to run the Watcher at all, QuirkGuard runs with components 4 to 6 only. Detection becomes slower (snapshot interval) but backup and health checks still work. This gives a clear answer for very old systems.

---

# STEP 4: Keeping AI/ML simple

## Options compared

| Approach | How it works | Data needed | Easy to explain why it fired? | Handles "weird but normal" jobs? | Verdict |
|---|---|---|---|---|---|
| Fixed thresholds | "Alert if more than 500 files change" | None | Yes | No: one number can't fit all jobs | Too blunt |
| Rolling average + standard deviation (z-score) | Alert if value is far from the average | A few weeks | Yes | Poorly: one huge job run inflates the average and std | Risky with erratic data |
| **Frequency profile** | Count how often each job appears, at which hour, touching which file types | A few nights | Yes | Yes: rare-but-real jobs are "seen before" | **Use (identity, time, types)** |
| **Robust ranges per job (median + MAD / percentiles)** | Learn each job's typical range, ignoring one-off spikes | A few runs per job | Yes: "normal 150 to 260, today 4,812" | Yes: each job judged against itself | **Use (counts, sizes)** |
| EWMA (exponentially weighted average) | Average that slowly follows change | Ongoing | Yes | Adapts, but also adapts to slow attacks | Not for core |
| Isolation Forest | Tree model isolating rare points | More samples, several features | Harder ("the model said so") | Can, but needs enough runs per job | **Optional comparison in Round 2** |
| k-means / DBSCAN clustering | Group similar runs; far from all groups = odd | More samples | Medium | Can | Adds tuning without clear gain |
| Time-window histograms | Activity per hour-of-day | Weeks | Yes | Partly | Folded into frequency profile |

**Decision [DESIGN CHOICE]: "Habit Cards" = frequency profile + robust ranges per job.**
Reasons: works with very little learning data (important for a demo and for a new site), each alert comes with a human-readable reason, a single strange night doesn't wreck the baseline (medians and MAD ignore outliers better than averages), and it is honest ML: the system learns from its own data without labels. Isolation Forest can be run as a side-by-side comparison later if judges ask "why not a real model?".

## The pipeline

### Input
- **File events** from the data folders: time, path, type (created / modified / renamed / deleted), old and new name.
- **Process snapshots** every 2 seconds [TUNE]: process id, name, executable path, command line, parent, start time, bytes written so far.
- **Content samples** for changed files: first 64 KB [TUNE] to measure randomness and check the header.

### Step A: Who did it? (linking files to jobs)
- In each short window, the processes whose "bytes written" counter went up are the active writers (psutil gives this counter on Windows and Linux).
- File events in that window are assigned to the active writer(s).
- **Job identity** = executable + script path from the command line + SHA-256 of the script file. Example: `python.exe | C:\PDS\jobs\nightly_export.py | 9f2c…`.
- **Honest limitation:** if two jobs write at the same moment, events are shared. [PROTOTYPE] fine because demo jobs don't overlap. [PRODUCTION] use Windows event tracing / Sysmon-style telemetry where the OS supports it.

### Step B: Features per job run (and per rolling 60-second window while running)

| # | Feature | Why it matters |
|---|---|---|
| F1 | Job seen before? (count of past runs) | Unknown jobs are the first thing to look at |
| F2 | Script hash same as learned? | Catches a legit job whose code was swapped |
| F3 | Start time vs usual time window | Weird jobs have *their own* usual hours |
| F4 | Existing files rewritten in place | Ransomware overwrites your files; most export jobs write new files |
| F5 | New files created | Normal for exports and archives |
| F6 | Files renamed, and to which extensions | `.tmp → .dat` may be normal; `.csv → .locked` is not |
| F7 | Files deleted | Archive jobs delete; learn how many |
| F8 | Number of different folders touched | Ransomware sweeps across folders |
| F9 | Bytes written | Size of activity |
| F10 | File types written (set of extensions) | Each job writes a familiar set |

### Step C: Habit score (0 to 1)
For each numeric feature (F4, F5, F7, F8, F9) the habit card stores the median and MAD [TUNE: or the 5th to 95th percentile] from learning runs.

- Inside the learned range → 0.
- Outside → distance beyond the range divided by the range width, capped at 1.
- Novelty flags: unknown job → 1.0; known job with changed hash → 0.7; known job at a never-seen hour → 0.6; new extension written → 0.5 [TUNE].
- **Habit score = the highest novelty flag, or the average of the 3 largest feature deviations, whichever is higher.**
- Every score carries its reasons, e.g. *"nightly_export.py rewrote 4,812 existing files (usual 0); touched 9 folders (usual 1)."*

### Step D: Decision
The habit score **never** triggers a blocking action on its own. It feeds the Judge (Step 5).

## How ransomware looks different from the legacy weirdness

| Behaviour | Weird legit nightly job | Ransomware |
|---|---|---|
| Identity | Same script, same hash, run many times before | New program, or known name with a new hash |
| Time | Odd hour, but *its* odd hour | Any time, often outside office hours |
| Existing files | Mostly reads them; writes *new* output files | Rewrites existing files in place |
| Content | Output is readable text, or a valid archive (zip header intact) | Output looks random **and** the original file header is gone |
| Extensions | Familiar set (`.csv`, `.zip`, `.dat`) | Mass rename to a never-seen extension (`.locked`) |
| Spread | One or two folders it always uses | Sweeps many folders |
| Recovery | Never touches shadow copies or backups | Tries to delete shadow copies / backup catalogues (MITRE T1490) [RESEARCH] |
| Traps | Never touches decoys | Touches decoys because it encrypts everything |

---

# STEP 4B: Entropy is a core detection signal (built and tested)

This part is not just a plan. It is coded and tested in the prototype (`quirkguard/judge/entropy_signal.py`, 10 passing tests). The numbers below are **measured on real files**, not invented.

## The one rule that matters
**High entropy alone is never treated as ransomware.** A file is only marked SUSPICIOUS when three things happen together:

1. an **existing** file is rewritten (not a brand-new file), **and**
2. its **entropy jumps** a lot compared with the last known-good version, **and**
3. its **structure/header becomes invalid** (a SQLite file stops starting with `SQLite format 3`, a CSV stops decoding as text).

Then it is combined with the mass-rename, decoy and recovery-attack signals to reach the final verdict.

## Why entropy alone is not enough
Shannon entropy measures how random the bytes look, from 0.0 (all bytes the same) to 8.0 (all 256 byte values equally likely). Encrypted data looks random, so it scores near 8.0. **But so does normal compressed data.** A ZIP, GZIP, JPEG or PDF is already compressed, so it also scores near 8.0. If we alarmed on entropy alone, every backup zip and every photo would be a false alarm.

The fix is to ask a second question: *does the file still have a valid structure for its type?* Compression keeps a valid header. Encryption destroys it.

## Measured numbers from our prototype

| File and event | Entropy | Header/structure | Our status | Why |
|---|---|---|---|---|
| CSV export, before edit | 4.18 | VALID (text) | baseline | known-good |
| CSV, normal edit (add a row) | 4.18 | VALID (text) | **NORMAL** | small entropy change, still valid |
| CSV, **encrypted in place** | 8.0 | **BROKEN** (text -> unknown) | **SUSPICIOUS** | jump + broken structure + rewrite |
| SQLite DB, clean | 5.43 | VALID (sqlite) | baseline | |
| SQLite DB, **encrypted in place** | 8.0 | **BROKEN** (sqlite -> unknown) | **SUSPICIOUS** | jump + broken structure + rewrite |
| New ZIP of report data (legit job) | 3.65 to 8.0* | VALID (zip) | **NORMAL** | new file, valid structure |
| New GZIP log rotation (legit job) | 4.51 | VALID (gzip) | **NORMAL** | new file, valid structure |
| **ZIP of incompressible data** (photos) | **8.0** | **VALID (zip)** | **NORMAL** | high entropy, but structure valid |
| **JPEG scan** (new) | **8.0** | **VALID (jpeg)** | **NORMAL** | high entropy, but structure valid |

\* entropy of a zip depends on the data inside; repetitive text compresses to low entropy, real mixed data approaches 8.0. The last two rows are the key point: **entropy 8.0 and still NORMAL, because the file structure is valid.** That is exactly the trap the naive "alarm on high entropy" approach falls into, and we avoid it.

## Dashboard cards (real output from the prototype)

```
NORMAL FILE
File: rc_export_01.csv
Entropy: 4.9 -> 4.9
Header: VALID -> VALID
Rewrite: YES (same path)
Status: NORMAL

HIGH ENTROPY BUT VALID FILE
File: photos.zip
Entropy: new file -> 8.0
Header: VALID (zip)
Rewrite: NO (new file)
Status: NORMAL
Why: High entropy explained by valid zip format (compressed, not encrypted)

RANSOMWARE-LIKE FILE CHANGE
File: rc_export_01.csv.locked  (from rc_export_01.csv)
Entropy: 4.9 -> 8.0
Header: VALID -> BROKEN
Rewrite: YES
Status: SUSPICIOUS
Why: Entropy jumped 4.9 -> 8.0 (+3.1); Structure broke: text -> no known format; Existing file rewritten
```

## How the maths stays simple
`H(X) = - sum p(x) log2 p(x)` over the 256 possible byte values. In code it is a byte histogram and one loop (about 5 lines). The team can explain it in one sentence: *"it counts how unpredictable the bytes are, 0 means boring and repetitive, 8 means fully random."* Judges do not need the derivation unless they ask.

## Practical details we handle (from testing)
- **Sampling:** we read the start, middle and end (16 KB each) instead of the whole file, so it is fast and still catches partial encryption. [TUNE]
- **Small files:** below 4 KB [TUNE] entropy is unreliable, so tiny files are judged on structure only, never on entropy. This stopped a false alarm in testing.
- **Already-random files:** if a file was already high-entropy (a valid zip), a later change cannot show an entropy jump, so we lean on the structure check instead.
- **Compare with known-good, not with the previous scrambled version:** repeated damage is always measured against the last clean copy, so a slow attacker cannot creep the baseline upward.
- **Rolling 60-second score (S3)** plus a **24-hour slow counter**, so both fast and slow ransomware trip the signal.

# STEP 5: Detection model built around the twist

## The three questions the Judge asks

| Question | Name | What answers it | Learned or fixed? |
|---|---|---|---|
| Is this unusual **for this job**? | **H: Habit** | Habit score from Step 4 | **Learned** |
| Does this look like **data being destroyed**? | **R: Ransom signals** | Traps + encryption pattern + mass rename | **Fixed rules, never learned** |
| Is someone **attacking recovery**? | **K: Recovery attack** | Recovery-killing commands + Watcher silence | **Fixed rules, never learned** |

The most important design decision in QuirkGuard: **we learn habits, we never learn tripwires.** Even if malware is present during learning, the R and K rules are active from minute one and cannot be "taught" that encryption is normal.

## Signals we selected (and why)

| Signal | Group | Strength | What exactly we check | Why it matters | Practical to prototype? |
|---|---|---|---|---|---|
| **S1 Unusual job** | H | Supporting | Habit score ≥ 0.5 [TUNE] | Required by the twist; gives context and reasons | Yes |
| **S2 Trap file changed** | R | Strong | A decoy file is modified, renamed or deleted (reading alone does not count) | Real jobs never use decoys, so a change is very hard to explain innocently | Yes |
| **S3 In-place scramble** | R | Strong | **Built and tested (Step 4B).** An **existing** file is rewritten, its Shannon entropy jumps by at least 1.5 above 7.2 bits/byte [TUNE], **and** its structure becomes invalid. A rolling 60 s score fires S3 at 10 [TUNE]; a 24 h counter catches slow attacks | The heart of ransomware. The "in place + entropy jump + broken structure" combination is what separates it from a legit job that writes new valid zip files [RESEARCH: CryptoDrop uses entropy + file-type change] | **Done** |
| **S4 Mass rename to unknown extension** | R | Medium | At least 10 [TUNE] renames to an extension never seen on this system | Common ransomware habit; cheap to check | Yes |
| **S5 Recovery-killing command** | K | Strong | Process command line contains patterns like `vssadmin delete shadows`, `wmic shadowcopy delete`, `wbadmin delete catalog`, `bcdedit ... recoveryenabled no` | Listed in MITRE ATT&CK T1490 [RESEARCH]; legit PDS jobs have no reason to do this | Yes |
| **S6 Watcher went silent** | K | Medium | The Vault checks the Watcher's status page every 10 s (the Vault asks, the PC only answers); no answer for 30 s [TUNE] | Attackers with admin rights often stop security tools first | Yes |
| **S7 Vault snapshot unhealthy** | R (vault side) | Strong, but delayed | New snapshot shows many files with broken headers / random content / record count drop | Independent second witness that works even if the PC is fully taken over | Yes |

**Signals we are NOT using (on purpose):** ransom note detection (comes late, easy to change), network traffic analysis (adds a whole new skill area), memory analysis and key recovery (far too advanced), kernel drivers (breaks "lightweight bolt-on").

## The verdict table

| Verdict | When | What QuirkGuard does | Destructive? |
|---|---|---|---|
| **NORMAL** | H < 0.5, no R, no K | Log it. During learning, add to habit card | No |
| **ODD** (weird, not dangerous) | H ≥ 0.5, no R, no K | Show a "Review" card: *"nightly_export ran at 03:40 (usual 01:00 to 02:30)."* Operator can tap "This is normal" to update the habit card | No |
| **SUSPICIOUS** | Any one of: S3 or S4 alone by a known job with normal habit; S5 alone; S6 alone; S7 alone | Loud alert; Vault enters **Protect mode** (pins the last clean point, stops all automatic backup clean-up, stores new snapshots only as "suspect"); extra evidence capture | No |
| **INCIDENT** (high confidence) | S2 (trap changed); **or** S3/S4 **plus** H ≥ 0.5; **or** S5 **plus** any R; **or** S7 **plus** S6 | Everything in SUSPICIOUS, **plus**: pause (suspend) the responsible process, set the data share to read-only, save evidence bundle, start restore wizard | Reversible only |

**Rule:** the learned habit score is never enough, by itself, to pause anything. Every INCIDENT needs at least one fixed ransomware or recovery signal.

**Reversible first** [DESIGN CHOICE]: we *pause*, not kill (operator can press Resume). We set read-only, not delete. A wrong call costs minutes, not data.

## Walking through the twist

| Situation | H | R | K | Verdict | Why that's right |
|---|---|---|---|---|---|
| `archive_old.bat` zips last month's exports at 02:10 and deletes the originals | 0.1 (it always does this) | No: new `.zip` files with valid header, originals deleted not rewritten | No | **NORMAL** | Random-looking output and deletions are its habit |
| `nightly_export.py` runs at 03:40 instead of 01:00 to 02:30 | 0.6 | No | No | **ODD** | Worth a look, not worth stopping |
| Undocumented `fix_dat.vbs` renames 800 `.tmp` files to `.dat` | 0.1 | No: `.dat` already a known extension for this job | No | **NORMAL** | Learned quirk |
| Vendor quietly updates `nightly_export.py` (new hash), output unchanged | 0.7 | No | No | **ODD** | Flag code change, don't block |
| Unknown `update_helper.exe` rewrites 200 CSVs in place, random content, headers broken, renames to `.locked`, runs `vssadmin delete shadows` | 1.0 | S3 + S4 | S5 | **INCIDENT** within seconds | Three independent reasons |
| Attacker replaces `nightly_export.py` with an encryptor and runs it at the usual hour | 0.7 (hash changed) + big F4/F8 deviation | S3 | Maybe | **INCIDENT** | Disguise fails because in-place scrambling is a fixed rule |
| Legit job suddenly produces random-looking CSVs (bug) | 0.8 | S3 | No | **INCIDENT** (paused, reversible) | Also a real data-loss event; pausing is correct |

## Detection workflow

```
File events + process list
        │
        ▼
 Link events to job ──► Job identity (exe + script + hash)
        │
        ├──► Habit score H (learned, per job) ──────────────┐
        ├──► Trap check S2 (fixed) ─────────────────────────┤
        ├──► In-place scramble S3 / rename S4 (fixed) ──────┼──► JUDGE ──► NORMAL / ODD / SUSPICIOUS / INCIDENT
        ├──► Recovery command S5 (fixed) ───────────────────┤                          │
        └──► Heartbeat to vault ──► S6 (vault side) ────────┘                          ▼
                                                                          Reversible actions + evidence
 Vault snapshot ──► Health check S7 (fixed + small learned change band) ──► same Judge rules on the vault
```

---

# STEP 6: Offline-first operation

"Offline" in this design means **no internet and possibly no link to the district/state server**. The legacy PC and the Vault box talk over the office LAN or a direct cable. [DESIGN CHOICE]

## What works with zero internet

| Function | Where | Offline? | Notes |
|---|---|---|---|
| Detection (H, R, K) | Watcher + Judge on PC | Yes | No cloud calls at all |
| Baseline learning and habit cards | PC, copied to Vault | Yes | Stored in local SQLite |
| Alerts | PC pop-up + Vault console banner + sound | Yes | No email/SMS needed to raise the alarm |
| Evidence collection | PC writes evidence bundle; Vault pulls it | Yes | Timeline, process details, affected file list, hashes |
| Backup snapshots | Vault pulls over LAN | Yes | |
| Snapshot health check | Vault | Yes | Works even if the PC is lost |
| Restore | Vault console → restore to PC share | Yes | |
| Incident report draft | Vault | Yes | Pre-filled summary shaped for CERT-In's 6-hour reporting duty [RESEARCH] |

## If even the LAN link to the Vault drops
- Watcher and Judge keep detecting and can still pause processes locally.
- Watcher keeps an append-only local log and evidence folder.
- Vault shows "PC unreachable" (same as S6) and keeps the last clean point pinned.
- When the link returns, Vault pulls the missed evidence and takes a snapshot, marked "suspect" until its health check passes.

## When internet / district connectivity returns
- **Outbox** sends queued items in order: incident summaries, health status, habit-card change log, the draft incident report.
- **No beneficiary data leaves the office** through the Outbox [DESIGN CHOICE]: only counts, timings, hashes and file names needed for investigation.
- Optional: download updated recovery-command patterns (S5 list). Detection never waits for this.
- [PRODUCTION] a district or state dashboard could collect these summaries from many offices. This is optional and not needed for protection.

---

# STEP 7: Backup system (Pull Vault)

## The simple version

| Question | Answer |
|---|---|
| **When are backups made?** | [PROTOTYPE] every simulated hour (every ~10 s real time in the demo). [PRODUCTION] e.g. every 30 to 60 minutes in office hours, plus one right **before** and one right **after** the nightly job window [TUNE] |
| **What is backed up?** | The legacy PDS data folders: database files, exports, allocation files, and the job scripts themselves (so we can see if scripts change). Not the whole OS |
| **Where is it stored?** | On the separate Vault box, in a content-addressed store: each file saved once under its SHA-256 hash, plus one small manifest per snapshot listing path → hash, size, time, randomness score, header OK |
| **Why can't ransomware on the PC delete it?** | (1) **Pull only**: the Vault opens every connection; the PC holds no password or path to the Vault. (2) The PC only offers a **read-only** share. (3) The Vault runs no file-sharing service the PC could write to. (4) Stored blobs are marked read-only on the Vault. (5) Clean points are **pinned** and the automatic clean-up can never delete them; manual deletion needs the operator PIN on the Vault console. [PRODUCTION] add a weekly copy to a disconnected drive, in line with CERT-In's "offline backups with encryption" rule [RESEARCH] |
| **How is integrity checked?** | Each manifest includes the hash of the previous manifest (a simple hash chain, so silent edits to history show up). A background job re-hashes a random sample of stored files and compares them with their names. Every restore re-hashes every file |
| **How does restore work?** | Restore Wizard (below) |
| **How do we know restored data is trustworthy?** | It matches a snapshot bit-for-bit (hashes), that snapshot was taken **before** the first suspicious event, it **passed** its health check, and the files open correctly (headers, CSV parses, SQLite integrity check, record count in expected range) |

## Snapshot health check (the Vault's own detector, S7)
For every new snapshot, compared with the previous clean one:

1. % of files changed, compared with the learned normal band **for that hour** (small frequency profile on the Vault).
2. % of changed files whose header no longer matches their type.
3. % of changed files whose randomness jumped above 7.5 bits/byte [TUNE] without being a known archive type.
4. New extensions never seen before.
5. Beneficiary record count (rows in the DB / export) dropped by more than 2% [TUNE].

Result: **CLEAN** (becomes the new clean point), **SUSPECT** (stored, never promoted), or **QUARANTINED** (during an incident).

## Restore Wizard

1. **Pick point:** wizard suggests the newest CLEAN snapshot taken before the first SUSPICIOUS/INCIDENT event.
2. **Restore to a new folder** (`restore_2026-09-20_0100`), never over the damaged data.
3. **Verify:** re-hash every file vs manifest → check headers → parse CSVs → run SQLite `PRAGMA integrity_check` → compare record count with that snapshot's stored count.
4. **Show the loss window:** list files changed between the clean point and the incident, so staff know exactly what to re-check or re-enter.
5. **Swap in:** only after the operator confirms the PC is cleaned (prototype: ransomware simulator stopped). Folders are swapped by rename; the damaged copy is kept aside as evidence.

## [PROTOTYPE] vs [PRODUCTION]

| Area | [PROTOTYPE] | [PRODUCTION] |
|---|---|---|
| Vault hardware | Second laptop or a VM on the same laptop | Dedicated low-cost box per office, locked cabinet |
| Pull method | Vault reads a read-only shared folder (or a read-only HTTP file listing from the Watcher) | Read-only SMB account or rsync over SSH started from the Vault; firewall blocks all inbound from the PC |
| Immutability | Read-only file permissions + pinned clean points + PIN | OS-level immutable flags or WORM media, plus rotating offline drive |
| Encryption of backups | Optional | Required (CERT-In guideline) |
| Scale | One PC, one folder | Several PCs per Vault; retention policy; storage monitoring |

---
# STEP 8: The demo (about 4 minutes)

## Setup
- **Laptop A = "District PDS PC"**: a mock legacy PDS folder (SQLite DB of 5,000 fake beneficiaries, CSV exports, per-shop allocation files), 3 weird scheduled jobs, the Watcher + Judge.
- **Laptop B = "Vault box"**: Pull Vault + Console (web page on the LAN). Can be a VM if we only have one laptop, but two machines make the idea obvious.
- **Simulated clock:** 1 "night" = about 20 seconds, so a week of learning fits on stage.
- **Fake data only.** Ration card numbers are made-up 12-digit numbers fixed to the `11` prefix (**superseded by ADR-0003**, was `RC-` IDs). No Aadhaar-format numbers.
- **Safe ransomware simulator:** only touches the demo folder (hard-coded path check), uses a known key with a matching decrypt script, does not spread, and its "vssadmin delete shadows" step is a harmless command whose *text* appears in the process command line (e.g. `cmd /c echo vssadmin delete shadows /all /quiet`). It never runs the real command.

## The weird jobs we build
| Job | What it does | Why it looks scary |
|---|---|---|
| `nightly_export.py` | Exports all records to CSV at a random time between 01:00 and 02:30 | Unpredictable timing, thousands of writes |
| `archive_old.bat` | Zips old exports into `.zip` and deletes originals | Random-looking output + mass deletes |
| `fix_dat.vbs` (the "undocumented script") | Renames `.tmp` files to `.dat`, rewrites allocation files in place (still valid text) some nights, skips others | In-place rewrites, renames, irregular |

## Scene by scene

| # | Time | On screen | What we say |
|---|---|---|---|
| **1. Normal life** | 0:00 to 0:30 | Laptop A: jobs firing on the simulated clock. Console: live activity strip lighting up at odd hours | "This is a district PDS office. Its nightly jobs are messy: random times, thousands of writes, zips, deletes, renames." |
| **2. Learning** | 0:30 to 1:10 | Console: habit cards appear one by one: *nightly_export: 01:00 to 02:30, 5,000 new rows, writes .csv*. Vault timeline: green snapshots, Day-0 golden snapshot pinned | "QuirkGuard learns each job's own habits. Tripwires are NOT learned, they stay on from minute one." |
| **2b. Weird but fine** | 1:10 to 1:30 | `nightly_export` runs at 03:40. Console shows a yellow **ODD** card, nothing blocked. Operator taps "This is normal" | "A normal tool would scream here. We only flag it, because nothing looks destroyed." |
| **3. Attack** | 1:30 to 1:50 | Laptop A: `update_helper.exe` (simulator) starts. Files turn to `.locked` in the file explorer | "Now real ransomware-like behaviour starts." |
| **4. Detection** | 1:50 to 2:20 | Console: three lights turn red one after another: **Habit** (unknown job), **Ransom** (in-place scramble + trap file changed), **Recovery** (shadow copy delete command). Verdict: **INCIDENT**, with plain reasons | "Weird alone isn't enough. It took a trap, a scramble and an attack on recovery. That's why this isn't a false alarm." |
| **5. Protect** | 2:20 to 2:40 | Process shown as **Paused**; data share read-only; evidence bundle created; counter shows "37 files affected, 4,963 untouched" [numbers will be real from the run] | "We pause, not kill. It's reversible if we're wrong." |
| **6. Backup safe** | 2:40 to 3:00 | Simulator tries to delete the PC's local backup folder and look for the Vault: nothing to find. Vault marks the new snapshot **SUSPECT**; last clean point is pinned. Bonus: kill the Watcher on stage → Vault raises "Watcher silent" | "The PC has no way to reach the vault. The vault pulls. Even if they kill our Watcher, the vault notices." |
| **7. Recovery** | 3:00 to 3:50 | Restore Wizard: pick clean point → restore to new folder → checklist ticks green (hashes, headers, SQLite check, record count 5,000) → loss window list → swap in. PDS app opens records again | "We don't just restore. We prove the restored data is the data from before the attack." |
| **8. Offline** | 3:50 to 4:20 | Turn off internet on both laptops (LAN hotspot stays). Replay a short attack: detection, alert, snapshot still work. Outbox shows "3 items waiting". Reconnect → items sent to a mock district inbox | "No internet needed to protect or recover. Reports go out when the link comes back." |

---

# STEP 9: Attacking our own design

| # | Attack question | The problem in simple words | Must solve in prototype? | Simplest practical mitigation |
|---|---|---|---|---|
| 1 | **Attacker has admin rights** | Admin can stop our Watcher, change permissions, and encrypt anything on the PC | **Partly** | The PC is assumed lost; what matters is the Vault. Pull-only design means admin on the PC still can't reach backups. Vault health check (S7) still detects encryption. Heartbeat loss (S6) raises an alarm. [PRODUCTION] run Watcher as a protected service, separate admin accounts, disable exposed RDP (CERT-In entry vectors) |
| 2 | **Slow ransomware** (a few files per hour) | Per-60-second rules (S3, S4) never reach 10 files | **Yes (simple)** | Also keep a rolling 24-hour counter of "files rewritten in place with broken header". Vault health check compares against the last *clean* snapshot, not just the previous one, so small damage adds up |
| 3 | **Poisoned baseline** (malware running while learning) | Malware could get its own "normal" habit card | **Yes** (this is the twist) | (a) R and K signals are fixed and never learned. (b) Refuse to create a habit card for any job that triggered R or K during learning. (c) Operator confirms each new habit card. (d) Day-0 golden snapshot pinned before learning starts |
| 4 | **No internet** | Cloud tools stop working | **Yes** (demo scene 8) | Nothing in detection, backup or restore uses the internet. Outbox queues reports |
| 5 | **Legit nightly job changes** | New code or new timing looks unusual | **Yes** | It becomes ODD, never INCIDENT unless it also destroys data. Operator approves → habit card version updated. History of card versions kept |
| 6 | **False positive** | We pause a real job | **Yes** | INCIDENT needs a fixed ransomware or recovery signal, not just "unusual". Actions are reversible (Resume, unlock). Every verdict shows its reasons. Thresholds marked [TUNE] |
| 7 | **Backup attacked** | Attacker tries to delete or encrypt the backups | **Yes (show it)** | No write path from PC to Vault; blobs read-only; pinned clean points; hash chain across manifests; PIN for deletions. [PRODUCTION] offline rotating drive, encrypted backups |
| 8 | **Monitoring disabled** | Watcher killed or blocked | **Yes (show it)** | Vault asks the Watcher for a status check every 10 s [TUNE] (pull, like everything else); 30 s of silence = SUSPICIOUS + Protect mode. Detection continues vault-side via S7. Combined with S7 = INCIDENT |
| 9 | **Attacker imitates a known job** | Same name, same hour | **Yes** | Script hash check (F2) + in-place scramble rule (S3) do not care about the name |
| 10 | **Trap files deleted by a legit cleanup job** | False INCIDENT | **Yes** | During learning, if any known job touches a trap, move the trap to a location that job never visits and log it |
| 11 | **Vault box itself compromised** | Attacker reaches the Vault console | **No** | [PROTOTYPE] PIN + LAN only. [PRODUCTION] separate network segment, no remote admin, physical lock, audit log |
| 12 | **Data stolen, not encrypted** | Extortion without locking | **No** | Out of scope of CX0204 text. Mention as future: unusual read volume on data folders, unusual outbound traffic |
| 13 | **OS too old to run the Watcher** | Python 3.9+ won't install on Windows 7 (python.org); newest watchdog needs Python 3.9 | **No** (demo runs on a modern OS) | Sensor-less mode (Vault only). [PRODUCTION] a Python 3.8-compatible build using simple folder polling instead of watchdog, or a small compiled Watcher |
| 14 | **Linking files to the wrong process** | Two jobs writing at once | **No** | Demo jobs don't overlap. [PRODUCTION] OS event tracing where available |
| 15 | **Snapshot taken mid-encryption** | Backup contains some encrypted files | **Yes** | Health check marks it SUSPECT; it never becomes a clean point |

---

# STEP 10: Final solution blueprint

## 1. Product name
**QuirkGuard**

## 2. Tagline
*Knows your system's weird. Stops what isn't.*

## 3. One-paragraph explanation
QuirkGuard is a lightweight, offline-first protection layer that bolts onto old government PDS software without changing it. A small Watcher on the legacy PC learns the habits of each job the system already runs, including the strange nightly scripts nobody documented. It only raises a high-confidence incident when unusual behaviour comes with fixed ransomware signs: trap files changed, existing files scrambled in place, or commands that destroy recovery. Its response is reversible: pause and lock, never delete. A separate Vault box pulls backups the legacy PC cannot reach, checks every snapshot for signs of damage on its own, and restores only data it can prove is from before the attack.

## 4. Problem → solution mapping

| Official requirement / problem | QuirkGuard answer |
|---|---|
| District PDS software hit by ransomware | Watcher + Judge detect in-place scrambling, traps, recovery attacks; Vault detects damage in snapshots |
| Outdated OS | Tiny agent; **sensor-less mode** when nothing can be installed |
| Thousands of beneficiary records locked | Pull Vault with verified restore and record-count check |
| Lightweight | Python + SQLite, no servers, no deep learning, no cloud |
| Offline-capable | Everything runs on the office LAN; Outbox only for reports |
| Backup layer | Pull-only content-addressed Vault with pinned clean points |
| Anomaly-detection layer | Per-job Habit Cards (learned) + fixed ransomware signals |
| Bolt-on, no rewrite | Watches folders and processes from outside the app; reads data via read-only share |
| Twist: learn erratic normal as baseline | Habit Cards per job; ODD verdict for weird-but-harmless; tripwires never learned |

## 5. Architecture (5 components + optional Outbox)
1. **Watcher** (legacy PC): file changes + running processes + writes.
2. **Habit Book** (legacy PC, copy on Vault): habit card per job.
3. **Judge** (legacy PC): Habit + Ransom + Recovery → verdict → reversible action.
4. **Pull Vault** (separate box): snapshots, health check, clean points, Watcher liveness check (Vault asks).
5. **Console & Restore** (separate box, LAN web page): alerts, habit cards, timeline, restore wizard, evidence, report draft.
6. **Outbox** (optional): sends summaries when connected.

## 6. End-to-end workflow
1. **Install:** copy Watcher to PC, set up read-only share, connect Vault box on LAN. Vault takes and pins the **Day-0 golden snapshot**.
2. **Learn** (N nights; demo: 5 simulated nights): Watcher builds habit cards; tripwires already active; operator confirms cards.
3. **Guard:** every job run is scored; Vault pulls snapshots and health-checks each one, and checks the Watcher is alive every 10 s.
4. **Weird night:** ODD card, no disruption.
5. **Attack:** signals combine → INCIDENT → pause process, read-only share, evidence bundle, Vault Protect mode.
6. **Recover:** Restore Wizard picks last clean point → restore to new folder → verify → show loss window → swap in.
7. **Report:** incident report draft on console; Outbox sends summary when a connection exists.

## 7. Detection logic (summary)
- **H** Habit score (learned, per job) from identity, hash, start time, in-place rewrites, new files, deletes, folders, bytes, extensions.
- **R** Ransom signals (fixed): trap changed; ≥10 existing files rewritten in 60 s with high randomness and broken header; ≥10 renames to unknown extension; 24-hour slow counter; vault snapshot unhealthy.
- **K** Recovery attack (fixed): shadow copy / backup catalogue delete commands; Watcher silence.
- **Verdicts:** NORMAL, ODD (H only), SUSPICIOUS (one R or K), INCIDENT (trap, or R + H, or K + R, or vault damage + silence). H alone never blocks.

## 8. Backup / recovery logic (summary)
Pull-only snapshots → content stored by hash on the Vault → manifest per snapshot with hash chain → health check → CLEAN / SUSPECT / QUARANTINED → pinned clean points → Restore Wizard with hash, header, parse, integrity and record-count checks → loss window report → swap in.

## 9. Offline behaviour (summary)
Detection, learning, alerts, evidence, backups, health checks, restore and report drafting all run on the PC and Vault over LAN. If the LAN link drops, the PC side keeps detecting and logging and the Vault raises "PC unreachable". When internet returns, only summaries leave the office.

## 10. AI/ML role
One honest, small role, required by the problem statement: **learning each job's normal behaviour without labels**, using frequency profiles and robust ranges (median + MAD). It explains itself in plain numbers. It adds context and reduces false alarms. It is **not** allowed to pause anything on its own; fixed ransomware and recovery rules must agree. Optional: compare against Isolation Forest in Round 2 to show why the simpler method was chosen.

## 11. What is genuinely innovative
We did not find this exact combination in our Phase 1 research. That does not prove nobody has built it, so we should say "designed specifically for", not "first ever".

1. **Per-job habits instead of one machine-wide baseline**, so erratic legacy jobs are judged against themselves.
2. **"Learn habits, never learn tripwires"**, a simple answer to baseline poisoning.
3. **Two independent witnesses**: an on-PC Watcher that is fast, and an off-PC Vault that still works when the PC is fully taken over.
4. **Pull-only, self-checking backups**: the vault refuses to treat a damaged snapshot as a clean point.
5. **Sensor-less mode** for systems too old to run anything new.
6. **Reversible response** (pause, read-only) designed for government services where a wrong kill is costly.
7. **Verified restore** that proves data is from before the attack and shows the exact loss window.

## 12. Prototype features [PROTOTYPE]
- Mock legacy PDS folder with fake beneficiary DB, exports, allocation files
- 3 weird scheduled jobs + simulated clock
- Watcher (watchdog + psutil), Habit Book (SQLite), Judge with verdict table
- Trap files placed and checked
- In-place scramble detector (Shannon entropy jump + structure/header check) **already built and tested (10 passing tests, Step 4B)**, mass rename detector, recovery-command detector, 24-hour slow counter
- Reversible actions: pause/resume process, read-only data folder
- Pull Vault: snapshots, content-addressed store, manifest hash chain, health check, pinned clean points, Watcher liveness check (vault-initiated)
- Console (**Flask, settled by ADR-0002**): habit cards, live three-light verdict, snapshot timeline, Restore Wizard, evidence download, incident report draft
- Offline demo + Outbox queue to a mock district inbox
- Safe ransomware simulator with decrypt script

## 13. Future features [PRODUCTION / later]
- Windows event tracing / Sysmon-style telemetry for exact process attribution where the OS supports it
- Python 3.8-compatible or compiled Watcher for Windows 7-era systems
- Hardened Vault appliance: encrypted backups, immutable storage, rotating offline drive
- Several PCs per Vault; district/state summary view with no beneficiary data
- Data-theft signals (unusual read volume)
- Isolation Forest comparison as an optional second opinion
- Signed, auto-verified Watcher updates

## 14. Risks and limitations
- **Not production-ready.** Prototype runs on a modern OS with a mock PDS; real district systems, formats and networks are unknown (Phase 1: [UNKNOWN]).
- **An admin-level attacker can defeat the on-PC Watcher.** We rely on the Vault for survival, not the Watcher.
- **Snapshot interval = maximum data loss** for changes after the last clean point.
- **Thresholds are starting guesses** [TUNE] and need testing on real job logs.
- **Process attribution is approximate** with our simple method.
- **Doesn't fix the outdated OS.** CERT-In says end-of-support products should not be on the network [RESEARCH]. QuirkGuard reduces risk while an upgrade is pending; it is not a substitute.
- **Data theft without encryption is out of scope** for the prototype.
- **Sensor-less mode is slower** and cannot pause the attack.

## 15. 30-second explanation
"Old government PDS systems have messy nightly jobs, so normal security tools either miss ransomware or scream all the time. QuirkGuard learns each job's own habits, but only raises a real incident when that weirdness comes with hard ransomware signs, like files being scrambled in place or backups being deleted. A separate Vault box pulls backups the infected PC can't touch, checks them for damage, and restores only data it can prove is clean. Everything works offline."

## 16. 2-minute explanation
"Picture a district supply office. Its PDS software runs on an old OS, and every night some scripts nobody documented export thousands of records, zip them, delete files and rename others, at random times. If you train a simple anomaly detector here, it will alarm every night. If you don't, ransomware walks in.

QuirkGuard splits the question in two. First, 'Is this unusual for *this* job?' A small Watcher on the PC learns a habit card for each job: when it runs, how many files it touches, which file types it writes, and the fingerprint of its script. That's our learning part, and it's deliberately simple so it works with a few nights of data and explains itself in numbers.

Second, 'Is data actually being destroyed?' These rules are fixed and never learned: a trap file gets changed, existing files get rewritten with random-looking content and broken headers, or someone runs a command that deletes shadow copies. Only when unusual behaviour and a destruction sign line up do we call it an incident. Even then we only pause the process and lock the folder, so a mistake is reversible.

The backup lives on a separate small box that *pulls* snapshots. The PC has no password and no path to it, so ransomware on the PC can't reach it. The box also checks each snapshot on its own, so if the attacker kills our Watcher, the box still sees the damage and still refuses to treat a damaged snapshot as clean.

Recovery restores to a new folder, checks hashes, file formats and the beneficiary count, shows exactly what changed after the last clean point, and only then swaps the data back. None of this needs the internet. Reports go out when a connection returns."

## 17. Technical explanation for judges

### LAYER 1: For a software developer who isn't a security specialist
- **Think of it as two programs.** One is a monitoring script on the old PC, like a logger with rules. The other is a backup server that fetches copies, like a scheduled `git pull` that refuses to accept broken commits.
- **The monitoring script** subscribes to folder change events (the `watchdog` library) and polls the process list every 2 seconds (`psutil`). It groups file changes by the program that made them.
- **Learning** is just statistics in SQLite: for each program + script, store the typical start time and the median and spread of "files changed", "files created", "folders touched". New runs are compared to those numbers. No labels needed.
- **Ransomware checks** are plain functions: Did a trap file change? Did 10+ existing files suddenly become random bytes with a broken header? Did a process run a known "delete backups" command?
- **Decision** is a lookup table: learned score + at least one hard rule = incident. Learned score alone = "please review".
- **Response** calls `process.suspend()` and flips the folder to read-only. Both can be undone.
- **Backup server** copies files over the LAN, saves each file under its SHA-256 hash (like git objects), writes a JSON manifest per snapshot that includes the previous manifest's hash (like a commit chain), and runs checks before marking a snapshot "clean".
- **Restore** copies a clean snapshot into a new folder, re-hashes, opens the files to make sure they parse, compares record counts, then swaps folders.

### LAYER 2: How we answer a technical judge
- **Threat model:** financially motivated ransomware with initial access via exposed remote services or valid credentials (CERT-In 2024 entry vectors), ending in T1490 (inhibit recovery) and T1486 (data encrypted for impact). We assume the legacy host can be fully compromised, including admin; survival depends on the off-host Vault. [RESEARCH]
- **Why per-job robust statistics rather than a heavier model:** anomaly detection in noisy operational environments suffers from high false-positive cost and weak ground truth (Sommer & Paxson, 2010). Median/MAD per job identity handles heavy-tailed, erratic jobs with few samples and yields explainable deviations. The anomaly score is context only; blocking requires a deterministic content or recovery signal. [RESEARCH]
- **Poisoning resistance:** training-time poisoning of anomaly detectors is demonstrated (ANTIDOTE, 2009). Our controls: deterministic R/K signals excluded from learning, refusal to learn runs that trip R/K, operator confirmation of new profiles, pinned pre-learning golden snapshot. [RESEARCH]
- **Content-based encryption detection:** entropy plus file-type/header change on in-place rewrites, similar in spirit to CryptoDrop's indicators; the "new file vs in-place rewrite" split and valid-archive-header check address its stated limitation of not knowing intent for legitimate compression/encryption tools. Thresholds are tunable and will be measured. [RESEARCH]
- **Decoys:** only modification/rename/delete counts, to avoid backup/indexing read false positives; decoy placement is validated against learned job paths.
- **Attribution:** per-window correlation of filesystem events with per-process write counters. Known limitation with concurrent writers; production would use OS event tracing where supported.
- **Backup integrity:** pull-only topology (no host-held credentials, no inbound service on the Vault), content-addressed immutable blobs, hash-chained manifests for tamper evidence, pinned clean points exempt from retention, independent vault-side health scoring (header validity, entropy, extension novelty, record-count delta against an hourly change band). Aligns with CISA's offline, tested backups and NIST SP 1800-11's focus on trusting recovered data. [RESEARCH]
- **Independence:** host-side and vault-side detectors share no process or credentials; vault-initiated liveness loss + vault-side damage is itself an incident rule, covering the "kill the agent first" playbook.
- **Recovery RPO/RTO:** RPO bounded by snapshot interval (tunable; pre/post nightly-window snapshots); RTO measured in the prototype and reported honestly.
- **Legacy compatibility:** sensor-less mode needs only a read-only share on the host. Python 3.9+ does not install on Windows 7 (python.org), so a legacy Watcher would target Python 3.8 with polling, or a compiled binary. [PRODUCTION]
- **Compliance hooks:** 180-day local log retention and a pre-filled incident summary for CERT-In's 6-hour reporting; outbox excludes beneficiary PII. [RESEARCH]
- **What we do not claim:** production readiness, protection against a compromised Vault, data-exfiltration detection, or that an outdated OS becomes safe.

---

# Teaching the architecture to the team (before we code)

## The mental model: "A security guard and a locker room"
- The **Watcher + Habit Book + Judge** are a security guard who has worked nights at this office for a week. He knows the cleaner always comes at odd hours and makes noise. He doesn't call the police for that. He calls when someone is **breaking** things.
- The **Vault** is a locker room in a different building. The guard can't open it either. Someone from the locker room comes every hour, takes photos of everything, and checks the photos aren't smashed before filing them.
- If the guard gets knocked out, the locker room notices he stopped checking in.

## Build order (each step is demo-able on its own)

| Order | Build | Done when | Suggested owner |
|---|---|---|---|
| 1 | **Mock PDS + weird jobs + simulated clock** | 5,000 fake records; 3 jobs run on the fake clock | ML/data person |
| 2 | **Watcher** | Prints "job X changed N files in folders Y" | Backend person |
| 3 | **Pull Vault (no checks yet)** | Snapshots appear on second machine; content-addressed store + manifests | Backend person 2 |
| 4 | **Habit Book** | Habit cards in SQLite after 5 simulated nights; ODD card for 03:40 run | ML person |
| 5 | **Ransom + Recovery signals** | Traps, in-place scramble, rename, command patterns, status endpoint for Vault liveness checks | Backend person |
| 6 | **Safe simulator** | Encrypts demo folder only; decrypt script works | Backend person 2 |
| 7 | **Judge + reversible actions** | Verdict table works; pause/resume; read-only | Backend person |
| 8 | **Vault health check + clean points + Restore Wizard** | SUSPECT snapshot never promoted; restore verified | Backend person 2 + ML person |
| 9 | **Console** | Three lights, habit cards, timeline, restore buttons | App/UI person |
| 10 | **Offline + Outbox + rehearsal** | Full 4-minute demo runs twice in a row without touching code | Everyone |

## Suggested project layout [PROTOTYPE]

```
quirkguard/
  mock_pds/            # fake legacy system: data generator, weird jobs, simulated clock
  watcher/             # file events, process polling, read-only status endpoint, local log
  habit/               # feature extraction, habit cards, habit score
  judge/               # signals (traps, scramble, rename, commands), verdict table, actions
  vault/               # puller, blob store, manifests, health check, clean points, restore
  console/             # Flask page, loopback only (ADR-0002; MVP.md section 8 retires the LAN page)
  outbox/              # queue + mock district inbox
  simulator/           # safe ransomware simulator + decrypt (demo folder only)
  config.yaml          # all [TUNE] numbers in one place
```

## Tech stack [PROTOTYPE]
- **Python 3.10+** on the demo machines (modern OS).
- `watchdog` (file events), `psutil` (processes, write counters, suspend/resume), `sqlite3`, `hashlib`, `pandas`/`numpy` for habit statistics.
- **Flask + Jinja + hand-written CSS** for the console (**ADR-0002**; this document originally offered Streamlit or Flask).
- No cloud, no Docker required, no deep learning, no Kubernetes.

## Data formats to agree on first
- **Event:** `{time, path, action, old_path, job_id, bytes, entropy_before, entropy_after, header_ok}`
- **Habit card:** `{job_id, exe, script_path, script_hash, runs, start_window, median/MAD for files_modified, files_created, files_deleted, folders, bytes, extensions_seen, approved_by, version}`
- **Verdict:** `{time, job_id, H, signals[], level, reasons[], actions[]}`
- **Manifest:** `{snapshot_id, time, prev_manifest_hash, files:[{path, sha256, size, entropy, header_ok}], record_count, health, status}`

## Three rules the whole team must remember
1. **Learned score alone never pauses anything.**
2. **Tripwires are never learned.**
3. **The PC never gets a path to the Vault.**

## Timeline reality check
Round 1 closes **17 Sept 2026, 11:59 pm IST** and asks for the initial idea and approach, so Round 1 needs this design explained well, not the full build. Aim to have build steps 1 to 5 working before Round 2 (22 Sept) and the full demo ready before the finale (27 Sept). [OFFICIAL SOURCE: hackathon.musaforstudents.in timeline]
