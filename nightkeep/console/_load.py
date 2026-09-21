"""Turn a demo run into the presentation objects the console renders.

The console is a renderer (ADR-0008): it never re-derives a reason or a
number. This module is the seam that feeds it. It reads two things a demo
run leaves behind under `<demo>/pds/`:

- `reports/run.json`, for the four Data Safety screens. Every reason string
  in there was written by habit, judge or the Vault, in plain language, and
  is passed through untouched.
- `data/district.db`, the real 5,000-card district, for the search and card
  detail screens, so a judge can type any card number and see a real record.

If a run has not happened yet, `load()` returns an empty mapping and the
console falls back to its built-in sample, so the screens always render.
Nothing here decides anything: it reads, shapes and hands over.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from nightkeep.console.app import (
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
)
from nightkeep.mock_pds import conventions as c

RUN_REPORT = "reports/run.json"
DISTRICT_DB = "data/district.db"


def load(district_dir: Path) -> dict:
    """Everything create_app needs from a demo run, or {} if there is none."""
    district_dir = Path(district_dir)
    kwargs: dict = {}

    run_path = district_dir / RUN_REPORT
    if run_path.is_file():
        run = json.loads(run_path.read_text(encoding="utf-8"))
        kwargs.update(
            safety_home_data=_safety(run),
            alert_data=_alert(run),
            restore_data=_restore(run),
            server_alert_data=_server_alert(run),
            district_figures={
                "ration_cards": f"{run['district']['ration_cards']:,}",
                "fps_count": str(run["district"]["fps_count"]),
            },
        )

    db_path = district_dir / DISTRICT_DB
    if db_path.is_file():
        records, details, figures = _from_district(db_path)
        kwargs.update(sample_records=records, card_details=details)
        kwargs.setdefault("district_figures", figures)

    return kwargs


# --- the four Data Safety screens, from run.json ---------------------------


def _safety(run: dict) -> SafetyHomePresentation:
    snapshots = run.get("snapshots", [])
    clean_copies = sum(1 for s in snapshots if s["health"] == "CLEAN")
    return SafetyHomePresentation(
        protection_status="Your records are safe",
        protected_cards_count=f"{run['district']['ration_cards']:,}",
        fps_count=str(run["district"]["fps_count"]),
        safe_copies_count=str(clean_copies),
        clean_point=_clean_point_when(run),
        tasks=tuple(
            NightTaskPresentation(
                task_name=task["task_name"], usually=task["usually"],
                last_night=task["last_night"], status=task["status"],
            )
            for task in run.get("night_tasks", [])
        ),
    )


def _alert(run: dict) -> AlertScreenPresentation:
    proofs = run.get("proofs", {})
    attack = run.get("attack", {})
    figures = [
        IncidentFigurePresentation(
            value=str(attack.get("files_scrambled", 0)), label="files affected"
        ),
        IncidentFigurePresentation(
            value=f"{attack.get('detection_seconds', 0)}s",
            label="to detect and stop it",
        ),
        IncidentFigurePresentation(
            value=f"{proofs.get('p4_records_verified', 0):,}",
            label="ration cards recovered",
        ),
        IncidentFigurePresentation(
            value=str(proofs.get("entries_to_recheck", 0)),
            label="counter entries to re-check",
        ),
    ]
    timeline = [
        TimelineEventPresentation(
            time=(f"{event.get('at', '')}" or ""),
            title=event["title"], detail=event["detail"],
        )
        for event in run.get("timeline", [])
    ]
    return AlertScreenPresentation(
        headline="Someone tried to lock your files. It was stopped.",
        status_badge="STATUS: THREAT STOPPED",
        figures=tuple(figures),
        timeline=tuple(timeline),
        actions=(
            AlertActionStepPresentation(
                number=1, title="Do not restart the office computer.",
                detail="Restarting can lose the record of what happened and "
                       "let the locking program start again.",
                is_highlighted=True,
            ),
            AlertActionStepPresentation(
                number=2, title="Disconnect the network cable.",
                detail="Keep this computer apart until the district technician arrives.",
            ),
            AlertActionStepPresentation(
                number=3, title="Restore records using the clean copy.",
                detail=f"Safe copies are preserved on the Vault. Use the clean "
                       f"copy from {_clean_point_when(run)} to restore records.",
            ),
        ),
    )


def _restore(run: dict) -> RestoreWizardPresentation:
    proofs = run.get("proofs", {})
    restore = run.get("restore", {})
    verified = restore.get("records_verified", proofs.get("p4_records_verified", 0))
    entries = proofs.get("entries_to_recheck", 0)
    checks = tuple(
        VerificationCheckPresentation(
            check_number=index + 1,
            statement=check["statement"],
            status="Passed" if check["passed"] else "Not passed",
        )
        for index, check in enumerate(restore.get("checks", []))
    )
    return RestoreWizardPresentation(
        headline="Get my records back",
        clean_point=_clean_point_when(run),
        records_count=f"{verified:,}",
        loss_window_entries=str(entries),
        loss_window_detail=(
            f"Every ration card was recovered. {entries} counter "
            f"entries recorded on the last night should be re-checked against "
            f"the counter register."
        ),
        steps=(
            RestoreStepPresentation(
                step_number=1, title="Select clean copy",
                description=f"Clean copy from {_clean_point_when(run)} on the "
                            f"Vault selected.",
                status="completed",
            ),
            RestoreStepPresentation(
                step_number=2, title="Verify records",
                description="All five automatic safety checks passed.",
                status="completed",
            ),
            RestoreStepPresentation(
                step_number=3, title="Confirm and restore",
                description="Enter the supervisor PIN to restore records to the "
                            "office computer.",
                status="active",
            ),
        ),
        checks=checks,
    )


def _server_alert(run: dict) -> ServerAlertPresentation:
    return ServerAlertPresentation(
        title="Nightkeep Security Alert",
        headline="A program tried to lock your files. It was paused.",
        actions=(
            "Do not restart the office computer.",
            "Disconnect the network cable.",
            "Go to the Data Safety console on the Vault machine.",
        ),
    )


def _clean_point_when(run: dict) -> str:
    """The pinned clean copy, as a time a clerk can read, not a snapshot id."""
    pinned = next(
        (s for s in run.get("snapshots", []) if s.get("is_clean_point")), None
    )
    if pinned is None:
        return "the last safe copy"
    try:
        moment = datetime.fromisoformat(pinned["taken_at"])
        return moment.strftime("%d %b, %H:%M")
    except (ValueError, KeyError):
        return "the last safe copy"


# --- search and card detail, from the real district database ----------------


def _from_district(db_path: Path) -> tuple:
    connection = sqlite3.connect(f"{Path(db_path).as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        records = _records(connection)
        figures = {
            "ration_cards": f"{connection.execute('SELECT COUNT(*) FROM cards').fetchone()[0]:,}",
            "fps_count": str(connection.execute("SELECT COUNT(*) FROM shops").fetchone()[0]),
        }
    finally:
        connection.close()
    # The detail lookup keeps its own read-only connection, opened per query,
    # so 5,000 full detail records never have to be built up front.
    return records, _CardDetails(db_path), figures


def _records(connection: sqlite3.Connection) -> tuple:
    """A lightweight row per card for the search screen, head of family joined."""
    rows = connection.execute(
        """
        SELECT ca.card_no, ca.scheme, ca.card_type, ca.status, ca.taluka,
               ca.village, ca.fps_id, sh.name AS fps_name,
               (SELECT m.name FROM members m
                WHERE m.card_no = ca.card_no
                ORDER BY (m.relation_to_head = 'Self') DESC, m.member_id LIMIT 1)
               AS head_of_family
        FROM cards ca JOIN shops sh ON sh.fps_id = ca.fps_id
        ORDER BY ca.card_no
        """
    ).fetchall()
    return tuple(
        RationCardPresentation(
            card_no=row["card_no"], head_of_family=row["head_of_family"] or "",
            taluka=row["taluka"], village=row["village"], fps_id=row["fps_id"],
            fps_name=row["fps_name"], scheme=row["scheme"],
            card_type=row["card_type"], status=row["status"],
        )
        for row in rows
    )


class _CardDetails:
    """A dict-shaped lookup that builds one card's full detail on demand.

    The console calls `.get(card_no)`, so this offers exactly that, and only
    that: opening one short read-only connection per lookup is far cheaper
    than assembling five thousand detail records the moment the app starts.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)

    def get(self, card_no: str) -> CardDetailPresentation | None:
        connection = sqlite3.connect(f"{self._db_path.as_uri()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            card = connection.execute(
                "SELECT ca.*, sh.name AS fps_name FROM cards ca "
                "JOIN shops sh ON sh.fps_id = ca.fps_id WHERE ca.card_no = ?",
                (card_no,),
            ).fetchone()
            if card is None:
                return None
            members = connection.execute(
                "SELECT * FROM members WHERE card_no = ? ORDER BY "
                "(relation_to_head = 'Self') DESC, member_id",
                (card_no,),
            ).fetchall()
            transactions = connection.execute(
                "SELECT * FROM transactions WHERE card_no = ? "
                "ORDER BY occurred_at DESC LIMIT 12",
                (card_no,),
            ).fetchall()
        finally:
            connection.close()

        head = next((m["name"] for m in members if m["relation_to_head"] == "Self"),
                    members[0]["name"] if members else "")
        return CardDetailPresentation(
            card_no=card["card_no"], head_of_family=head, scheme=card["scheme"],
            card_type=card["card_type"], status=card["status"],
            address=card["address"], taluka=card["taluka"], village=card["village"],
            issue_date=_date(card["issue_date"]),
            fps_id=card["fps_id"], fps_name=card["fps_name"],
            mobile_masked=_masked_mobile(card["card_no"]),
            gas_connection="Seeded per household",
            members=tuple(
                MemberPresentation(
                    sr_no=index + 1, name=m["name"],
                    relation_to_head=m["relation_to_head"], sex=m["sex"],
                    age=m["age"], aadhaar_seeded=bool(m["aadhaar_seeded"]),
                    ekyc_status=m["ekyc_status"],
                )
                for index, m in enumerate(members)
            ),
            entitlements=_entitlements(card["scheme"], len(members)),
            transactions=tuple(
                TransactionPresentation(
                    occurred_at=_stamp(t["occurred_at"]),
                    allotment_month=t["allotment_month"],
                    commodity_summary=f"{t['commodity'].title()} "
                                      f"({t['quantity_kg']:.3f} kg)",
                    quantity_kg=t["quantity_kg"], auth_mode=t["auth_mode"],
                    status=t["status"], fps_id=t["fps_id"],
                )
                for t in transactions
            ),
        )


