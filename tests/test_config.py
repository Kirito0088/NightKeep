"""The config loader is the only thing in Nightkeep that reads config.yaml.

Expected values come from the ticket, docs/MVP.md section 6 and CONTEXT.md,
never from re-running the loader's own arithmetic.
"""

from datetime import time
from pathlib import Path

import pytest
import yaml

from nightkeep.config import ConfigError, load_config

REPO_CONFIG = Path(__file__).resolve().parent.parent / "nightkeep" / "config.yaml"


def _edited(tmp_path: Path, section: str, edit) -> Path:
    """The repo's own config.yaml with one key changed. Nothing else moves."""
    raw = yaml.safe_load(REPO_CONFIG.read_text(encoding="utf-8"))
    edit(raw[section])
    written = tmp_path / "config.yaml"
    written.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return written


def _config_without(tmp_path: Path, section: str, key: str) -> Path:
    return _edited(tmp_path, section, lambda block: block.pop(key))


def _config_with(tmp_path: Path, section: str, key: str, value) -> Path:
    return _edited(tmp_path, section, lambda block: block.__setitem__(key, value))



def test_repo_config_gives_the_district_f1_needs():
    config = load_config(REPO_CONFIG)

    assert config.district.ration_cards == 5000
    assert config.district.fps_count == 50


def test_a_missing_key_fails_at_startup_and_names_the_key(tmp_path):
    broken = _config_without(tmp_path, "district", "fps_count")

    with pytest.raises(ConfigError) as raised:
        load_config(broken)

    assert "district.fps_count" in str(raised.value)


def test_a_mistyped_value_fails_at_startup_and_names_the_key(tmp_path):
    broken = _config_with(tmp_path, "district", "ration_cards", "five thousand")

    with pytest.raises(ConfigError) as raised:
        load_config(broken)

    assert "district.ration_cards" in str(raised.value)


def test_a_key_nightkeep_does_not_know_fails_rather_than_being_ignored(tmp_path):
    typo = _config_with(tmp_path, "district", "fps_cont", 50)

    with pytest.raises(ConfigError) as raised:
        load_config(typo)

    assert "district.fps_cont" in str(raised.value)


def test_unreadable_or_malformed_yaml_fails_at_startup(tmp_path):
    missing = tmp_path / "nowhere.yaml"
    with pytest.raises(ConfigError):
        load_config(missing)

    malformed = tmp_path / "config.yaml"
    malformed.write_text("district:\n  ration_cards: [unclosed\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(malformed)


def test_repo_config_gives_the_clock_and_seed_f2_needs():
    config = load_config(REPO_CONFIG)

    # CONTEXT.md and ADR-0012: one simulated day is 10 s, 7 learning days
    # then 3 guard days. The seed is what lets a judge replay a run exactly.
    assert config.clock.simulated_day_seconds == 10
    assert config.clock.learning_days == 7
    assert config.clock.guard_days == 3
    assert isinstance(config.seed, int)


def test_repo_config_surges_once_while_learning_and_once_while_guarding():
    config = load_config(REPO_CONFIG)

    assert config.harvest_surge.multiplier == 2.0
    learning = config.clock.learning_days
    assert any(day <= learning for day in config.harvest_surge.days)
    assert any(day > learning for day in config.harvest_surge.days)


def test_repo_config_gives_every_job_its_own_hours_and_variation():
    config = load_config(REPO_CONFIG)
    jobs = config.jobs

    # docs/MVP.md section 6: the day-end export starts anytime 01:00 to 02:30
    # and its row count moves plus or minus 30 percent with the day's sales.
    assert jobs.nightly_export.start_window.earliest == time(1, 0)
    assert jobs.nightly_export.start_window.latest == time(2, 30)
    assert jobs.nightly_export.volume_variation == 0.30

    # Clerks edit records in office hours, and never on a Sunday.
    assert jobs.operator_activity.start_window.earliest == time(10, 0)
    assert jobs.operator_activity.start_window.latest == time(17, 0)
    assert jobs.operator_activity.skip_sundays is True

    # The zip-and-delete job only runs when the folder crosses a size limit,
    # which is what makes it fire on random nights.
    assert jobs.archive_old.size_threshold_kb > 0

    # The database backup runs after the export, so its start time drifts with
    # the export rather than sitting in a window of its own.
    assert jobs.db_backup.delay_after_export_minutes.low >= 0
    assert (
        jobs.db_backup.delay_after_export_minutes.high
        >= jobs.db_backup.delay_after_export_minutes.low
    )


def test_repo_config_gives_the_household_detail_f1_needs():
    config = load_config(REPO_CONFIG)

    assert config.district.members_per_card.low >= 1
    assert config.district.members_per_card.high >= config.district.members_per_card.low
    assert config.district.transactions_per_card_per_month.high >= 1


def test_a_start_window_that_is_not_a_time_fails_at_startup(tmp_path):
    broken = _edited(
        tmp_path,
        "jobs",
        lambda jobs: jobs["fix_dat"]["start_window"].__setitem__("earliest", "half two"),
    )

    with pytest.raises(ConfigError) as raised:
        load_config(broken)

    assert "jobs.fix_dat.start_window.earliest" in str(raised.value)


def test_config_yaml_is_read_exactly_once_per_startup(monkeypatch):
    reads: list[Path] = []
    real_read_text = Path.read_text

    def counting_read_text(self, *arguments, **keywords):
        reads.append(self)
        return real_read_text(self, *arguments, **keywords)

    monkeypatch.setattr(Path, "read_text", counting_read_text)
    load_config(REPO_CONFIG)

    assert reads == [REPO_CONFIG]


def test_repo_config_starts_each_simulated_day_before_the_shops_open():
    config = load_config(REPO_CONFIG)

    # A simulated day is one shop day followed by its night, so it must start
    # after the last night job and before the shops open (09:00).
    last_night_job = max(
        job.start_window.latest
        for job in vars(config.jobs).values()
        if hasattr(job, "start_window") and job.start_window.latest < time(9, 0)
    )
    assert last_night_job < config.clock.day_starts_at <= time(9, 0)
