# ADR-0007: What the PDS server shares with the Vault

**Date:** 18 Sept 2026
**Status:** Accepted

## Context

MVP.md F7 says the Vault pulls "the nightly database backup file made by
`db_backup.py` ... plus exports and allocation files" over a read-only share.
MVP.md section 6 says the backup is "placed in the shared folder for the
Vault to pull", and section 8, rule 2, says the server "shares one folder
read-only". None of them says which folder that is.

Ticket #3 first put the backup in `data/`, next to the live `district.db`.
That left two bad choices for the share: share `data/` and expose the live
database, which F7 says is "never copied directly", or share several folders
and break "one folder".

The demo runs on two laptops: Laptop A is the district PDS server, Laptop B
is the Vault. The layout should be the one a real office would set up.

## Decision

**The PDS server shares exactly one folder, `share/`, read-only, and the live
database is never inside it.**

```
district/
  data/district.db      live database. Never shared.
  share/                the one read-only SMB share
    exports/            day-end export CSVs
    allocations/        per-shop allotment files
    backups/            nightly safe copies of the database
  reports/  archive/  logs/     never shared
```

- `db_backup` writes into `share/backups/`, `nightly_export` into
  `share/exports/`, and the allotment job (#4) into `share/allocations/`.
- On Laptop A, `share/` is published over SMB **read-only**, to a local
  account that exists only for the Vault, open **only to Laptop B's
  address**, with SMBv1 switched off (MVP section 8, rule 2).
- The share address and that account live in the **Vault's own config**.
  Laptop A's config holds nothing about the Vault. This is rule 3.
- `vault.pull()` takes the share location as an argument: a local path when
  developing on one machine, the network path to Laptop A on stage. Same
  code either way.
- `logs/_truth/` stays outside the share, so the Vault could not read the
  ground truth even by accident.

## Consequences

- If the Vault were ever compromised, an attacker could read copies in one
  folder and change nothing on Laptop A.
- Ransomware on Laptop A can still scramble what is in `share/`. That is the
  case the Vault's health check exists for: the new snapshot is marked
  SUSPECT, and the last clean point, already in the Vault's own store, stays
  pinned.
- The Judge's INCIDENT action "set the data share to read-only"
  (SOLUTION_DESIGN.md section on verdicts) has exactly one folder to lock.
- Ticket #4's old file clean-up zips from `share/exports/` into `archive/`,
  so archived exports leave the share. The Vault already holds them from
  earlier pulls.
- **Open for the Vault ticket:** SOLUTION_DESIGN.md mentions "restore to PC
  share", but this share is read-only and pull-only, so nothing can be
  written back through it. MVP.md F8 restores to a new folder instead. How
  restored data reaches Laptop A is decided with the Vault, not here.