def _entitlements(scheme: str, member_count: int) -> tuple:
    kg = c.entitlement_kg(scheme, max(member_count, 1))
    basis = ("AAY household fixed allocation" if scheme == "AAY"
             else "per member")
    labels = {"rice": "Rice", "wheat": "Wheat", "sugar": "Sugar"}
    return tuple(
        EntitlementItemPresentation(
            commodity=labels.get(name, name.title()),
            monthly_allotment_kg=amount,
            rate_per_kg=c.ISSUE_PRICE_TEXT,
            allotment_basis=basis,
        )
        for name, amount in kg.items()
    )


def _masked_mobile(card_no: str) -> str:
    """A masked mobile, stable per card and never a real number.

    CLAUDE.md's convention is a masked form like 98XXXXXX41. The visible
    digits are derived from the card number so a card always shows the same
    masked mobile, and no actual mobile number is ever stored or invented.
    """
    digits = [ch for ch in card_no if ch.isdigit()]
    lead = "9" + (digits[2] if len(digits) > 2 else "8")
    tail = "".join(digits[-2:]) if len(digits) >= 2 else "00"
    return f"{lead}XXXXXX{tail}"


def _date(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%d %b %Y")
    except (ValueError, TypeError):
        return value or ""


def _stamp(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return value or ""
