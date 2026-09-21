"""Both configured traps flow through the whole pipeline, from the same file.

Regression for the config path fix: the second trap used to be
``allocations/fps_quota_2024_01.csv`` -- outside ``share/``, the one folder
the PDS server shares with the Vault. The simulator would encrypt it, but
the Vault pull, the read-only containment scope, and the restore proof never
saw it. This test reads the traps straight out of ``config.yaml`` and pins
all four stages for both of them:

  1. the Judge's ``plant_traps()`` creates both files under share/
  2. the simulator's target scan reaches both
  3. a Vault pull includes both (no exclusion rule skips them)
  4. a Vault restore materializes both back to disk
"""

import shutil
from datetime import datetime, timedelta
from pathlib import Path

from nightkeep.config import load_config
from nightkeep.habit import Habit
from nightkeep.judge import Judge
from nightkeep.simulator import fast_encrypt
from nightkeep.types import Event, JobRun
from nightkeep.vault import Vault, _manifest

REPO_CONFIG = Path(__file__).resolve().parent.parent / "nightkeep" / "config.yaml"

# The traps exactly as the demo ships them: no local copy of the paths.
CONFIGURED_TRAPS = tuple(load_config(REPO_CONFIG).judge.canary_files)


def _judge(root: Path, habit_db: Path | None = None) -> Judge:
    return Judge(
        root=root,
        habit=Habit(habit_db or (root / "habit.db"), 3.0, 3, 0.10),
        odd_score=0.5,
        rename_burst=10,
        entropy_jump=1.5,
        entropy_floor=7.0,
        recovery_commands=(),
        canary_files=CONFIGURED_TRAPS,
    )


def test_config_traps_both_live_under_share() -> None:
    """The path correction itself: every configured trap is inside share/."""
    assert len(CONFIGURED_TRAPS) == 2
    for trap in CONFIGURED_TRAPS:
        assert trap.startswith("share/"), f"trap outside the Vault's reach: {trap}"


def test_judge_plants_every_configured_trap(tmp_path: Path) -> None:
    root = tmp_path / "district"
    root.mkdir()
    judge = _judge(root)
    try:
        planted = judge.plant_traps()
        assert {p.relative_to(root).as_posix() for p in planted} == set(
            CONFIGURED_TRAPS
        )
        for trap in CONFIGURED_TRAPS:
            assert (root / trap).is_file()
    finally:
        judge.undo()


def test_simulator_reaches_every_configured_trap() -> None:
    """The simulator's scan is the same rglob over the demo root, so a trap
    the scan misses would be a hole the proof would never notice."""
    import uuid

    import nightkeep.simulator as simulator

    base = simulator.DEMO_DIR / ".trap-path-tests" / uuid.uuid4().hex
    root = base / "district"
    root.mkdir(parents=True)
    # The habit database lives outside the simulator's root: otherwise the
    # drill would encrypt it and the "every target is a trap" assertion
    # below would be polluted by the Judge's own scratch file.
    judge = _judge(root, habit_db=base / "habit.db")
    try:
        judge.plant_traps()
        report = fast_encrypt(
            root,
            key="trap-path-drill",
            locked_extension=".locked",
            ransom_note_name="READ_ME.txt",
            delay_between_files_seconds=0.0,
        )
        locked = {
            p.relative_to(root).as_posix()
            for p in root.rglob("*.locked")
            if p.is_file()
        }
        assert report.files_encrypted == 2, report
        assert locked == {trap + ".locked" for trap in CONFIGURED_TRAPS}
    finally:
        judge.undo()
        shutil.rmtree(base, ignore_errors=True)


def test_vault_pull_and_restore_cover_every_configured_trap(
    tmp_path: Path,
) -> None:
    """Pull stores both traps; restore writes both back, hashes verified."""
    root = tmp_path / "district"
    share = root / "share"
    judge = _judge(root)
    judge.plant_traps()
    vault = Vault(
        root=tmp_path / "vault",
        share=share,
        suspect_entropy=7.0,
        suspect_changed_fraction=0.5,
        suspect_record_drop_fraction=0.02,
        restore_folder_name="restored",
    )
    snapshot = vault.pull(taken_at=datetime(2026, 9, 21, 12, 0, 0))
    assert snapshot.health == "CLEAN"

    # The pull stage: the Vault reads everything under share/, so both traps
    # must be in the snapshot manifest with their share-relative paths.
    manifest = _manifest.read_manifest(vault._root, snapshot.snapshot_id)
    expected = {trap.removeprefix("share/") for trap in CONFIGURED_TRAPS}
    assert set(manifest["files"]) >= expected

    # The restore stage: the restored folder must contain both, byte-identical
    # to what was planted. The restore's own hash checks verify every file's
    # content against the manifest, so matching bytes here is the full proof.
    # (Manifest and restore paths are share-relative; the "share/" prefix of
    # the configured trap paths has to be dropped for the comparison.)
    result = vault.restore(snapshot.snapshot_id)
    restored = Path(result.restored_to)
    assert result.snapshot_id == snapshot.snapshot_id
    for trap in CONFIGURED_TRAPS:
        rel = trap.removeprefix("share/")
        assert (restored / rel).is_file()
        assert (restored / rel).read_bytes() == (root / trap).read_bytes()


def test_judge_s2_fires_on_the_second_trap_too(tmp_path: Path) -> None:
    """The moved trap still trips S2 on touch: the path fix must not have
    made the simulator's target and the Judge's tripwire disagree."""
    at = datetime(2026, 9, 21, 12, 0, 0)
    root = tmp_path / "district"
    root.mkdir()
    judge = _judge(root)
    judge.plant_traps()
    try:
        trap = root / CONFIGURED_TRAPS[1]
        trap.write_bytes(b"tampered")
        run = JobRun(
            job="nightly_export",
            identity="nightly_export:fake",
            started_at=at,
            finished_at=at + timedelta(seconds=30),
            events=(),
            sim_started_at=at,
            day_no=8,
        )
        event = Event(
            path=trap.relative_to(root).as_posix(),
            kind="modified",
            at=at,
            pid=None,
        )
        verdict = judge.verdict(run, events=[event])
        assert verdict.level == "INCIDENT"
        assert "S2" in {signal.code for signal in verdict.signals}
    finally:
        judge.undo()
