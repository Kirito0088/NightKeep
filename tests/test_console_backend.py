"""The console wired to real backend state: the F8+F9 task.

Real generated districts, a real habit database, a real judge verdict and
real vault snapshots drive the presentation layer. Nothing here asserts on
mock copy: every value rendered comes from a module's own public API.
"""

import csv
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from nightkeep.config import District, Span
from nightkeep.console.app import create_app
from nightkeep.console.providers import (
    PdsProvider,
    PinRejected,
    RestoreService,
    alert_presentation,
    calm_alert,
    first_incident,
    habit_tasks,
    newest_clean_before,
    restore_result_wizard,
    restore_service_for,
    restore_wizard,
    safety_home,
    server_alert,
    verdict_record_from_live,
    verdicts_from_report,
)
from nightkeep.habit import Habit
from nightkeep.judge import Judge
from nightkeep.mock_pds import build_district
from nightkeep.types import INCIDENT, MODIFIED, Event, JobRun
from nightkeep.vault import Vault

SMALL = District(
    ration_cards=200,
    fps_count=10,
    members_per_card=Span(low=1, high=5),
    transactions_per_card_per_month=Span(low=0, high=2),
)
FULL = District(
    ration_cards=5000,
    fps_count=50,
    members_per_card=Span(low=1, high=7),
    transactions_per_card_per_month=Span(low=0, high=2),
)
DAY = datetime(2026, 9, 20, 2, 14, tzinfo=timezone.utc)
TRAPS = ("share/exports/epos_day_end_20240101.csv",)
PIN = "246810"


# --- fixtures: a real district, habit, judge, vault ---------------------------


def _district(tmp_path: Path, district: District = SMALL) -> Path:
    return build_district(20260921, district, tmp_path / "district")


def _habit(tmp_path: Path) -> Habit:
    return Habit(tmp_path / "habit.db", 3.0, 3, 0.10)


def _teach(habit: Habit, days: int = 7) -> None:
    for day in range(1, days + 1):
        start = DAY - timedelta(days=days - day)
        habit.learn(
            JobRun(
                job="nightly_export",
                identity="nightly_export|nightly_export.py|abc123",
                started_at=start,
                finished_at=start + timedelta(seconds=30),
                events=(
                    Event(
                        path="share/exports/epos_day_end.csv",
                        kind=MODIFIED,
                        at=start,
                        size=9_000,
                    ),
                ),
                day_no=day,
            )
        )


def _judge(tmp_path: Path, habit: Habit) -> Judge:
    judge = Judge(
        root=tmp_path,
        habit=habit,
        odd_score=0.5,
        rename_burst=10,
        entropy_jump=1.5,
        entropy_floor=7.0,
        recovery_commands=("vssadmin delete shadows",),
        trap_files=TRAPS,
    )
    judge.plant_traps()
    return judge


def _share_with_backup(district_dir: Path, cards: int = 120) -> Path:
    """The district's share with one CSV, one allocation and one db backup."""
    share = district_dir / "share"
    exports, allocations, backups = (
        share / "exports",
        share / "allocations",
        share / "backups",
    )
    with (exports / "epos_day_end_20260920.csv").open(
        "w", encoding="utf-8", newline=""
    ) as fh:
        writer = csv.writer(fh)
        writer.writerow(["card_no", "date", "qty_kg"])
        writer.writerow(["110300512847", "2026-09-20", "5.000"])
    (allocations / "alloc_27030300145_2026-09.tmp").write_text(
        "fps_id=27030300145\nallotment_month=2026-09\n", encoding="utf-8"
    )
    backup = backups / "district-backup-2026-09-20.db"
    conn = sqlite3.connect(backup)
    try:
        conn.execute("CREATE TABLE cards (id INTEGER PRIMARY KEY, name TEXT)")
        conn.executemany(
            "INSERT INTO cards (name) VALUES (?)",
            [(f"card {n}",) for n in range(cards)],
        )
        conn.commit()
    finally:
        conn.close()
    return share


