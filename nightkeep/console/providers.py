"""Read-only adapters: backend state into the console's presentation data.

Thin glue between the real modules and the Flask console. Every decision
was already made by habit, judge and vault: a verdict's level, a snapshot's
health, the pinned clean point. This module only reads those outcomes
through the modules' own public APIs and maps them onto the presentation
dataclasses the templates already render.

It never re-judges, re-scores, re-verifies or recomputes a backend
decision. Numbers shown here are read, not derived: a sentence the judge
wrote, a count the database returned, a timestamp a manifest carries.

Two ways to feed it verdicts, because verdicts live in memory while a run
is happening and on disk afterwards:
  - live: verdict_record_from_live(run, verdict) for each Judge.history()
    entry, when the console runs in the same process as the judging;
  - on disk: verdicts_from_report() reads the demo report the orchestrator
    writes to <district>/reports/demo_run.json.
"""

from __future__ import annotations

import hmac
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping

from nightkeep.console.app import (
    RESTORE_CHECK_STATEMENTS,
    AlertActionStepPresentation,
    AlertScreenPresentation,
    CardDetailPresentation,
    EntitlementItemPresentation,
    IncidentFigurePresentation,
    MemberPresentation,
    NightTaskPresentation,
    RationCardPresentation,
    RestoreStepPresentation,
    RestoreWizardPresentation,
    SafetyHomePresentation,
    ServerAlertPresentation,
    TimelineEventPresentation,
    TransactionPresentation,
    VerificationCheckPresentation,
    calm_alert,
)
from nightkeep.habit import Habit, open_habit
from nightkeep.mock_pds import conventions as c
from nightkeep.types import (
    CLEAN,
    INCIDENT,
    NORMAL,
    ODD,
    SUSPICIOUS,
    JobRun,
    RestoreResult,
    Snapshot,
    Verdict,
)
from nightkeep.vault import Vault, VaultError

# The report the demo orchestrator writes when a run finishes. The judge's
# verdict history lives in memory, so this file is the persistent record of
# what was decided: levels, signals, reasons and actions.
DEMO_REPORT_NAME = "demo_run.json"

# The console's own vocabulary for the six jobs. Labels only: which job is
# which comes from habit's cards, never from here.
JOB_LABELS = {
    "nightly_export": "Day-end upload",
    "allocation_gen": "Allotment file creation",
    "db_backup": "Safe copy of the database",
    "archive_old": "Old file clean-up",
    "fix_dat": "Data format maintenance",
    "operator_activity": "Counter clerk entries",
}


# --- verdict records -------------------------------------------------------


@dataclass(frozen=True)
class VerdictRecord:
    """One judged run, as the console needs it: the level, why, what was done.

    `started_at`/`finished_at` are the run's own clocks when known. Records
    read from the on-disk report have no run clocks, only the verdict.
    """

    job: str
    day_no: int | None
    level: str
    signals: tuple[str, ...] = ()
    signal_titles: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    actions: tuple[str, ...] = ()
    started_at: datetime | None = None
    finished_at: datetime | None = None


