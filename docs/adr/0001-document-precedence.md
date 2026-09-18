# ADR-0001: MVP.md wins over SOLUTION_DESIGN.md

**Status:** Accepted
**Date:** 18 September 2026

## Context

Three documents describe Nightkeep and they do not fully agree:

- `docs/SOLUTION_DESIGN.md` (16 Sept 2026), the full design blueprint, written under the earlier working name QuirkGuard.
- `docs/MVP.md` v5 (16 Sept 2026), which states it builds on the design blueprint and narrows it to what is buildable in four days.
- The Session 1 kickoff prompt (18 Sept 2026), the most specific about module boundaries and data conventions.

Known disagreements at the time of writing: number of erratic jobs (3 vs 6), learning period (5 nights vs 7 days plus 3 guard days), simulated day length (20 s vs 30 s), console reachability (LAN web page vs the Vault's own screen), product name (QuirkGuard vs Nightkeep).

Without a standing rule, every one of these costs a round trip.

## Decision

Precedence order is **`MVP.md` > `SOLUTION_DESIGN.md` > kickoff prompt**, except where an ADR records a deliberate override.

`MVP.md` wins because it is the later document, it explicitly states it builds on the blueprint, and it already reverses the blueprint in at least one place on purpose: section 8 replaces the LAN-reachable console with a console that exists only on the Vault's own screen, and gives the security reason.

`SOLUTION_DESIGN.md` remains authoritative for everything `MVP.md` does not cover, which is most of the threat model, the signal definitions and the research citations.

## Consequences

- The job count is 6, the learning period is 7 plus 3 days, a simulated day is 30 s, the console is loopback-only, and the product is Nightkeep. These follow from the rule and need no further ADR.
- Two conflicts were decided against this order and are recorded as ADR-0002 and ADR-0003.
- `SOLUTION_DESIGN.md` is not rewritten to match. It is a design record, and rewriting history would lose the reasoning. Where it is superseded, the superseding ADR says so.
