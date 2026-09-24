# ADR-0013: Demo controls live on the Live Demo page, not over every screen

**Date:** 24 Sept 2026
**Status:** Accepted. Amends ADR-0011.

## Context

ADR-0011 put the demo controls (simulated attack, fresh run) in a panel fixed
to the bottom left of every page, and the harvest surge switch in the blue
utility strip. In the pre-deployment review, judged the way a Round 2 judge
would see it, both hurt the product:

- The floating panel covered the PDS screens themselves: search results, the
  card detail, the incident report. It made the office's own system look
  like a test harness.
- A demo switch in the GIGW utility strip sits beside the accessibility and
  language controls, where a real government portal has nothing of the kind.
- "Full MVP Demo" is hackathon shorthand, not a name a District Supply
  Office would put in its navigation.

## Decision

- **The floating demo controls are removed from every page.** No office
  screen carries a demo window or a demo switch.
- **The same controls move, unchanged in behaviour, to the Live Demo page**
  as a "Step-by-step controls" panel beside the guided demo: the harvest
  surge switch, the attack picker with "Launch simulated attack", and
  "Restart from day 1". The routes (`/live/attack`, `/live/harvest-surge`,
  `/live/reset`) and the session they drive are untouched.
- **"Full MVP Demo" is renamed "Live Demo"** in the nav, and its one button
  "Run Full MVP Demo" becomes "Start guided demo". "Start a fresh run"
  becomes "Restart from day 1", which says what it does.
- The Live Demo page refreshes once per simulated day (the `day` scope), not
  on every status write, so the page is not reloaded under someone using its
  controls. The status line and the attack button still update in place.

## What this does not change

- Rules 1, 2 and 3, the live engine, the Judge, the Vault and the office
  pop-up (which still never waits on OK).
- Every other screen still follows the live session and reloads when what it
  shows changes.
