"""Plain dataclasses shared across the PDS server / Vault boundary.

The only thing allowed to cross that line. Nothing here carries state, holds a
connection or reaches for config. Each type lands with the ticket that needs
it: HabitScore with habit, Verdict with judge, RestoreResult with vault.
"""
