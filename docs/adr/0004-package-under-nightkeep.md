# ADR-0004: Code lives under `nightkeep/`, not at the repository root

**Date:** 18 Sept 2026
**Status:** Accepted

## Context

CLAUDE.md's folder layout lists `types.py`, `config.yaml`, `tests/` and
`CLAUDE.md` itself inside a `nightkeep/` directory. Because `CLAUDE.md`,
`CONTEXT.md` and `docs/` already sat at the repository root, the layout read as
"the repository root is `nightkeep/`", and the code was written that way first.

That reading does not work. Python's standard library has
a module named `types`. `functools` imports it, and `functools` is imported
during interpreter start-up. With the repository root on `sys.path`, a
root-level `types.py` shadows the standard library and every Python process in
the repository fails before running a line of our code:

```
ImportError: cannot import name 'GenericAlias' from 'types'
```

Renaming the file was the alternative, but `types.py` is the name CLAUDE.md
gives the shared dataclass module, and CONTEXT.md's boundary rule refers to it.

## Decision

`nightkeep/` is a package directory inside the repository root. All code lives
under it: `nightkeep/types.py`, `nightkeep/config.py`, `nightkeep/config.yaml`,
`nightkeep/mock_pds/`, `nightkeep/watcher/`, `nightkeep/habit/`,
`nightkeep/judge/`, `nightkeep/vault/`, `nightkeep/console/`,
`nightkeep/simulator/`.

`CLAUDE.md`, `CONTEXT.md`, `docs/`, `tests/` and `pyproject.toml` stay at the
repository root, which is a second departure from the layout block: that block
draws `CLAUDE.md` and `tests/` inside `nightkeep/`. Both stay out, because
CLAUDE.md and CONTEXT.md are read before anyone opens the code, and because a
`tests/` outside the package lets the config locality guard walk the whole
package without having to exclude itself. Imports are absolute and package-qualified:
`from nightkeep.config import load_config`.

## Consequences

- The standard library is no longer shadowed. This is the whole point.
- Module names in CLAUDE.md's public-interface table are unchanged. Only the
  prefix moves. `judge` still calls `habit.score(run)`, now written
  `from nightkeep.habit import score`.
- `config.yaml` sits next to the loader that reads it, which makes the "read
  once, by one loader" rule visible in the layout.
- Tests stay outside the package at `tests/`, so the locality guard can walk
  the package directory without excluding itself.
- **CLAUDE.md's folder-layout block is updated by this ADR** to draw the
  repository root with `nightkeep/` inside it. The module names and the public
  interface table are untouched.