def _vault(tmp_path: Path, share: Path) -> Vault:
    return Vault(
        tmp_path / "vault",
        share,
        suspect_entropy=7.0,
        suspect_changed_fraction=0.5,
        suspect_record_drop_fraction=0.02,
        restore_folder_name="restored",
    )


def _incident_run() -> JobRun:
    at = DAY + timedelta(days=8)
    return JobRun(
        job="nightly_export",
        identity="nightly_export|nightly_export.py|abc123",
        started_at=at,
        finished_at=at + timedelta(seconds=45),
        events=(
            Event(path=TRAPS[0], kind=MODIFIED, at=at, size=8),
        ),
        day_no=8,
    )


# --- PdsProvider: the real database --------------------------------------------


def test_pds_search_returns_every_card(tmp_path):
    district_dir = _district(tmp_path)
    pds = PdsProvider(district_dir / "data" / "district.db")

    results = pds.search()

    assert len(results) == 200
    assert results == sorted(results, key=lambda r: r.card_no)


def test_pds_search_all_5000_cards(tmp_path):
    district_dir = _district(tmp_path, FULL)
    pds = PdsProvider(district_dir / "data" / "district.db")

    assert len(pds.search()) == 5000
    figures = pds.district_figures()
    assert figures["ration_cards"] == "5,000"
    assert figures["fps_count"] == "50"


def test_pds_search_filters_across_the_full_dataset(tmp_path):
    district_dir = _district(tmp_path, FULL)
    pds = PdsProvider(district_dir / "data" / "district.db")

    by_scheme = pds.search(scheme="AAY")
    by_taluka = pds.search(taluka="Thane")

    assert 0 < len(by_scheme) < 5000
    assert all(r.scheme == "AAY" for r in by_scheme)
    assert 0 < len(by_taluka) < 5000
    assert all(r.taluka == "Thane" for r in by_taluka)

    one = pds.search()[0]
    assert pds.search(card_no=one.card_no) == [one]
    assert pds.search(head_of_family=one.head_of_family)


def test_pds_card_detail_maps_members_entitlements_transactions(tmp_path):
    from nightkeep.mock_pds import conventions as c

    district_dir = _district(tmp_path)
    pds = PdsProvider(district_dir / "data" / "district.db")
    card_no = pds.search()[0].card_no

    detail = pds.card_detail(card_no)

    assert detail is not None
    assert detail.card_no == card_no
    assert detail.members, "the card has members"
    assert detail.head_of_family in {m.name for m in detail.members}
    expected_kg = c.entitlement_kg(detail.scheme, len(detail.members))
    assert {e.commodity.lower(): e.monthly_allotment_kg for e in detail.entitlements} == {
        k: v for k, v in expected_kg.items()
    }
    for tx in detail.transactions:
        assert tx.commodity_summary, "each event summarises its commodities"


def test_pds_card_detail_unknown_card_is_none(tmp_path):
    district_dir = _district(tmp_path)
    pds = PdsProvider(district_dir / "data" / "district.db")

    assert pds.card_detail("no-such-card") is None


# --- habit cards into task rows -------------------------------------------------


def test_habit_tasks_render_learned_jobs(tmp_path):
    habit = _habit(tmp_path)
    _teach(habit)

    tasks = habit_tasks(habit)

    assert len(tasks) == 1
    task = tasks[0]
    assert task.task_name == "Day-end upload"
    assert "02:14" in task.usually
    assert task.status == "Normal"
    assert "quiet learning days" in task.last_night


def test_habit_tasks_carry_the_latest_verdict(tmp_path):
    habit = _habit(tmp_path)
    _teach(habit)
    judge = _judge(tmp_path, habit)
    (tmp_path / TRAPS[0]).write_bytes(b"tampered")
    run = _incident_run()
    verdict = judge.verdict(run)
    assert verdict.level == INCIDENT

    tasks = habit_tasks(habit, (verdict_record_from_live(run, verdict),))

    assert tasks[0].status == "Incident"
    assert "day 8" in tasks[0].last_night


