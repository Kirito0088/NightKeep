# ADR-0008: Console UI presentation boundary and copy rules

**Date:** 18 Sept 2026
**Status:** Accepted

## Context

Ticket #7 landed the 7 console screens and popup into `nightkeep/console/` on `main`.
During review against `docs/design/mockup-log.md` and `CLAUDE.md`, two UI drifts were
caught and fixed:
1. `locked.html:206` contained the word "snapshots" on the clerk-facing main path.
2. `style.css:71` used the active-tab orange for the skip-link focus outline.

The console represents the primary visual surface evaluated by judges in Round 2.
To prevent future drift when backend modules (`habit`, `judge`, `vault`) are wired in,
the architectural boundary and presentation rules must be formally recorded.

## Decision

1. **Strict presentation layer**:
   - `nightkeep/console/app.py` contains only Flask route handlers and Presentation
     dataclasses.
   - It renders plain-language strings and metrics computed by deep backend modules.
   - It never computes scores, medians, MAD, hashes, or verdicts itself.

2. **Network binding**:
   - The console runs strictly locally on the Vault screen bound to loopback `127.0.0.1:5000`.
   - It must never bind to `0.0.0.0` or expose routes over the LAN (ADR-0002).

3. **Clerk-facing plain language**:
   - The main path is written for a counter clerk and District Supply Officer.
   - Technical terms ("snapshot", "manifest", "habit score", "entropy", "SHA-256",
     "MAD", "verdict") are forbidden on the main path.
   - Any technical inspectability must be gated behind "For the IT person" sections.

4. **Visual tokens and color discipline**:
   - Orange (`#b0451a`) marks the active navigation tab and nothing else.
   - Semantic state colors (`#1a6b3c` green, `#8a5200` amber, `#9b2226` red) reflect
     real system state only, never decorative badges.
   - Square corners (`border-radius: 0`) throughout. No drop shadows, except for the
     modal server alert pop-up.
   - Zero em-dashes anywhere in UI copy.
   - Mandatory top disclaimer strip on every template:
     "Prototype on invented data. Not a live government system."

## Consequences

- The backend can evolve its detection algorithms and storage engines without breaking
  or complicating template rendering.
- UI compliance can be verified mechanically in tests (e.g. `tests/test_console.py`).
- Feature branches carrying draft presentation code remain isolated from backend logic.
