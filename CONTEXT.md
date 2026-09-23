# Nightkeep: domain context

The vocabulary this codebase uses. When naming a module, a function, a test, a ticket title or a column, use the term as defined here. Do not drift to the synonyms listed under "say instead".

Two vocabularies live side by side and must not be mixed:

- **Domain terms** describe the Indian Public Distribution System. They come from how a real district supply office actually talks.
- **System terms** describe Nightkeep itself.

A third register, **counter-clerk language**, is what appears on the main path of the console. It is not a synonym layer. It is a deliberate translation, and the rule for it is at the bottom.

---

## Domain: the Public Distribution System

| Term | Meaning |
|---|---|
| **PDS** | Public Distribution System. The national foodgrain distribution scheme. |
| **District PDS server** | The machine in the district supply office that runs the district's own PDS software, its database, its exports and its nightly jobs. This is the machine the problem statement says gets hit. In this prototype it is Laptop A. |
| **Ration card** | The household unit of entitlement. Identified by a 12-digit number with no prefix and no dashes, e.g. `110300512847`. Never an `RC-` ID. See ADR-0003. Carries a **card status** (Active or Suspended), a **card type** (the scheme's own name, never a colour, see ADR-0005), an address and an **issue date**. |
| **Village** | The settlement a card's household lives in, distinct from and nested under its **taluka**. |
| **Member** | A person on a ration card. Has a name, sex, age, relation to head, and an e-KYC status. |
| **Head of household** | The member a card is registered to. Other members state their relation to this person. |
| **FPS** | Fair Price Shop. The village-level shop that issues grain. Identified by an 11-digit numeric shop ID, e.g. `27030300145`, and a shop name. Say **FPS** or **fair price shop**, not "store" or "outlet". |
| **Scheme** | Which entitlement a card falls under. Exactly three: `AAY` (Antyodaya), `NFSA-PHH` (Priority Household), `Kesari (APL)`. Never an invented category. |
| **Entitlement** | The monthly grain a card may draw. PHH: 5 kg per member per month, issued in Maharashtra as 3 kg rice and 2 kg wheat per member. AAY: 35 kg per card per month regardless of family size, plus 1 kg sugar. |
| **Allotment month** | The month a transaction draws against, which is not always the month it happens in. A transaction carries both its own date and its allotment month. |
| **ePoS transaction** | One issue of grain at a shop, recorded on the electronic point-of-sale device. Carries date and time, allotment month, commodity, quantity in kg to 3 decimals, authentication mode, and a **transaction status** (Collected or Part collected). |
| **Authentication mode** | How the beneficiary proved identity at the counter. Exactly four: Biometric, Iris, OTP, Nominee. |
| **e-KYC status** | Whether a member's identity verification is complete. Done or Pending. |
| **Aadhaar seeded** | Whether a member's Aadhaar has been linked to the card. **A yes/no only.** No Aadhaar number is ever generated or stored, and no field is named `aadhaar_no`. |
| **PMGKAY** | Pradhan Mantri Garib Kalyan Anna Yojana. Under it, foodgrain is issued **free**, extended five years from 1 Jan 2024. Do not print the old Rs 3 / Rs 2 NFSA rates as current. |
| **Thane** | The real Maharashtra district this prototype models. Talukas modelled: **Thane** and **Kalyan**, both real. Every card, member, shop and transaction attached to the district is still invented; only the district and taluka names are real. See ADR-0006. |
| **District Supply Officer** | The official who answers for grain reaching shops. One of the two console audiences. |
| **Counter clerk** | The person at the district office who searches cards and fixes records. The other console audience, and the one the main path is written for. |

**Record.** One **ration card row**. There are 5,000. "5,000 / 5,000" in restore verification counts cards, not members. When you mean a person, say **member**.

---

## Domain: the messy night

| Term | Meaning |
|---|---|
| **Job** | One task the PDS software runs by itself, with nobody clicking anything. There are six. Say **job**, not "script", "task" or "cron". |
| **Job identity** | What makes two runs the same job: **executable + script path + SHA-256 of the script**. Not the filename alone. A vendor silently changing a script produces a new hash and therefore a flagged identity. |
| **Job run** | One execution of one job, from start to finish. The unit `habit` scores and `judge` judges. |
| **Erratic** | Timing and volume that change from day to day and are still legitimate. The thing Nightkeep must learn to ignore. Not a synonym for "suspicious". |
| **Undocumented script** | `fix_dat.vbs`. Nobody remembers what it does. It renames `.tmp` to `.dat` and rewrites allocation files in place, some nights only. It is the hardest legitimate job to tell from a file-locking threat, which is why it exists. |
| **Harvest surge** | A switch that doubles volumes on chosen days. Peak season. Legitimate, and must not alarm. |
| **Simulated clock** | One simulated day takes 10 s of real time (ADR-0012). Seeded, so a judge can pick a seed and the run replays exactly. |
| **Learning days** | The first 7 simulated days. `habit` builds one habit card per job. Canary signals are already live. |
| **Guard days** | The 3 simulated days after learning. Proves Nightkeep stays quiet on erratic-but-normal behaviour. Zero INCIDENT verdicts is the pass condition. |
| **Ground truth** | What a job really did, written by the job itself to `logs/_truth/<job>.jsonl`. **Nothing under `watcher/`, `habit/`, `judge/` or `vault/` may read it.** It exists to prove, after the fact, that learning was correct. |

---

## System: Nightkeep

| Term | Meaning |
|---|---|
| **Watcher** | On the PDS server. Notices file changes and which process caused them. |
| **Habit card** | What one job normally does: start window, median and MAD of files modified / created / deleted, folders, bytes, extensions, script SHA-256. **Learned.** Versioned, because legitimate jobs change. |
| **Habit score** | 0 to 1. How far this run sits from its own habit card. **Learned, and never sufficient on its own to pause anything.** Carries its reasons in plain numbers. |
| **Canary signal** | A fixed, hard-coded rule. Signals S2 to S7. **Never learned, and no learning path may widen one.** Say **canary signal**, not "tripwire". |
| **Signal** | One named check. S1 unusual job (learned). S2 canary file changed. S3 in-place scramble, entropy jump plus broken header. S4 mass rename to an unseen extension. S5 system-restore-deletion command text. S6 Watcher went silent. S7 Vault snapshot unhealthy. S2 to S7 are canary signals. |
| **Canary file** | A decoy that looks like a real export and that no legitimate job ever touches. Modifying, renaming or deleting one trips S2. Reading one does not. Say **canary file**, not "trap file". |
| **Judge** | On the PDS server. Combines habit score and signals into a verdict, then takes only reversible actions. |
| **Verdict** | One of NORMAL, ODD, SUSPICIOUS, INCIDENT. Carries its reasons in plain language and the actions taken. |
| **ODD** | Unusual, not dangerous. A yellow review card. Nothing is blocked. The verdict that proves the twist was handled. |
| **INCIDENT** | High confidence. Needs at least one canary signal, never habit score alone. Pauses the process and sets the data folder read-only. |
| **Reversible action** | Suspend, not kill. Read-only, not delete. A wrong call costs minutes, not data. |
| **Vault** | The separate machine that holds the backups. In this prototype, Laptop B or a VM. |
| **Share** | The one folder on the PDS server, `share/`, that the Vault pulls from: day-end exports, allotment files and the nightly safe copy of the database. Read-only, open only to the Vault's address. The live database is never in it. See ADR-0007. |
| **Pull** | The Vault opens every connection. The PDS server never pushes, and **holds no path, credential or address for the Vault**. This is rule 3. |
| **Snapshot** | One pull. Files stored by SHA-256 in a content-addressed store, plus one manifest. |
| **Manifest** | The JSON record of one snapshot: path to hash, size, time, entropy, header validity, record count, and the previous manifest's hash. |
| **Health check** | The Vault's own judgement on a new snapshot, independent of the PDS server. Marks it CLEAN, SUSPECT or QUARANTINED. |
| **Clean point** | A snapshot that passed its health check and is pinned. Automatic clean-up can never delete one. A SUSPECT snapshot never becomes one. |
| **Loss window** | The files that changed between the clean point and the incident. What staff must re-check or re-enter. Counted in counter entries, not files, on the main path. |
| **Restore** | Copy a clean point to a **new** folder, never over the damaged data, then verify hashes, headers, CSV parse, SQLite integrity and record count before any swap. |
| **Verified restore** | A restore whose checks all passed. The claim is "this is the data from before the attack", and it is proved, not assumed. |
| **Sensor-less mode** | Vault only, for a machine too old to run the Watcher. Slower, and cannot pause an attack. Out of scope for the MVP, named in the pitch. |

---

## Say instead

| Do not say | Say |
|---|---|
| beneficiary record, entry | **ration card** (the card) or **member** (the person) |
| store, outlet, shop | **FPS** or **fair price shop** |
| script, task, cron | **job** |
| anomaly, alert | **verdict**, and name its level |
| baseline, model, profile | **habit card** |
| backup | **snapshot**, or **clean point** if it passed its health check |
| RC-0001, beneficiary ID | the 12-digit **ration card number** |
| QuirkGuard, Prahari | **Nightkeep** |

---

## Counter-clerk language

The console's main path does not use the system vocabulary above. It is written for a counter clerk and a District Supply Officer.

- **Never on the main path:** entropy, SHA-256, habit score, MAD, manifest, snapshot, verdict.
- **Counts in ration-office units:** 5,000 ration cards, 37 files damaged, 19 counter entries to re-check.
- **Jobs are named by what they do**, never by filename: "Day-end upload", "Allotment file creation", "Safe copy of the database", "Old file clean-up".
- **Every technical view sits behind a "For the IT person" link.** Nothing is deleted, just demoted.
- **Zero em-dashes in UI copy.** A full stop or a comma.

The translation happens **inside the module that knows why**, not in the template. `HabitScore`, `Verdict` and `RestoreResult` arrive at the console carrying reasons already written in this register. The console renders those strings and never re-derives them. That one decision is what keeps the UI simple.

This register is not invented here; it is worked out, screen by screen, in the "Nightkeep Prototype Screens" Claude Design canvas and recorded at `docs/design/mockup-log.md`. When writing console copy, match the canvas's wording rather than paraphrasing this section.