def verdict_record_from_live(run: JobRun, verdict: Verdict) -> VerdictRecord:
    """One Judge.history() entry, mapped without re-deriving anything."""
    return VerdictRecord(
        job=run.job,
        day_no=run.day_no,
        level=verdict.level,
        signals=tuple(signal.code for signal in verdict.signals),
        signal_titles=tuple(signal.title for signal in verdict.signals),
        reasons=tuple(verdict.reasons),
        actions=tuple(verdict.actions),
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


def verdicts_from_report(report: Mapping) -> tuple[VerdictRecord, ...]:
    """Verdicts from the orchestrator's on-disk report. Never raises.

    The report is written by another process; anything missing or misshapen
    yields fewer records, never an exception. The console degrades to the
    calm screens rather than failing to start.
    """
    records: list[VerdictRecord] = []
    if not isinstance(report, Mapping):
        return ()

    verdicts = report.get("verdicts")
    if isinstance(verdicts, list):
        for entry in verdicts:
            if not isinstance(entry, Mapping):
                continue
            level = entry.get("level")
            if not isinstance(level, str):
                continue
            signals = entry.get("signals")
            records.append(
                VerdictRecord(
                    job=str(entry.get("job", "?")),
                    day_no=entry.get("day")
                    if isinstance(entry.get("day"), int)
                    else None,
                    level=level,
                    signals=tuple(signals)
                    if isinstance(signals, list)
                    else (),
                )
            )

    attack = report.get("attack")
    if isinstance(attack, Mapping) and isinstance(attack.get("level"), str):
        signals = attack.get("signals")
        reasons = attack.get("reasons")
        actions = attack.get("actions")
        records.append(
            VerdictRecord(
                job="simulator",
                day_no=None,
                level=attack["level"],
                signals=tuple(signals) if isinstance(signals, list) else (),
                reasons=tuple(reasons) if isinstance(reasons, list) else (),
                actions=tuple(actions) if isinstance(actions, list) else (),
            )
        )
    return tuple(records)


def first_incident(
    records: tuple[VerdictRecord, ...],
) -> VerdictRecord | None:
    """The first INCIDENT, if any. The alert and restore screens hang off it."""
    for record in records:
        if record.level == INCIDENT:
            return record
    return None


def first_attention(
    records: tuple[VerdictRecord, ...],
) -> VerdictRecord | None:
    """The first record that deserves an alert screen: INCIDENT or SUSPICIOUS.

    The restore path still hangs off first_incident(): only a real
    INCIDENT picks the restore target. The alert and server-alert screens
    use this, so a SUSPICIOUS verdict is not silently shown as all-clear.
    """
    for record in records:
        if record.level in (INCIDENT, SUSPICIOUS):
            return record
    return None


def load_report(district_dir: Path) -> Mapping:
    """The orchestrator's report, or {} when there is none or it is broken."""
    path = Path(district_dir) / "reports" / DEMO_REPORT_NAME
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


# --- the PDS database -------------------------------------------------------


class PdsProvider:
    """Read-only ration-card search and detail over the district database.

    Opens the SQLite file read-only on every call and closes it again: the
    console never holds a write handle to the district's live data.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)
        if not self._db_path.is_file():
            raise VaultError(f"no district database at {self._db_path}")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            f"file:{self._db_path}?mode=ro", uri=True
        )
        conn.row_factory = sqlite3.Row
        return conn

    def district_figures(self) -> dict[str, str]:
        with self._connect() as conn:
            cards = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
            shops = conn.execute("SELECT COUNT(*) FROM shops").fetchone()[0]
        return {
            "ration_cards": f"{cards:,}",
            "fps_count": f"{shops:,}",
        }

    def search(
        self,
        *,
        card_no: str = "",
        head_of_family: str = "",
        taluka: str = "",
        fps: str = "",
        scheme: str = "",
        status: str = "",
    ) -> list[RationCardPresentation]:
        """Cards matching the filters, in card-number order.

        `head_of_family` matches the member recorded as "Self", which is
        how the generator marks the head of the household.
        """
        clauses = ["m.relation_to_head = 'Self'"]
        params: list[str] = []
        if card_no:
            clauses.append("c.card_no LIKE '%' || ? || '%'")
            params.append(card_no)
        if head_of_family:
            clauses.append("m.name LIKE '%' || ? || '%'")
            params.append(head_of_family)
        if taluka and taluka != "All":
            clauses.append("c.taluka = ?")
            params.append(taluka)
        if fps:
            clauses.append("(c.fps_id LIKE '%' || ? || '%' OR s.name LIKE '%' || ? || '%')")
            params.extend([fps, fps])
        if scheme and scheme != "All":
            clauses.append("c.scheme = ?")
            params.append(scheme)
        if status and status != "All":
            clauses.append("c.status = ?")
            params.append(status)

        query = (
            "SELECT c.card_no, c.scheme, c.card_type, c.status, c.taluka, "
            "c.village, c.fps_id, s.name AS fps_name, m.name AS head_of_family "
            "FROM cards c "
            "JOIN shops s ON s.fps_id = c.fps_id "
            "JOIN members m ON m.card_no = c.card_no "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY c.card_no"
        )
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            RationCardPresentation(
                card_no=row["card_no"],
                head_of_family=row["head_of_family"],
                taluka=row["taluka"],
                village=row["village"],
                fps_id=row["fps_id"],
                fps_name=row["fps_name"],
                scheme=row["scheme"],
                card_type=row["card_type"],
                status=row["status"],
            )
            for row in rows
        ]

    def card_detail(self, card_no: str) -> CardDetailPresentation | None:
        with self._connect() as conn:
            card = conn.execute(
                "SELECT c.*, s.name AS fps_name FROM cards c "
                "JOIN shops s ON s.fps_id = c.fps_id "
                "WHERE c.card_no = ?",
                (card_no,),
            ).fetchone()
            if card is None:
                return None
            member_rows = conn.execute(
                "SELECT name, sex, age, relation_to_head, ekyc_status, "
                "aadhaar_seeded FROM members WHERE card_no = ? "
                "ORDER BY member_id",
                (card_no,),
            ).fetchall()
            tx_rows = conn.execute(
                "SELECT occurred_at, allotment_month, commodity, quantity_kg, "
                "auth_mode, status, fps_id FROM transactions "
                "WHERE card_no = ? ORDER BY occurred_at DESC",
                (card_no,),
            ).fetchall()

        members = tuple(
            MemberPresentation(
                sr_no=index,
                name=row["name"],
                relation_to_head=row["relation_to_head"],
                sex=row["sex"],
                age=row["age"],
                aadhaar_seeded=bool(row["aadhaar_seeded"]),
                ekyc_status=row["ekyc_status"],
            )
            for index, row in enumerate(member_rows, start=1)
        )
        head = next(
            (m for m in members if m.relation_to_head == "Self"),
            members[0] if members else None,
        )
        entitlements = tuple(
            EntitlementItemPresentation(
                commodity=commodity.title(),
                monthly_allotment_kg=kg,
                rate_per_kg=c.ISSUE_PRICE_TEXT,
                allotment_basis=_allotment_basis(card["scheme"], commodity),
            )
            for commodity, kg in c.entitlement_kg(
                card["scheme"], len(members)
            ).items()
        )
        transactions = _group_transactions(tx_rows)
        return CardDetailPresentation(
            card_no=card["card_no"],
            head_of_family=head.name if head else "Not recorded",
            scheme=card["scheme"],
            card_type=card["card_type"],
            status=card["status"],
            address=card["address"],
            taluka=card["taluka"],
            village=card["village"],
            issue_date=_pretty_date(card["issue_date"]),
            fps_id=card["fps_id"],
            fps_name=card["fps_name"],
            # The mock district records no phone numbers or LPG data.
            mobile_masked="Not recorded",
            gas_connection="Not recorded",
            members=members,
            entitlements=entitlements,
            transactions=transactions,
        )

    def counter_entries_between(
        self, start: datetime, end: datetime
    ) -> int:
        """Counter-clerk transactions recorded in the loss window.

        The office re-checks these after a restore: they landed after the
        last clean copy and may not be in it.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM transactions "
                "WHERE occurred_at >= ? AND occurred_at <= ?",
                (start.isoformat(), end.isoformat()),
            ).fetchone()
        return int(row[0])


