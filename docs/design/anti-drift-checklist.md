# Console UI anti-drift checklist

Reference checklist for creating or modifying templates in `nightkeep/console/`.
Derived from `CLAUDE.md`, `docs/design/mockup-log.md`, `ADR-0005`, and `ADR-0008`.

Before opening a pull request or committing changes to `nightkeep/console/`, verify
each of the following checks.

---

## 1. Main path copy and terminology

- [ ] **Clerk-facing plain language**: Is the screen written for a counter clerk or District Supply Officer?
- [ ] **Technical jargon check**: Ensure the following terms never appear on the main path:
  - `snapshot` (say "safe copy" or "record")
  - `manifest` (say "backup list")
  - `entropy` (say "scrambled files")
  - `SHA-256` / `hash` (say "fingerprint" or "check")
  - `MAD` / `median` (say "usually" or "expected range")
  - `verdict` (say "status" or "report")
- [ ] **Gating**: Any technical details must sit behind a link or section titled "For the IT person".
- [ ] **PDS conventions**: Ration card numbers are 12 digits (ADR-0003), never `RC-` format. No Aadhaar numbers anywhere. PMGKAY foodgrain is marked free.

---

## 2. Color token discipline

- [ ] **Active tab orange (`#b0451a`)**: Used strictly for the active navigation tab (`.nav-tab.active`) and nothing else. Never used on buttons, links, borders, or focus outlines.
- [ ] **System navy (`#14387f`)**: Used for system headers, links, and keyboard focus outlines (`:focus-visible`).
- [ ] **Semantic state colors**:
  - Green (`#1a6b3c`): Normal, verified, safe.
  - Amber (`#8a5200`): Odd, needs review, warning.
  - Red (`#9b2226`): Incident, attack detected, locked.
  - Never use these colors for purely decorative badges or unverified status.

---

## 3. Layout, geometry, and styling

- [ ] **Square corners**: `border-radius: 0` on every container, button, input, badge, and card.
- [ ] **No drop-shadows**: `box-shadow: none` across all components. The sole exception is the modal dialog on Screen 7 (`ServerAlert.dc.html`).
- [ ] **Typography**: Noto Sans for Latin, Noto Sans Devanagari for Marathi header text. Hierarchy is established through weight, not extreme font-size jumps.
- [ ] **Table alignment**: Tabular numbers enabled (`font-variant-numeric: tabular-nums`) with consistent numeric right-alignment.

---

## 4. Mechanical checks

- [ ] **Zero em-dashes**: Search the template copy for em-dashes (`—`). Use a full stop or comma instead.
- [ ] **Government header chrome**:
  - Blue utility strip with accessibility controls (Skip link, text resize, language toggle).
  - Tri-colour saffron-white-green hairline.
  - District seal placeholder and bilingual header text ("District Supply Office, Thane").
- [ ] **Mandatory disclaimer**: Every screen must carry the exact strip:
  `"Prototype on invented data. Not a live government system."`

---

## 5. Network safety

- [ ] **Loopback only**: Entrypoint in `nightkeep/console/__main__.py` binds to `127.0.0.1:5000`. Never bind to `0.0.0.0` or expose the console to the office LAN.
