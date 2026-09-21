# Contributing to Nightkeep

Nightkeep is a four-day prototype for MUSA CodeX 2026, and it is built to a
tight set of rules on purpose. This file is the short version; the full
reasoning lives in [`CLAUDE.md`](CLAUDE.md) and [`CONTEXT.md`](CONTEXT.md).

## The three rules that never bend

1. The learned habit score never pauses, locks or deletes anything on its own.
   Every INCIDENT verdict needs at least one fixed canary or recovery signal.
2. Canary signals (S2–S7) are never learned. They are hard-coded and live from
   minute one, and no learning path may widen them.
3. The PDS server never gets a path, credential or address for the Vault. The
   Vault always opens the connection.

Each rule has a test that fails if it is broken. **If a change would break one
of these rules, it does not go in.**

## How to work here

- **Plan first.** Say what you are going to change before you change it.
- **One feature per commit, tests alongside it.** Run the tests yourself before
  saying something works.
- **Match the surrounding code.** Absolute, package-qualified imports
  (`from nightkeep.habit import score`). Deep modules, shallow glue: no
  pass-through layers, no interface as complicated as the thing it hides.
- **Every tunable number lives in `config.yaml`.** Modules take values as
  arguments; they never reach for config themselves.
- **Use the vocabulary in [`CONTEXT.md`](CONTEXT.md).** Say *canary signal*,
  not "tripwire"; *file-locking threat*, not "ransomware"; *scramble*, not
  "encrypt". The console's main path uses counter-clerk language.
- **When a change touches data shape or the console UI, check the mockups
  first** (the design canvas and `docs/design/mockup-log.md`).

## Environment

- **Python 3.11** (`python` on the build machine; `py` is 3.14 and is not the
  target).
- Standard library first, then `watchdog`, `psutil`, `numpy`/`pandas`,
  `sqlite3`, `hashlib`, `PyYAML`, and Flask + Jinja + hand-written CSS for the
  console. No Docker, no cloud, no GPU, no deep learning.

```bash
python -m pip install -e ".[dev]"
python -m pytest                 # the whole suite
python -m pytest -m "not slow"   # skip filesystem, subprocess and clock tests
```

## Tests

- Tests land with the module they cover.
- A test that guards a rule must fail when the rule is broken. Do not write a
  vacuous test that passes because the thing it guards does not exist yet;
  confirm it by breaking the behaviour and watching it fail.
- Mark a test `@pytest.mark.slow` when it touches the filesystem, a subprocess
  or the simulated clock.

## Commits

- Write commit messages that say **why**, not just what.
- Do not add `Co-Authored-By` lines.

## Safety

This repository models a security scenario on **entirely invented data**. Keep
it that way: no real personal data, no Aadhaar-shaped numbers, and the threat
simulator stays safe by construction (reversible, contained to a demo district,
and never executing a system command).