def _allotment_basis(scheme: str, commodity: str) -> str:
    if scheme == "AAY":
        if commodity == "sugar":
            return "1.000 kg per card"
        return "AAY household fixed allocation"
    per_member = {"rice": "3.000 kg per member", "wheat": "2.000 kg per member"}
    return per_member.get(commodity, "per member")


def _group_transactions(
    rows: list[sqlite3.Row],
) -> tuple[TransactionPresentation, ...]:
    """One presentation row per collection event, commodities summarised."""
    grouped: dict[tuple[str, str], list[sqlite3.Row]] = {}
    for row in rows:
        key = (row["occurred_at"], row["allotment_month"])
        grouped.setdefault(key, []).append(row)
    presentations = []
    for (occurred_at, month), items in sorted(
        grouped.items(), key=lambda kv: kv[0][0], reverse=True
    )[:10]:
        summary = ", ".join(
            f"{item['commodity'].title()} ({item['quantity_kg']:.3f} kg)"
            for item in items
        )
        presentations.append(
            TransactionPresentation(
                occurred_at=_pretty_datetime(occurred_at),
                allotment_month=month,
                commodity_summary=summary,
                quantity_kg=round(sum(i["quantity_kg"] for i in items), 3),
                auth_mode=items[0]["auth_mode"],
                status=items[0]["status"],
                fps_id=items[0]["fps_id"],
            )
        )
    return tuple(presentations)


