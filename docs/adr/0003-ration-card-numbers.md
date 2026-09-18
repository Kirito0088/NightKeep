# ADR-0003: 12-digit numeric ration card numbers, not RC- IDs

**Status:** Accepted. Overrides `MVP.md` F1 and `SOLUTION_DESIGN.md` Step 8.
**Date:** 18 September 2026

## Context

Both documents specify `RC-` style identifiers. `MVP.md` F1: "5,000 fake beneficiaries (`RC-` IDs, no Aadhaar-format numbers)". `SOLUTION_DESIGN.md` Step 8: "Ration card numbers are made-up `RC-` IDs. No Aadhaar-format numbers."

Real Indian PDS systems do not use that format. A Maharashtra ration card number is a plain 12-digit number with no prefix and no dashes. Three of the seven console screens are the PDS system itself, and a judge who has seen a real ration card will notice an invented identifier immediately. The whole point of those screens is that they look like the thing being attacked.

The obvious objection: an Aadhaar number is also 12 digits, and both documents forbid Aadhaar-format numbers. A naive 12-digit generator could emit something Aadhaar-shaped.

## Decision

Ration card numbers are **12-digit numeric, no prefix, no dashes**, e.g. `110300512847`.

The first two digits are fixed at **`11`**. An Aadhaar number never begins with 0 or 1, so no number this generator can produce falls in the Aadhaar range. The "no Aadhaar-format numbers" requirement in both documents is therefore satisfied by construction, not by chance.

Aadhaar itself is stored as a **seeded yes/no per member**. There is no field named `aadhaar_no` and no 12-digit Aadhaar-shaped value is generated anywhere in the codebase.

## Consequences

- `MVP.md` F1 and `SOLUTION_DESIGN.md` Step 8 are superseded on the identifier format. The "no Aadhaar-format numbers" half of both sentences still stands and is now enforced by the leading-digit rule.
- A test asserts that no generated ration card number begins with a digit in 2 to 9, and that no field named `aadhaar_no` exists in the schema.
- `mock_pds/conventions.py` is the single home for the prefix, so no generator or template can drift from it.
- Restore verification counts **ration cards**, not members. "5,000 / 5,000" in `MVP.md` P4 means 5,000 ration card rows.