# --- judge verdicts into the incident screens ------------------------------------


def _incident_record(tmp_path):
    habit = _habit(tmp_path)
    _teach(habit)
    judge = _judge(tmp_path, habit)
    (tmp_path / TRAPS[0]).write_bytes(b"tampered")
    run = _incident_run()
    verdict = judge.verdict(run)
    assert verdict.level == INCIDENT
    return verdict_record_from_live(run, verdict)


def test_verdict_record_carries_level_signals_reasons_actions(tmp_path):
    record = _incident_record(tmp_path)

    assert record.level == INCIDENT
    assert "S2" in record.signals
    assert record.reasons, "the verdict wrote its reasons"
    assert record.actions, "the verdict wrote its actions"
    assert record.started_at is not None and record.finished_at is not None


def test_alert_presentation_names_the_real_signals(tmp_path):
    district_dir = _district(tmp_path)
    share = _share_with_backup(district_dir)
    vault = _vault(tmp_path, share)
    vault.pull(taken_at=DAY)
    record = _incident_record(tmp_path)

    alert = alert_presentation(record, vault, PdsProvider(district_dir / "data" / "district.db"))

    assert "stopped" in alert.headline
    assert alert.status_badge == "STATUS: ATTACK STOPPED"
    assert any("S2" in figure.value for figure in alert.figures)
    assert any(event.title == "Attack stopped" for event in alert.timeline)
    assert alert.actions[0].is_highlighted


def test_server_alert_fires_on_a_real_incident(tmp_path):
    record = _incident_record(tmp_path)

    alert = server_alert(record)

    assert alert.title == "Nightkeep Security Alert"
    assert "paused" in alert.headline
    assert "Do not restart the office computer." in alert.actions


def test_calm_alert_when_nothing_happened():
    alert = calm_alert()

    assert alert.status_badge == "STATUS: ALL CLEAR"
    assert first_incident(()) is None


# --- vault snapshots into safety/restore ------------------------------------------


def _timeline(tmp_path):
    """Two clean pulls, an incident, a suspect pull, a clean pull after."""
    district_dir = _district(tmp_path)
    share = _share_with_backup(district_dir)
    vault = _vault(tmp_path, share)
    first = vault.pull(taken_at=DAY)
    second = vault.pull(taken_at=DAY + timedelta(days=1))

    record = _incident_record(tmp_path)
    incident_at = record.finished_at
    assert DAY + timedelta(days=1) < incident_at

    csv_path = share / "exports" / "epos_day_end_20260920.csv"
    csv_path.write_bytes(os.urandom(6000))
    suspect = vault.pull(taken_at=DAY + timedelta(days=9))
    assert suspect.health == "SUSPECT"

    csv_path.write_text(
        "card_no,date,qty_kg\n110300512847,2026-09-20,5.000\n", encoding="utf-8"
    )
    after = vault.pull(taken_at=DAY + timedelta(days=10))
    assert after.health == "CLEAN"
    return district_dir, vault, record, (first, second, suspect, after)


def test_restore_selects_newest_clean_before_the_incident(tmp_path):
    _, vault, record, (first, second, _suspect, after) = _timeline(tmp_path)

    chosen = newest_clean_before(vault, record.finished_at)

    assert chosen is not None
    assert chosen.snapshot_id == second.snapshot_id
    assert chosen.snapshot_id != after.snapshot_id
    assert chosen.snapshot_id != first.snapshot_id


def test_safety_home_reads_real_snapshots_and_cards(tmp_path):
    district_dir, vault, record, _ = _timeline(tmp_path)
    habit = _habit(tmp_path)
    _teach(habit)
    pds = PdsProvider(district_dir / "data" / "district.db")

    safety = safety_home(habit, vault, pds.district_figures(), (record,))

    assert safety.protected_cards_count == "200"
    assert safety.safe_copies_count == "4"
    assert len(safety.tasks) == 1
    assert safety.tasks[0].task_name == "Day-end upload"