def _pretty_date(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%d %b %Y")
    except ValueError:
        return iso


def _pretty_datetime(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return iso


# --- habit cards -------------------------------------------------------------


def habit_tasks(
    habit: Habit,
    verdicts: tuple[VerdictRecord, ...] = (),
) -> tuple[NightTaskPresentation, ...]:
    """One row per learned job: what it usually does, and its latest state.

    The "usually" ranges are the habit card's own medians and spreads,
    phrased plainly. The latest state is the job's most recent verdict, or
    "Normal" when the job has only ever been seen on quiet learning days.
    """
    cards = habit.cards()
    latest: dict[str, VerdictRecord] = {}
    for record in verdicts:
        latest[record.job] = record
    tasks = []
    for job in sorted(cards, key=lambda j: JOB_LABELS.get(j, j)):
        card = cards[job]
        record = latest.get(job)
        tasks.append(
            NightTaskPresentation(
                task_name=JOB_LABELS.get(job, job),
                usually=_usually(card),
                last_night=_last_night(record),
                status=_task_status(record),
            )
        )
    return tuple(tasks)


def _usually(card: dict[str, tuple[float, float]]) -> str:
    """The card's medians as one plain sentence."""
    parts = []
    start = card.get("start_minute")
    if start:
        median, spread = start
        parts.append(
            f"around {_hhmm(median)} (give or take {spread:.0f} min)"
        )
    files = sum(
        card.get(feature, (0.0, 0.0))[0]
        for feature in ("files_created", "files_modified")
    )
    if files:
        parts.append(f"touches about {files:,.0f} files")
    return ", ".join(parts) if parts else "no usual pattern recorded yet"


def _last_night(record: VerdictRecord | None) -> str:
    if record is None:
        return "only seen on quiet learning days"
    day = f"day {record.day_no}" if record.day_no is not None else "recently"
    return f"{day}: {record.level.title()}"


def _task_status(record: VerdictRecord | None) -> str:
    if record is None:
        return "Normal"
    return {
        NORMAL: "Normal",
        ODD: "Odd, not blocked",
        SUSPICIOUS: "Under review",
        INCIDENT: "Incident",
    }.get(record.level, record.level.title())


def _hhmm(minutes: float) -> str:
    total = int(minutes) % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


# --- the vault -----------------------------------------------------------------


def newest_clean_before(
    vault: Vault, before: datetime | None
) -> Snapshot | None:
    """The newest CLEAN snapshot strictly before `before`.

    `before` is the first incident's time; with no incident it is the newest
    CLEAN snapshot outright. The restore target, per the MVP: the last point
    verified clean before anything went wrong.

    Note this filters on the snapshot's own health, not on the vault's
    current pin: a later clean pull moves the pin forward, but the restore
    must still go back to before the incident.
    """
    candidates = [
        snap
        for snap in vault.snapshots()
        if snap.health == CLEAN and (before is None or snap.taken_at < before)
    ]
    return candidates[-1] if candidates else None


def first_suspect_after(
    vault: Vault, after: datetime | None
) -> Snapshot | None:
    """The first SUSPECT snapshot at or after `after`, if one exists."""
    for snap in vault.snapshots():
        if snap.health == "SUSPECT" and (
            after is None or snap.taken_at >= after
        ):
            return snap
    return None


def safety_home(
    habit: Habit,
    vault: Vault,
    district_figures: dict[str, str],
    verdicts: tuple[VerdictRecord, ...] = (),
) -> SafetyHomePresentation:
    """The Data Safety screen from the real habit cards and vault state.

    Read-only: `vault.protect_mode` is the Vault's own verdict state, and
    Snapshot.health is left untouched -- a SUSPICIOUS Vault verdict says
    nothing about the data, only about the protection posture.
    """
    snapshots = vault.snapshots()
    clean = [s for s in snapshots if s.is_clean_point]
    suspect = [s for s in snapshots if s.health == "SUSPECT"]
    latest_clean = clean[-1] if clean else None

    protect_mode = bool(getattr(vault, "protect_mode", False))
    has_suspicious = any(record.level == SUSPICIOUS for record in verdicts)

    if protect_mode:
        status_badge = "STATUS: PROTECTING"
        protection_status = (
            "Attention needed: Nightkeep is protecting your records"
        )
        protection_detail = (
            "The Vault is holding the last clean recovery point while the "
            "unusual activity is checked. Restore remains available from "
            "the clean copy."
        )
    elif suspect and (
        not latest_clean or suspect[-1].taken_at > latest_clean.taken_at
    ):
        status_badge = "STATUS: ATTENTION"
        protection_status = (
            "Attention needed: the latest safe copy looks suspicious"
        )
        protection_detail = (
            "The newest backup failed the Vault's health check. The last "
            "clean copy is still preserved and ready."
        )
    elif has_suspicious:
        status_badge = "STATUS: UNDER REVIEW"
        protection_status = (
            "Attention needed: unusual activity is under review"
        )
        protection_detail = (
            "Nightkeep flagged unusual activity for review. Nothing is "
            "blocked; the Incident Alert screen shows what was flagged."
        )
    elif latest_clean:
        status_badge = "STATUS: NORMAL"
        protection_status = "Your records are safe"
        protection_detail = (
            "All 5,000 ration cards are protected and continuous monitoring "
            "is active. Safe copies are preserved on the isolated Vault."
        )
    else:
        status_badge = "STATUS: NORMAL"
        protection_status = "No safe copies yet"
        protection_detail = "The Vault has not taken a clean backup yet."

    clean_point = (
        _snapshot_label(latest_clean) if latest_clean else "No clean copy yet"
    )
    return SafetyHomePresentation(
        status_badge=status_badge,
        protection_status=protection_status,
        protection_detail=protection_detail,
        protected_cards_count=district_figures.get("ration_cards", "?"),
        fps_count=district_figures.get("fps_count", "?"),
        safe_copies_count=str(len(snapshots)),
        clean_point=clean_point,
        tasks=habit_tasks(habit, verdicts),
    )


def restore_wizard(
    vault: Vault,
    incident: VerdictRecord | None,
    pds: PdsProvider | None,
) -> RestoreWizardPresentation:
    """The restore screen before a restore runs.

    Selects the newest CLEAN snapshot before the first incident, exactly the
    MVP's restore rule. The five checks are named but Pending: nothing has
    been verified yet. After the restore runs, restore_result_wizard()
    replaces them with the checks that actually ran.
    """
    incident_at = _incident_time(vault, incident)
    target = newest_clean_before(vault, incident_at)
    clean_point = _snapshot_label(target) if target else "No clean copy yet"
    records = pds.district_figures()["ration_cards"] if pds else "?"
    loss_entries, loss_detail = _loss_window(vault, incident, pds, target)

    steps = (
        RestoreStepPresentation(
            step_number=1,
            title="Select clean copy",
            description=(
                f"Clean backup {target.snapshot_id} on the Vault selected."
                if target
                else "No clean backup is available to select."
            ),
            status="completed" if target else "active",
        ),
        RestoreStepPresentation(
            step_number=2,
            title="Verify records",
            description=(
                "The five automated integrity and safety checks run "
                "with the restore."
                if target
                else "Waiting for a clean backup."
            ),
            status="active",
        ),
        RestoreStepPresentation(
            step_number=3,
            title="Confirm and restore",
            description="Enter supervisor PIN to restore records to the office computer.",
            status="active",
        ),
    )
    checks = tuple(
        VerificationCheckPresentation(
            check_number=index,
            statement=statement,
            status="Pending",
        )
        for index, statement in enumerate(RESTORE_CHECK_STATEMENTS, start=1)
    )
    return RestoreWizardPresentation(
        headline="Get my records back",
        clean_point=clean_point,
        records_count=records,
        loss_window_entries=loss_entries,
        loss_window_detail=loss_detail,
        steps=steps,
        checks=checks,
    )


def restore_result_wizard(
    result, pds: PdsProvider | None
) -> RestoreWizardPresentation:
    """The restore screen after Vault.restore() ran: the checks that ran."""
    records = pds.district_figures()["ration_cards"] if pds else "?"
    steps = (
        RestoreStepPresentation(
            step_number=1,
            title="Select clean copy",
            description=f"Clean backup {result.snapshot_id} on the Vault selected.",
            status="completed",
        ),
        RestoreStepPresentation(
            step_number=2,
            title="Verify records",
            description=(
                "All five automated integrity and safety checks passed."
                if result.ok
                else "Some checks failed; the damaged data was left untouched."
            ),
            status="completed",
        ),
        RestoreStepPresentation(
            step_number=3,
            title="Confirm and restore",
            description=(
                f"Records restored to {result.restored_to}."
                if result.ok
                else "Restore did not complete."
            ),
            status="completed",
        ),
    )
    checks = tuple(
        VerificationCheckPresentation(
            check_number=index,
            statement=check.statement,
            status="Passed" if check.passed else "Failed",
        )
        for index, check in enumerate(result.checks, start=1)
    )
    return RestoreWizardPresentation(
        headline="Get my records back",
        clean_point=result.snapshot_id,
        records_count=records,
        loss_window_entries="0",
        loss_window_detail=(
            f"{result.records_verified:,} of {result.records_expected:,} "
            "ration cards verified after the restore."
        ),
        steps=steps,
        checks=checks,
    )


def _loss_window(
    vault: Vault,
    incident: VerdictRecord | None,
    pds: PdsProvider | None,
    target,
) -> tuple[str, str]:
    """Counter entries between the clean copy and the incident, from the DB."""
    if target is None or pds is None:
        return "?", "The loss window cannot be measured without a clean copy."
    end = _incident_time(vault, incident) or datetime.now(target.taken_at.tzinfo)
    count = pds.counter_entries_between(target.taken_at, end)
    detail = (
        f"{count} counter entries recorded between the clean backup "
        f"({_snapshot_label(target)}) and the incident must be re-checked "
        "after restoration."
    )
    return str(count), detail


def _incident_time(
    vault: Vault, incident: VerdictRecord | None
) -> datetime | None:
    """When the trouble started, from the verdict or the first SUSPECT pull."""
    if incident is not None and incident.finished_at is not None:
        return incident.finished_at
    suspect = first_suspect_after(vault, None)
    return suspect.taken_at if suspect else None


def _snapshot_label(snapshot) -> str:
    return snapshot.taken_at.strftime("%d %b, %H:%M")


# --- the incident screens -------------------------------------------------------


def alert_presentation(
    incident: VerdictRecord,
    vault: Vault,
    pds: PdsProvider | None,
) -> AlertScreenPresentation:
    """The incident alert from the real verdict, snapshots and loss window."""
    clean = newest_clean_before(vault, _incident_time(vault, incident))
    suspect = first_suspect_after(
        vault, clean.taken_at if clean else None
    )
    clean_label = _snapshot_label(clean) if clean else "no clean copy"
    target = clean

    if incident.level == INCIDENT:
        headline = "Someone tried to lock your files. It was stopped."
        status_badge = "STATUS: ATTACK STOPPED"
    else:
        headline = "Something unusual is happening to your files."
        status_badge = "STATUS: UNDER REVIEW"

    signals = " + ".join(incident.signals) if incident.signals else "none"
    figures = [
        IncidentFigurePresentation(
            value=signals, label="tripwire signals fired"
        ),
        IncidentFigurePresentation(
            value=clean_label, label="clean copy ready"
        ),
    ]
    loss_entries = "?"
    if pds is not None and target is not None:
        end = _incident_time(vault, incident) or datetime.now(
            target.taken_at.tzinfo
        )
        loss_entries = str(pds.counter_entries_between(target.taken_at, end))
    figures.append(
        IncidentFigurePresentation(
            value=loss_entries, label="counter entries to re-check"
        )
    )
    if incident.reasons:
        figures.append(
            IncidentFigurePresentation(
                value=str(len(incident.reasons)),
                label="reasons recorded",
            )
        )

    timeline: list[TimelineEventPresentation] = []
    if incident.started_at is not None:
        timeline.append(
            TimelineEventPresentation(
                time=incident.started_at.strftime("%H:%M:%S"),
                title="Suspicious activity began",
                detail=incident.reasons[0]
                if incident.reasons
                else "An abnormal program began modifying office files.",
            )
        )
    if incident.finished_at is not None:
        # INCIDENT means the attack was stopped; SUSPICIOUS only means it
        # was flagged, so the timeline must not claim a stop happened.
        decision_title = (
            "Attack stopped"
            if incident.level == INCIDENT
            else "Flagged for review"
        )
        decision_detail = (
            "; ".join(incident.actions)
            if incident.actions
            else (
                "Nightkeep stopped the program."
                if incident.level == INCIDENT
                else "Nightkeep flagged this activity for review."
            )
        )
        timeline.append(
            TimelineEventPresentation(
                time=incident.finished_at.strftime("%H:%M:%S"),
                title=decision_title,
                detail=decision_detail,
            )
        )
    if suspect is not None:
        timeline.append(
            TimelineEventPresentation(
                time=suspect.taken_at.strftime("%H:%M:%S"),
                title="Latest safe copy flagged",
                detail=suspect.reasons[0]
                if suspect.reasons
                else "The Vault's health check marked this pull SUSPECT.",
            )
        )
    if clean is not None:
        timeline.append(
            TimelineEventPresentation(
                time=clean.taken_at.strftime("%H:%M:%S"),
                title=f"Clean copy from {clean_label} ready",
                detail="Safe backup preserved on the Vault remains uncorrupted "
                "and ready.",
            )
        )
    timeline.append(
        TimelineEventPresentation(
            time="--:--:--",
            title="Office follow-up required",
            detail=f"{loss_entries} counter entries recorded after the clean "
            "copy need to be re-checked.",
        )
    )

    actions = (
        AlertActionStepPresentation(
            number=1,
            title="Do not restart the office computer.",
            detail="Restarting can wipe the evidence and can let the locking "
            "program start again.",
            is_highlighted=True,
        ),
        AlertActionStepPresentation(
            number=2,
            title="Disconnect the network cable.",
            detail="Keep this computer separated until the district "
            "technician arrives.",
            is_highlighted=False,
        ),
        AlertActionStepPresentation(
            number=3,
            title="Restore records using the clean copy.",
            detail="Safe copies are preserved on the Vault. Use the clean "
            f"copy from {clean_label} to restore records.",
            is_highlighted=False,
        ),
    )
    return AlertScreenPresentation(
        headline=headline,
        status_badge=status_badge,
        figures=tuple(figures),
        timeline=tuple(timeline),
        actions=actions,
    )


def server_alert(incident: VerdictRecord | None) -> ServerAlertPresentation:
    """The office computer's pop-up.

    Says "paused" only when a real INCIDENT verdict is behind it -- the
    same honesty rule as the demo orchestrator's alert_for(): no incident
    state, no pause claim.
    """
    return ServerAlertPresentation(
        title="Nightkeep Security Alert",
        headline=(
            "A program tried to lock your files. It was paused."
            if incident is not None and incident.level == INCIDENT
            else "Unusual activity was detected on the office computer."
        ),
        actions=(
            "Do not restart the office computer.",
            "Disconnect the network cable.",
            "Go to the Data Safety console on the Vault machine.",
        ),
    )


# --- PIN-gated restore ------------------------------------------------------------


class PinRejected(Exception):
    """The supervisor PIN did not match. Nothing was restored."""


class RestoreService:
    """The restore the PIN unlocks: one snapshot, chosen before any incident.

    The snapshot was selected by newest_clean_before(); attempt() only
    checks the PIN and then calls Vault.restore(), which does its own
    verification and lands the data in a new folder.
    """

    def __init__(
        self, vault: Vault, expected_pin: str, snapshot_id: str | None
    ) -> None:
        self._vault = vault
        self._expected_pin = expected_pin
        self._snapshot_id = snapshot_id

    @property
    def snapshot_id(self) -> str | None:
        return self._snapshot_id

    @property
    def available(self) -> bool:
        return self._snapshot_id is not None

    def attempt(self, pin: str) -> RestoreResult:
        """Check the PIN, then restore. Raises PinRejected or VaultError."""
        if not hmac.compare_digest(pin or "", self._expected_pin):
            raise PinRejected("Wrong PIN. Nothing was restored.")
        if self._snapshot_id is None:
            raise VaultError("no clean snapshot is available to restore")
        return self._vault.restore(self._snapshot_id)


# --- putting it together ----------------------------------------------------------


@dataclass
class ConsoleRuntime:
    """Everything the console needs, read from real on-disk state."""

    district_dir: Path
    pds: PdsProvider
    habit: Habit | None
    vault: Vault | None
    verdicts: tuple[VerdictRecord, ...]
    supervisor_pin: str

    @property
    def incident(self) -> VerdictRecord | None:
        return first_incident(self.verdicts)

    @property
    def alert_record(self) -> VerdictRecord | None:
        """The first INCIDENT or SUSPICIOUS record, for the alert screens."""
        return first_attention(self.verdicts)


def build_runtime(
    district_dir: Path,
    vault_dir: Path | None,
    config,
) -> ConsoleRuntime | None:
    """Read the real runtime state, or None when it is not there.

    None means the console keeps its hardcoded demo values: the district
    has not been built yet, or this machine has never seen a run.
    """
    district_dir = Path(district_dir)
    db_path = district_dir / "data" / "district.db"
    if not db_path.is_file():
        return None

    pds = PdsProvider(db_path)

    habit_db = district_dir / "data" / "habit.db"
    habit = (
        open_habit(
            district_dir,
            config.habit.mad_multiplier,
            config.habit.min_runs_before_scoring,
            config.habit.minimum_spread_fraction,
        )
        if habit_db.is_file()
        else None
    )

    vault = None
    if vault_dir is not None and Path(vault_dir).is_dir():
        vault = Vault(
            root=Path(vault_dir),
            share=district_dir / "share",
            suspect_entropy=config.vault.suspect_entropy,
            suspect_changed_fraction=config.vault.suspect_changed_fraction,
            suspect_record_drop_fraction=(
                config.vault.suspect_record_drop_fraction
            ),
            restore_folder_name=config.vault.restore_folder_name,
        )

    verdicts = verdicts_from_report(load_report(district_dir))

    return ConsoleRuntime(
        district_dir=district_dir,
        pds=pds,
        habit=habit,
        vault=vault,
        verdicts=verdicts,
        supervisor_pin=config.console.supervisor_pin,
    )


def restore_service_for(
    runtime: ConsoleRuntime,
) -> RestoreService | None:
    """The PIN-gated restore for this runtime, if the vault is present."""
    if runtime.vault is None:
        return None
    incident_at = _incident_time(runtime.vault, runtime.incident)
    target = newest_clean_before(runtime.vault, incident_at)
    return RestoreService(
        vault=runtime.vault,
        expected_pin=runtime.supervisor_pin,
        snapshot_id=target.snapshot_id if target else None,
    )
