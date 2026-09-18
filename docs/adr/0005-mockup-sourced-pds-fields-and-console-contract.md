# ADR-0005: PDS fields the mockups need, and the console's contract with the canvas

**Date:** 18 Sept 2026
**Status:** Accepted

## Context

The team built a 7-artboard Claude Design canvas, "Nightkeep Prototype
Screens" (https://claude.ai/artifact/Gye9zkkioeiLxXLUgiMbMw), across versions
1 to 13, recorded in full at `docs/design/mockup-log.md`. It is the reference
the console gets built against, not decoration.

Two gaps surfaced when the mockups were checked against the tracker:

1. `Main.dc.html` (search) and `PdsCard.dc.html` (card detail) use six data
   fields that never made it into `docs/MVP.md`, `CLAUDE.md`'s PDS data
   conventions table, or ticket #2's acceptance criteria: card status, card
   type, address, village, card issue date, and ePoS transaction status.
   Unlike the fields in the mockup log's v4 table (card number format, FPS
   ID, scheme names, entitlement, PMGKAY pricing, Aadhaar handling, district
   and taluka names), these six were never checked against a real-world
   source during the mockup pass.
2. Every screen in the mockups carries the line "Prototype on invented data.
   Not a live government system." in its top strip. Nothing in `CLAUDE.md` or
   `CONTEXT.md` requires it, so a rebuild of the console could silently drop
   it.

Card type specifically read "Priority (white)" for an NFSA-PHH card in the
mockup. Real Indian ration-card colour codes vary by state and are not one of
the conventions this team has sourced (contrast: the AAY/NFSA-PHH/Kesari(APL)
scheme names in `CLAUDE.md` already are). Publishing an unverified colour on
a screen judges will read is the same mistake the v4 pass fixed for card
numbers and FPS IDs.

## Decision

**Six fields are added to the PDS data conventions and to ticket #2:**

| Field | Convention |
|---|---|
| Card status | `Active` or `Suspended`. Seeded per card; a small minority suspended, enough that a search can return one |
| Card type | The scheme's own official name is the card type label (`Priority Household` for NFSA-PHH, `Antyodaya` for AAY, `Kesari` for Kesari (APL)). **No colour is printed.** The colour-coding claim in the mockup ("Priority (white)") is dropped as unsourced; see Consequences |
| Address | A generated street-level line: plot/house number, a locality name from a fixed invented pool, the card's taluka. No real street data |
| Village | A field distinct from taluka, drawn from a fixed invented pool per taluka, matching the mockup's "Taluka / Village" split |
| Card issue date | A seeded date, plausible for an active PDS card (multi-year range ending before the simulated present) |
| Transaction status | `Collected` or `Part collected` on an ePoS transaction row, seeded so most rows are `Collected` |

All six are constants and generation rules in `mock_pds/conventions.py`,
alongside the fields ticket #2 already specifies. No generator and no
template keeps its own copy.

**The disclaimer line is a standing UI rule.** "Prototype on invented data.
Not a live government system." appears in the top utility strip of every
console screen. Added to `CLAUDE.md`'s hard safety rails.

**The canvas is the console's source of truth.** Building or changing any of
the seven console screens starts by reading the relevant artboard(s) from the
canvas and `docs/design/mockup-log.md`, not by working from CLAUDE.md's UI
direction prose alone. The same rule applies to `mock_pds` whenever a screen
implies a data field: check the mockups before inventing a shape.

## Consequences

- Ticket #2's acceptance criteria gain the six fields above.
- `mock_pds/conventions.py` (not yet written) must define all six alongside
  the fields already specified, as one module, per the existing "every
  generator and every template uses that file" rule.
- The card-colour claim in the mockup is superseded: the console renders the
  scheme's official name, not a colour. If a sourced colour convention is
  found later, this ADR is revised rather than the mockup silently trusted.
- `CLAUDE.md`'s PDS data conventions table, hard safety rails, and "How to
  work in this repo" section are updated to reflect all of the above.
- `CONTEXT.md` gains the two new domain nouns (card status, village) that
  did not previously exist in the vocabulary.