def test_restore_wizard_checks_are_pending_before_the_restore(tmp_path):
    district_dir, vault, record, (_, second, _, _) = _timeline(tmp_path)
    pds = PdsProvider(district_dir / "data" / "district.db")

    wizard = restore_wizard(vault, record, pds)

    assert wizard.clean_point == "21 Sep, 02:14"
    assert all(check.status == "Pending" for check in wizard.checks)
    assert len(wizard.checks) == 5
    assert wizard.steps[0].status == "completed"


def test_restore_service_wrong_pin_restores_nothing(tmp_path):
    district_dir, vault, record, (_, second, _, _) = _timeline(tmp_path)
    service = RestoreService(vault, PIN, second.snapshot_id)

    with pytest.raises(PinRejected):
        service.attempt("000000")

    assert not list((tmp_path / "vault").glob("restored*"))


def test_restore_service_correct_pin_restores_once(tmp_path):
    district_dir, vault, record, (_, second, _, _) = _timeline(tmp_path)
    service = RestoreService(vault, PIN, second.snapshot_id)
    calls = []
    real_restore = vault.restore
    vault.restore = lambda snapshot_id: calls.append(snapshot_id) or real_restore(snapshot_id)

    result = service.attempt(PIN)

    assert calls == [second.snapshot_id]
    assert result.ok
    assert result.records_verified == 120
    assert Path(result.restored_to).is_dir()


def test_restore_service_with_no_clean_snapshot_is_unavailable(tmp_path):
    from nightkeep.vault import VaultError

    district_dir = _district(tmp_path)
    share = _share_with_backup(district_dir)
    vault = _vault(tmp_path, share)

    service = RestoreService(vault, PIN, None)

    assert not service.available
    with pytest.raises(PinRejected):
        service.attempt("000000")
    with pytest.raises(VaultError):
        service.attempt(PIN)


def test_verdicts_from_report_survive_a_round_trip(tmp_path):
    record = _incident_record(tmp_path)
    reports = tmp_path / "district" / "reports"
    reports.mkdir(parents=True)
    (reports / "demo_run.json").write_text(
        '{"verdicts": [{"job": "nightly_export", "day": 8, "level": "INCIDENT", '
        '"signals": ["S2"]}], "attack": null}',
        encoding="utf-8",
    )
    import json

    report = json.loads((reports / "demo_run.json").read_text(encoding="utf-8"))

    records = verdicts_from_report(report)

    assert len(records) == 1
    assert first_incident(records).level == INCIDENT
    assert first_incident(records).signals == ("S2",)
    assert verdicts_from_report({}) == ()
    assert verdicts_from_report({"verdicts": "broken"}) == ()


# --- the wired app: routes over the real providers ---------------------------------


def _wired_app(tmp_path, pin=PIN):
    district_dir, vault, record, (_, second, _, _) = _timeline(tmp_path)
    pds = PdsProvider(district_dir / "data" / "district.db")
    service = RestoreService(vault, pin, second.snapshot_id)
    app = create_app(
        district_figures=pds.district_figures(),
        pds=pds,
        restore_wizard_data=restore_wizard(vault, record, pds),
        restore_service=service,
        alert_data=alert_presentation(record, vault, pds),
    )
    return app, vault, second


def test_search_serves_the_real_district(tmp_path):
    app, _, _ = _wired_app(tmp_path)
    client = app.test_client()

    response = client.get("/search")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "200" in html
    assert "All 200 records protected" in html


