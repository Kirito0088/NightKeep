# ADR-0002: Flask and Jinja for the console, not Streamlit

**Status:** Accepted. Overrides `MVP.md` F9 and section 9.
**Date:** 18 September 2026

## Context

`MVP.md` F9 and its tech stack name **Streamlit** for the console. `SOLUTION_DESIGN.md` is looser: "Streamlit for the console (fastest for our team) or Flask if we need more control", and its prototype feature list says "Console (Streamlit or Flask)". So the blueprint already permits Flask.

Two things pushed the decision:

1. The console must render seven specific screens in GIGW house style: blue utility strip, tri-colour hairline, district seal, bilingual header, navy nav with one orange active tab, dense bordered tables, labels above inputs, square corners throughout. Three of those screens are the **PDS system itself**, which is what the ransomware attacks and what makes the demo legible to a judge. Streamlit does not give control over markup at that level without fighting the framework.
2. `MVP.md`'s own risk table lists "Streamlit refresh lag looks slow on stage", with a pre-recorded video as the fallback. Choosing a framework whose named risk is "looks slow during the demo" is avoidable.

## Decision

The console is **Flask + Jinja templates + hand-written CSS**. No Streamlit, no React, no Node, no build step. It binds to `127.0.0.1` only and must not listen on the LAN.

`console` stays a deliberately shallow module: routes and template context, nothing else. All reasoning strings arrive pre-built inside `HabitScore`, `Verdict` and `RestoreResult`.

## Consequences

- `MVP.md` F9 and section 9 are superseded on this point. The rest of F9 stands.
- The "Streamlit refresh lag" risk row in `MVP.md` section 14 no longer applies. A recorded backup run is still worth keeping for other reasons.
- Loopback-only binding satisfies `MVP.md` section 8 ("the Console exists only on the Vault's own screen") and rule 3 at the same time.
- Hand-written CSS is more work than Streamlit defaults. That cost is accepted, because the house style is what stops the UI reading as generic.
