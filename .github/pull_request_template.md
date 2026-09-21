## What this changes

<!-- One or two sentences. What and why. -->

## The three rules

- [ ] The learned habit score still cannot pause, lock or delete on its own.
- [ ] Canary signals (S2–S7) are still hard-coded and unlearned.
- [ ] The PDS server still holds no path, credential or address for the Vault.

## Checklist

- [ ] One feature, tests alongside it.
- [ ] `python -m pytest` passes locally.
- [ ] Every new tunable number lives in `config.yaml`.
- [ ] Vocabulary matches `CONTEXT.md` (canary signal, file-locking threat, scramble).
- [ ] If this touches data shape or the console UI, the mockups were checked first.