def test_search_filter_and_card_detail_use_real_rows(tmp_path):
    app, _, _ = _wired_app(tmp_path)
    client = app.test_client()
    district_dir = tmp_path / "district"
    pds = PdsProvider(district_dir / "data" / "district.db")
    one = pds.search()[0]

    filtered = client.get("/search", query_string={"card_no": one.card_no})
    assert filtered.status_code == 200
    assert one.card_no in filtered.get_data(as_text=True)

    detail = client.get(f"/card/{one.card_no}")
    assert detail.status_code == 200
    assert one.head_of_family in detail.get_data(as_text=True)

    missing = client.get("/card/no-such-card")
    assert missing.status_code == 404


def test_restore_get_shows_pending_checks(tmp_path):
    app, _, _ = _wired_app(tmp_path)
    client = app.test_client()

    html = client.get("/restore").get_data(as_text=True)

    assert "Pending" in html
    assert "0 of 5 Verified" in html
    assert 'name="restore_pin"' in html


def test_restore_post_wrong_pin_shows_error_and_restores_nothing(tmp_path):
    app, vault, _ = _wired_app(tmp_path)
    client = app.test_client()

    response = client.post("/restore", data={"restore_pin": "000000"})

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Wrong PIN" in html
    assert not list((tmp_path / "vault").glob("restored*"))


def test_restore_post_correct_pin_restores_and_reports_checks(tmp_path):
    app, vault, _ = _wired_app(tmp_path)
    client = app.test_client()
    calls = []
    real_restore = vault.restore
    vault.restore = lambda snapshot_id: calls.append(snapshot_id) or real_restore(snapshot_id)

    response = client.post("/restore", data={"restore_pin": PIN})

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Restore complete" in html
    assert "5 of 5 Verified" in html
    assert calls and len(calls) == 1


def test_alert_route_renders_the_real_incident(tmp_path):
    app, _, _ = _wired_app(tmp_path)
    client = app.test_client()

    html = client.get("/alert").get_data(as_text=True)

    assert "ATTACK STOPPED" in html
    assert "S2" in html


# --- the entrypoint wiring: create_console_app over a real config ------------------


def _habit_in_district(district_dir: Path) -> Habit:
    return Habit(district_dir / "data" / "habit.db", 3.0, 3, 0.10)


def test_create_console_app_reads_real_runtime_from_disk(tmp_path):
    import json

    from nightkeep.config import load_config
    from nightkeep.console.__main__ import create_console_app

    district_dir = _district(tmp_path)
    share = _share_with_backup(district_dir)
    vault = _vault(tmp_path, share)
    vault.pull(taken_at=DAY)
    _teach(_habit_in_district(district_dir))

    reports = district_dir / "reports"
    (reports / "demo_run.json").write_text(
        json.dumps(
            {
                "verdicts": [
                    {
                        "job": "nightly_export",
                        "day": 8,
                        "level": "INCIDENT",
                        "signals": ["S2"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    config = load_config(Path("nightkeep/config.yaml"))
    assert config.console.supervisor_pin == PIN
    app = create_console_app(
        config, district_dir=district_dir, vault_dir=tmp_path / "vault"
    )
    client = app.test_client()

    search = client.get("/search").get_data(as_text=True)
    assert "All 200 records protected" in search

    safety = client.get("/safety").get_data(as_text=True)
    assert "Day-end upload" in safety

    alert = client.get("/alert").get_data(as_text=True)
    assert "ATTACK STOPPED" in alert

    restore = client.get("/restore").get_data(as_text=True)
    assert "Pending" in restore

    denied = client.post("/restore", data={"restore_pin": "000000"})
    assert "Wrong PIN" in denied.get_data(as_text=True)
    assert not list((tmp_path / "vault").glob("restored*"))

    allowed = client.post("/restore", data={"restore_pin": PIN})
    assert "Restore complete" in allowed.get_data(as_text=True)


def test_create_console_app_without_a_district_keeps_demo_values():
    from nightkeep.console.__main__ import create_console_app

    app = create_console_app()
    client = app.test_client()

    assert client.get("/search").status_code == 200
    assert client.get("/restore").status_code == 200
