# ADR-0006: Model the prototype on the real Thane district, not an invented one

**Date:** 18 Sept 2026
**Status:** Accepted

## Context

Every prior document (CLAUDE.md, CONTEXT.md, `docs/design/mockup-log.md`)
named the district Kesargaon, invented on purpose. The mockup log records why,
from the very first build: *"A mockup that imitates a real government body is
a different thing from a mockup that looks governmental, and only the second
one is safe to show and share."* CLAUDE.md carried this as a hard safety
rail: "The district is invented."

The team asked to switch to the real Thane district so the demo "feels real."
Before making the change, that reasoning was put back to the team: an
invented district exists specifically so 5,000 fake ration cards, fake
officer names, and a simulated ransomware attack cannot be mistaken for real
Thane PDS data, even with the "Prototype on invented data. Not a live
government system." disclaimer on every screen. The team heard this and
confirmed the change anyway.

## Decision

**The district and its talukas are real. Everything else stays invented.**

- District: **Thane**, Maharashtra.
- Talukas modelled: **Thane** and **Kalyan**, both real talukas of the real
  district. Thane district has more (Bhiwandi, Ulhasnagar, Ambarnath, Murbad,
  Shahapur), but the prototype keeps the original two-taluka scope; Thane and
  Kalyan are its largest and most recognisable, chosen for that reason.
- Every ration card, member, FPS shop, ePoS transaction, officer name, and
  address stays exactly as invented as before. No real person, no real shop,
  no real card exists. **Only the geographic and administrative names are
  real.**
- The other rails under "No real personal data anywhere, ever" are
  unchanged and still bind: names come from a fixed invented pool, no
  Aadhaar-shaped number is ever generated, mobile numbers stay masked.

This narrows, rather than removes, the "district is invented" rail from
CLAUDE.md: the rail now reads "no real personal data", full stop, and no
longer extends to the district's own name.

## Consequences

- `CLAUDE.md`'s PDS data conventions table and hard safety rails are updated:
  the district row now names Thane and Kalyan; the "district is invented"
  clause is removed from the safety rail, since it no longer holds.
- `CONTEXT.md`'s domain vocabulary entry for the district is rewritten
  accordingly.
- Ticket #2 (F1: generate the district) is retitled and its acceptance
  criteria updated to build Thane, not Kesargaon.
- **The Claude Design canvas is now stale.** All seven artboards still show
  "Kesargaon", "जिल्हा पुरवठा कार्यालय, केसरगाव" and "Kesargaon / Nandori" in
  their markup. `mock_pds` will generate Thane data once #2 lands, and the
  console (a later ticket) will render whatever `mock_pds` produces, so the
  console itself will show Thane correctly. But the canvas's own screenshots
  and its written log (`docs/design/mockup-log.md`) still describe Kesargaon
  as built, because they are a historical record of what was actually made,
  not source code. The canvas has not been edited under this ADR; that is a
  separate task if the team wants the mockups themselves to read Thane.
- `docs/design/mockup-log.md` is not rewritten. It stays an accurate account
  of what the mockups contained at each version. A note is added pointing
  here instead.
