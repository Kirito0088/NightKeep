"""The Flask console on the Vault's own screen. Routes only.

Shallow presentation layer. Bound to 127.0.0.1, never the LAN.
Renders the plain-language reasons carried by HabitScore, Verdict and
RestoreResult. It never re-derives them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from flask import Flask, redirect, render_template, request, url_for

from nightkeep.mock_pds import conventions as c

from nightkeep.console.showcase import ShowcaseController

if TYPE_CHECKING:
    # Imported for annotations only: providers.py imports this module's
    # presentation dataclasses, so a runtime import here would be circular.
    from nightkeep.console.providers import PdsProvider, RestoreService


@dataclass(frozen=True)
class RationCardPresentation:
    card_no: str
    head_of_family: str
    taluka: str
    village: str
    fps_id: str
    fps_name: str
    scheme: str
    card_type: str
    status: str


@dataclass(frozen=True)
class MemberPresentation:
    sr_no: int
    name: str
    relation_to_head: str
    sex: str
    age: int
    aadhaar_seeded: bool
    ekyc_status: str  # "Done" | "Pending"


@dataclass(frozen=True)
class EntitlementItemPresentation:
    commodity: str  # "Rice", "Wheat", "Sugar"
    monthly_allotment_kg: float
    rate_per_kg: str  # "Free under PMGKAY"
    allotment_basis: str  # "3.000 kg per member"


@dataclass(frozen=True)
class TransactionPresentation:
    occurred_at: str  # "2026-09-08 11:24"
    allotment_month: str  # "2026-09"
    commodity_summary: str  # "Rice (12.000 kg), Wheat (8.000 kg)"
    quantity_kg: float
    auth_mode: str  # "Biometric" | "Iris" | "OTP" | "Nominee"
    status: str  # "Collected" | "Part collected"
    fps_id: str


@dataclass(frozen=True)
class CardDetailPresentation:
    card_no: str
    head_of_family: str
    scheme: str
    card_type: str
    status: str
    address: str
    taluka: str
    village: str
    issue_date: str
    fps_id: str
    fps_name: str
    mobile_masked: str
    gas_connection: str
    members: tuple[MemberPresentation, ...]
    entitlements: tuple[EntitlementItemPresentation, ...]
    transactions: tuple[TransactionPresentation, ...]

    @property
    def member_count(self) -> int:
        return len(self.members)

    @property
    def seeded_member_count(self) -> int:
        return sum(1 for m in self.members if m.aadhaar_seeded)

    @property
    def aadhaar_summary(self) -> str:
        return f"{self.seeded_member_count} of {self.member_count} members seeded"


@dataclass(frozen=True)
class NightTaskPresentation:
    task_name: str
    usually: str
    last_night: str
    status: str


@dataclass(frozen=True)
class SafetyHomePresentation:
    status_badge: str  # "STATUS: NORMAL" | "STATUS: UNDER REVIEW" | "STATUS: PROTECTING" | ...
    protection_status: str
    protection_detail: str
    protected_cards_count: str
    fps_count: str
    safe_copies_count: str
    clean_point: str
    tasks: tuple[NightTaskPresentation, ...]


@dataclass(frozen=True)
class IncidentFigurePresentation:
    value: str
    label: str


@dataclass(frozen=True)
class TimelineEventPresentation:
    time: str
    title: str
    detail: str


@dataclass(frozen=True)
class AlertActionStepPresentation:
    number: int
    title: str
    detail: str
    is_highlighted: bool = False


@dataclass(frozen=True)
class AlertScreenPresentation:
    headline: str
    status_badge: str
    figures: tuple[IncidentFigurePresentation, ...]
    timeline: tuple[TimelineEventPresentation, ...]
    actions: tuple[AlertActionStepPresentation, ...]


@dataclass(frozen=True)
class RestoreStepPresentation:
    step_number: int
    title: str
    description: str
    status: str  # "completed" | "active"


@dataclass(frozen=True)
class VerificationCheckPresentation:
    check_number: int
    statement: str
    status: str  # "Passed"


@dataclass(frozen=True)
class RestoreWizardPresentation:
    headline: str
    clean_point: str
    records_count: str
    loss_window_entries: str
    loss_window_detail: str
    steps: tuple[RestoreStepPresentation, ...]
    checks: tuple[VerificationCheckPresentation, ...]


@dataclass(frozen=True)
class ServerAlertPresentation:
    title: str
    headline: str
    actions: tuple[str, ...]


@dataclass(frozen=True)
class LockedScreenPresentation:
    """The lock screen banner: live incident wording or drill framing.

    The route renders the same illustration either way; only the banner
    tells the truth about whether a real incident locked the records.
    """

    badge: str
    headline: str
    description: str


def calm_alert() -> AlertScreenPresentation:
    """The alert screen with no incident: nothing to show, honestly.

    This is also the fallback the unwired console uses, so an accidental
    launch without backend state can never present a fabricated attack.
    """
    return AlertScreenPresentation(
        headline="No incidents. Nightkeep is watching.",
        status_badge="STATUS: ALL CLEAR",
        figures=(),
        timeline=(),
        actions=(
            AlertActionStepPresentation(
                number=1,
                title="Nothing to do.",
                detail="No tripwire has fired. The Data Safety screen shows "
                "what the night tasks did.",
                is_highlighted=False,
            ),
        ),
    )


# The five checks Vault.restore() runs, in its own order. Stated here once
# so the wizard can name them before the restore runs; after it runs, the
# real Check objects from the RestoreResult take over.
RESTORE_CHECK_STATEMENTS = (
    "Every restored file's hash matches the safe copy from the Vault.",
    "Every restored file still opens as its own type.",
    "Every restored export parses as a CSV.",
    "The database backup passes its integrity check.",
    "All ration cards are present and readable.",
)


DEFAULT_SERVER_ALERT_DATA: ServerAlertPresentation = ServerAlertPresentation(
    title="Nightkeep Security Alert",
    # Honest fallback: no backend state here, so no claim that a program
    # was paused. Matches the no-incident branch of server_alert().
    headline="Unusual activity was detected on the office computer.",
    actions=(
        "Do not restart the office computer.",
        "Disconnect the network cable.",
        "Go to the Data Safety console on the Vault machine.",
    ),
)


DEFAULT_SAFETY_HOME_DATA: SafetyHomePresentation = SafetyHomePresentation(
    # Honest fallback: with no backend state there are no safe copies, no
    # clean point, and no night-task history to report. Same shape as the
    # no-clean-copy branch of providers.safety_home().
    status_badge="STATUS: NORMAL",
    protection_status="No safe copies yet",
    protection_detail=(
        "The Vault has not taken a clean backup yet. Run the full demo "
        "to see live protection data."
    ),
    protected_cards_count="?",
    fps_count="?",
    safe_copies_count="0",
    clean_point="No clean copy yet",
    tasks=(),
)


DEFAULT_ALERT_DATA: AlertScreenPresentation = calm_alert()


DEFAULT_RESTORE_DATA: RestoreWizardPresentation = RestoreWizardPresentation(
    # Honest fallback: with no backend state there is no clean copy, no
    # loss window and no incident to restore from. Same shape as the
    # no-target branch of providers.restore_wizard().
    headline="Get my records back",
    clean_point="No clean copy yet",
    records_count="?",
    loss_window_entries="?",
    loss_window_detail="The loss window cannot be measured without a clean copy.",
    steps=(
        RestoreStepPresentation(
            step_number=1,
            title="Select clean copy",
            description="No clean backup is available to select.",
            status="active",
        ),
        RestoreStepPresentation(
            step_number=2,
            title="Verify records",
            description="Waiting for a clean backup.",
            status="active",
        ),
        RestoreStepPresentation(
            step_number=3,
            title="Confirm and restore",
            description="Enter supervisor PIN to restore records to the office computer.",
            status="active",
        ),
    ),
    checks=tuple(
        VerificationCheckPresentation(
            check_number=index,
            statement=statement,
            status="Pending",
        )
        for index, statement in enumerate(RESTORE_CHECK_STATEMENTS, start=1)
    ),
)


DRILL_LOCKED_DATA: LockedScreenPresentation = LockedScreenPresentation(
    # The drill illustration: /locked with no real incident behind it.
    badge="DEMONSTRATION DRILL",
    headline="How the lock screen looks during an attack (drill)",
    description=(
        "No real incident is active. This screen illustrates what the "
        "office sees when Nightkeep locks the records after stopping an "
        "attack."
    ),
)


REAL_LOCKED_DATA: LockedScreenPresentation = LockedScreenPresentation(
    # A real INCIDENT locked the records: the previous static copy, now
    # gated on backend state instead of asserted unconditionally.
    badge="SYSTEM NOTICE",
    headline="Ration card records cannot be opened",
    description=(
        "The system detected an abnormal program attempting to modify "
        "database files. Records have been locked in place to protect "
        "beneficiary data."
    ),
)


# Five realistic initial presentation records modeled strictly after
# Thane district conventions (ADR-0003, ADR-0005, ADR-0006).
# Kept isolated as route presentation defaults so mock_pds data can
# seamlessly plug in later without modifying template contracts.
DEFAULT_SAMPLE_RECORDS: tuple[RationCardPresentation, ...] = (
    RationCardPresentation(
        card_no="110300512847",
        head_of_family="Sunita Ramesh Kadam",
        taluka="Thane",
        village="Navghar",
        fps_id="27030300145",
        fps_name="Jai Bhavani Swasta Dhanya Dukan",
        scheme="NFSA-PHH",
        card_type="Priority Household",
        status="Active",
    ),
    RationCardPresentation(
        card_no="110482910384",
        head_of_family="Rajesh Vithal Shinde",
        taluka="Thane",
        village="Majiwada",
        fps_id="27030300145",
        fps_name="Jai Bhavani Swasta Dhanya Dukan",
        scheme="AAY",
        card_type="Antyodaya",
        status="Active",
    ),
    RationCardPresentation(
        card_no="110829104928",
        head_of_family="Pooja Santosh Jadhav",
        taluka="Kalyan",
        village="Titwala",
        fps_id="27030300218",
        fps_name="Shree Ganesh Wajibi Bhav Dukan",
        scheme="NFSA-PHH",
        card_type="Priority Household",
        status="Active",
    ),
    RationCardPresentation(
        card_no="110294819203",
        head_of_family="Anil Eknath More",
        taluka="Kalyan",
        village="Dombivli Rural",
        fps_id="27030300218",
        fps_name="Shree Ganesh Wajibi Bhav Dukan",
        scheme="Kesari (APL)",
        card_type="Kesari",
        status="Suspended",
    ),
    RationCardPresentation(
        card_no="110938201948",
        head_of_family="Kavita Suresh Patil",
        taluka="Thane",
        village="Bhayandar Pada",
        fps_id="27030300145",
        fps_name="Jai Bhavani Swasta Dhanya Dukan",
        scheme="NFSA-PHH",
        card_type="Priority Household",
        status="Active",
    ),
)

DEFAULT_CARD_DETAILS: dict[str, CardDetailPresentation] = {
    "110300512847": CardDetailPresentation(
        card_no="110300512847",
        head_of_family="Sunita Ramesh Kadam",
        scheme="NFSA-PHH",
        card_type="Priority Household",
        status="Active",
        address="Plot 14, Ghodbunder Road, Navghar, Thane",
        taluka="Thane",
        village="Navghar",
        issue_date="14 Mar 2021",
        fps_id="27030300145",
        fps_name="Jai Bhavani Swasta Dhanya Dukan",
        mobile_masked="98XXXXXX41",
        gas_connection="1 Cylinder (HP Gas)",
        members=(
            MemberPresentation(1, "Sunita Ramesh Kadam", "Self", "Female", 42, True, "Done"),
            MemberPresentation(2, "Ramesh Ananda Kadam", "Spouse", "Male", 46, True, "Done"),
            MemberPresentation(3, "Amit Ramesh Kadam", "Son", "Male", 19, True, "Done"),
            MemberPresentation(4, "Priya Ramesh Kadam", "Daughter", "Female", 16, False, "Pending"),
        ),
        entitlements=(
            EntitlementItemPresentation("Rice", 12.000, "Free under PMGKAY", "3.000 kg per member"),
            EntitlementItemPresentation("Wheat", 8.000, "Free under PMGKAY", "2.000 kg per member"),
        ),
        transactions=(
            TransactionPresentation("2026-09-08 11:24", "2026-09", "Rice (12.000 kg), Wheat (8.000 kg)", 20.000, "Biometric", "Collected", "27030300145"),
            TransactionPresentation("2026-08-06 16:40", "2026-08", "Rice (12.000 kg), Wheat (8.000 kg)", 20.000, "Biometric", "Collected", "27030300145"),
            TransactionPresentation("2026-07-10 10:15", "2026-07", "Rice (12.000 kg), Wheat (8.000 kg)", 20.000, "OTP", "Collected", "27030300145"),
        ),
    ),
    "110482910384": CardDetailPresentation(
        card_no="110482910384",
        head_of_family="Rajesh Vithal Shinde",
        scheme="AAY",
        card_type="Antyodaya",
        status="Active",
        address="House 42, Majiwada Village Road, Thane",
        taluka="Thane",
        village="Majiwada",
        issue_date="05 Nov 2019",
        fps_id="27030300145",
        fps_name="Jai Bhavani Swasta Dhanya Dukan",
        mobile_masked="97XXXXXX23",
        gas_connection="None (PM Ujjwala eligible)",
        members=(
            MemberPresentation(1, "Rajesh Vithal Shinde", "Self", "Male", 54, True, "Done"),
            MemberPresentation(2, "Lata Rajesh Shinde", "Spouse", "Female", 49, True, "Done"),
            MemberPresentation(3, "Sachin Rajesh Shinde", "Son", "Male", 22, True, "Done"),
        ),
        entitlements=(
            EntitlementItemPresentation("Rice", 21.000, "Free under PMGKAY", "AAY household fixed allocation"),
            EntitlementItemPresentation("Wheat", 14.000, "Free under PMGKAY", "AAY household fixed allocation"),
            EntitlementItemPresentation("Sugar", 1.000, "Free under PMGKAY", "1.000 kg per card"),
        ),
        transactions=(
            TransactionPresentation("2026-09-04 09:30", "2026-09", "Rice (21.000 kg), Wheat (14.000 kg), Sugar (1.000 kg)", 36.000, "Biometric", "Collected", "27030300145"),
            TransactionPresentation("2026-08-03 14:12", "2026-08", "Rice (21.000 kg), Wheat (14.000 kg), Sugar (1.000 kg)", 36.000, "Biometric", "Collected", "27030300145"),
        ),
    ),
    "110829104928": CardDetailPresentation(
        card_no="110829104928",
        head_of_family="Pooja Santosh Jadhav",
        scheme="NFSA-PHH",
        card_type="Priority Household",
        status="Active",
        address="Room 8, Mandir Ali, Titwala, Kalyan",
        taluka="Kalyan",
        village="Titwala",
        issue_date="22 Jan 2022",
        fps_id="27030300218",
        fps_name="Shree Ganesh Wajibi Bhav Dukan",
        mobile_masked="98XXXXXX88",
        gas_connection="1 Cylinder (Bharat Gas)",
        members=(
            MemberPresentation(1, "Pooja Santosh Jadhav", "Self", "Female", 38, True, "Done"),
            MemberPresentation(2, "Santosh Tukaram Jadhav", "Spouse", "Male", 41, True, "Done"),
            MemberPresentation(3, "Rahul Santosh Jadhav", "Son", "Male", 17, True, "Done"),
            MemberPresentation(4, "Sneha Santosh Jadhav", "Daughter", "Female", 14, True, "Done"),
            MemberPresentation(5, "Parvati Tukaram Jadhav", "Mother", "Female", 68, False, "Pending"),
        ),
        entitlements=(
            EntitlementItemPresentation("Rice", 15.000, "Free under PMGKAY", "3.000 kg per member"),
            EntitlementItemPresentation("Wheat", 10.000, "Free under PMGKAY", "2.000 kg per member"),
        ),
        transactions=(
            TransactionPresentation("2026-09-09 17:05", "2026-09", "Rice (15.000 kg), Wheat (10.000 kg)", 25.000, "Biometric", "Collected", "27030300218"),
            TransactionPresentation("2026-08-07 11:30", "2026-08", "Rice (15.000 kg), Wheat (10.000 kg)", 25.000, "Biometric", "Collected", "27030300218"),
        ),
    ),
    "110294819203": CardDetailPresentation(
        card_no="110294819203",
        head_of_family="Anil Eknath More",
        scheme="Kesari (APL)",
        card_type="Kesari",
        status="Suspended",
        address="Bungalow 3, Deslepada, Dombivli Rural, Kalyan",
        taluka="Kalyan",
        village="Dombivli Rural",
        issue_date="18 Aug 2018",
        fps_id="27030300218",
        fps_name="Shree Ganesh Wajibi Bhav Dukan",
        mobile_masked="99XXXXXX55",
        gas_connection="2 Cylinders (Indane)",
        members=(
            MemberPresentation(1, "Anil Eknath More", "Self", "Male", 51, True, "Done"),
            MemberPresentation(2, "Sunanda Anil More", "Spouse", "Female", 47, True, "Done"),
        ),
        entitlements=(
            EntitlementItemPresentation("Rice", 6.000, "Free under PMGKAY", "3.000 kg per member"),
            EntitlementItemPresentation("Wheat", 4.000, "Free under PMGKAY", "2.000 kg per member"),
        ),
        transactions=(
            TransactionPresentation("2026-07-12 15:20", "2026-07", "Rice (6.000 kg), Wheat (4.000 kg)", 10.000, "Biometric", "Collected", "27030300218"),
        ),
    ),
    "110938201948": CardDetailPresentation(
        card_no="110938201948",
        head_of_family="Kavita Suresh Patil",
        scheme="NFSA-PHH",
        card_type="Priority Household",
        status="Active",
        address="Flat 102, Gokul Dham, Bhayandar Pada, Thane",
        taluka="Thane",
        village="Bhayandar Pada",
        issue_date="29 Sep 2020",
        fps_id="27030300145",
        fps_name="Jai Bhavani Swasta Dhanya Dukan",
        mobile_masked="96XXXXXX74",
        gas_connection="1 Cylinder (HP Gas)",
        members=(
            MemberPresentation(1, "Kavita Suresh Patil", "Self", "Female", 35, True, "Done"),
            MemberPresentation(2, "Suresh Dattatray Patil", "Spouse", "Male", 39, True, "Done"),
            MemberPresentation(3, "Nikhil Suresh Patil", "Son", "Male", 12, True, "Done"),
        ),
        entitlements=(
            EntitlementItemPresentation("Rice", 9.000, "Free under PMGKAY", "3.000 kg per member"),
            EntitlementItemPresentation("Wheat", 6.000, "Free under PMGKAY", "2.000 kg per member"),
        ),
        transactions=(
            TransactionPresentation("2026-09-05 10:45", "2026-09", "Rice (9.000 kg), Wheat (6.000 kg)", 15.000, "Biometric", "Collected", "27030300145"),
        ),
    ),
}

DEFAULT_DISTRICT_FIGURES: dict[str, str] = {
    "ration_cards": "5,000",
    "fps_count": "50",
}


def create_app(
    sample_records: tuple[RationCardPresentation, ...] | None = None,
    district_figures: dict[str, str] | None = None,
    card_details: dict[str, CardDetailPresentation] | None = None,
    safety_home_data: SafetyHomePresentation | None = None,
    alert_data: AlertScreenPresentation | None = None,
    restore_data: RestoreWizardPresentation | None = None,
    server_alert_data: ServerAlertPresentation | None = None,
    pds: PdsProvider | None = None,
    restore_wizard_data: RestoreWizardPresentation | None = None,
    restore_service: RestoreService | None = None,
    locked_data: LockedScreenPresentation | None = None,
    runtime_factory=None,
    showcase_controller: ShowcaseController | None = None,
) -> Flask:
    """Create and configure the Nightkeep console Flask application.

    The presentation pools keep their defaults: hardcoded demo values when
    no real backend state is wired in. `pds` answers search/detail from the
    real district database; `restore_wizard_data` is the pre-restore wizard
    built from the real vault state; `restore_service` unlocks the POST
    /restore route behind the supervisor PIN; `locked_data` decides whether
    /locked shows a live lock or a drill illustration. All are read-only
    from the routes' point of view: they call the provider, they never
    decide.

    `runtime_factory` is a no-argument callable returning a fresh
    ConsoleRuntime (or None). When present, the safety/alert/restore/
    locked/server-alert routes rebuild their presentation pools per
    request, so a demo launched from the showcase after the console
    started is visible on those screens. Without it every route behaves
    exactly as before. `showcase_controller` owns the one-click demo;
    a default one is created when none is given.
    """
    app = Flask(__name__)
    records_pool = sample_records if sample_records is not None else DEFAULT_SAMPLE_RECORDS
    figures = district_figures if district_figures is not None else DEFAULT_DISTRICT_FIGURES
    card_details_pool = card_details if card_details is not None else DEFAULT_CARD_DETAILS
    safety_pool = safety_home_data if safety_home_data is not None else DEFAULT_SAFETY_HOME_DATA
    alert_pool = alert_data if alert_data is not None else DEFAULT_ALERT_DATA
    restore_pool = restore_data if restore_data is not None else DEFAULT_RESTORE_DATA
    server_alert_pool = (
        server_alert_data if server_alert_data is not None else DEFAULT_SERVER_ALERT_DATA
    )
    locked_pool = locked_data if locked_data is not None else DRILL_LOCKED_DATA

    controller = (
        showcase_controller
        if showcase_controller is not None
        else ShowcaseController()
    )

    def refreshed_pool(name: str, default):
        """Rebuild one presentation pool from a fresh runtime, when wired.

        Without a runtime factory this returns the bound pool, exactly as
        before: unwired consoles and every existing test see no change.
        A factory that raises or returns None degrades to the bound pool
        rather than failing the page.
        """
        if runtime_factory is None:
            return default
        try:
            runtime = runtime_factory()
        except Exception:
            return default
        if runtime is None:
            return default
        from nightkeep.console.providers import presentation_for

        return presentation_for(runtime).get(name, default)

    @app.route("/", methods=["GET"])
    @app.route("/search", methods=["GET"])
    def search_cards() -> str:
        card_no = request.args.get("card_no", "").strip()
        head_of_family = request.args.get("head_of_family", "").strip()
        taluka = request.args.get("taluka", "").strip()
        fps = request.args.get("fps", "").strip()
        scheme = request.args.get("scheme", "").strip()
        status = request.args.get("status", "").strip()

        filtered = list(records_pool)

        if card_no:
            filtered = [r for r in filtered if card_no in r.card_no]
        if head_of_family:
            filtered = [
                r for r in filtered if head_of_family.lower() in r.head_of_family.lower()
            ]
        if taluka and taluka != "All":
            filtered = [r for r in filtered if r.taluka.lower() == taluka.lower()]
        if fps:
            filtered = [
                r for r in filtered
                if fps.lower() in r.fps_id.lower() or fps.lower() in r.fps_name.lower()
            ]
        if scheme and scheme != "All":
            filtered = [r for r in filtered if r.scheme.lower() == scheme.lower()]
        if status and status != "All":
            filtered = [r for r in filtered if r.status.lower() == status.lower()]

        query: dict[str, str] = {
            "card_no": card_no,
            "head_of_family": head_of_family,
            "taluka": taluka,
            "fps": fps,
            "scheme": scheme,
            "status": status,
        }

        if pds is not None:
            records = pds.search(
                card_no=card_no,
                head_of_family=head_of_family,
                taluka=taluka,
                fps=fps,
                scheme=scheme,
                status=status,
            )
            page_figures = pds.district_figures()
        else:
            records = filtered
            page_figures = figures

        return render_template(
            "search.html",
            records=records,
            query=query,
            district_figures=page_figures,
            talukas=c.TALUKAS,
            schemes=c.SCHEMES,
            statuses=c.CARD_STATUSES,
            active_page="search",
        )

    @app.route("/card/<card_no>", methods=["GET"])
    def card_detail(card_no: str) -> tuple[str, int] | str:
        detail = card_details_pool.get(card_no)
        if detail is None and pds is not None:
            detail = pds.card_detail(card_no)
        if detail is None:
            return render_template("card_not_found.html", card_no=card_no), 404
        total_entitlement_kg = round(
            sum(e.monthly_allotment_kg for e in detail.entitlements), 3
        )
        return render_template(
            "card_detail.html",
            card=detail,
            total_entitlement_kg=total_entitlement_kg,
            active_page="search",
        )

    @app.route("/locked", methods=["GET"])
    def pds_locked() -> str:
        return render_template(
            "locked.html",
            locked=refreshed_pool("locked_data", locked_pool),
            district_figures=figures,
            talukas=c.TALUKAS,
            schemes=c.SCHEMES,
            statuses=c.CARD_STATUSES,
            active_page="search",
        )

    @app.route("/safety", methods=["GET"])
    def nightkeep_home() -> str:
        return render_template(
            "safety.html",
            safety=refreshed_pool("safety_home_data", safety_pool),
            active_page="safety",
        )

    @app.route("/alert", methods=["GET"])
    def nightkeep_alert() -> str:
        return render_template(
            "alert.html",
            alert=refreshed_pool("alert_data", alert_pool),
            active_page="safety",
        )

    @app.route("/restore", methods=["GET", "POST"])
    def restore_wizard() -> str:
        """The restore wizard. GET shows it; POST needs the supervisor PIN.

        The route only reads the PIN and hands it to the injected restore
        service. The service checks the PIN and, only then, calls
        Vault.restore(). A wrong PIN means nothing is touched.
        """
        wizard = refreshed_pool(
            "restore_wizard_data",
            restore_wizard_data if restore_wizard_data is not None else restore_pool,
        )
        service = refreshed_pool("restore_service", restore_service)

        if request.method == "GET":
            return render_template(
                "restore.html",
                restore=wizard,
                active_page="safety",
            )

        from nightkeep.console.providers import (
            PinRejected,
            restore_result_wizard,
        )
        from nightkeep.vault import VaultError

        pin = request.form.get("restore_pin", "")
        if service is None or not service.available:
            return render_template(
                "restore.html",
                restore=wizard,
                restore_error=(
                    "Restore is not available right now: there is no clean "
                    "backup to restore from."
                ),
                active_page="safety",
            )
        try:
            result = service.attempt(pin)
        except PinRejected as exc:
            return render_template(
                "restore.html",
                restore=wizard,
                restore_error=str(exc),
                active_page="safety",
            )
        except VaultError as exc:
            return render_template(
                "restore.html",
                restore=wizard,
                restore_error=f"The restore could not finish: {exc}",
                active_page="safety",
            )
        return render_template(
            "restore.html",
            restore=restore_result_wizard(result, pds),
            restore_success=True,
            active_page="safety",
        )

    @app.route("/server-alert", methods=["GET"])
    def server_alert() -> str:
        return render_template(
            "server_alert.html",
            alert=refreshed_pool("server_alert_data", server_alert_pool),
        )

    @app.route("/showcase", methods=["GET"])
    def showcase_page() -> str:
        """The one-click demo showcase: launch the real demo, watch it live.

        The page never fabricates: the phase comes from the demo's own
        log markers, the figures from the run's own report, and the log
        tail is the demo's own output, unedited.
        """
        status = controller.read_status()
        state = status.get("state", "ready")
        # Terminal states override the log-derived phase: a failed or
        # completed run must show its outcome, not the last phase marker.
        if state in ("failed", "complete"):
            phase = state
        else:
            phase = controller.phase()
        title, description = controller.phase_copy(phase)

        order = list(controller.steps())
        if phase == "complete":
            progress = "complete"
        elif phase == "failed":
            progress = controller.progress_phase()
        else:
            progress = phase
        progress_idx = order.index(progress) if progress in order else -1
        steps = [
            {
                "key": key,
                "title": controller.phase_copy(key)[0],
                "done": order.index(key) < progress_idx
                or (phase == "complete"),
            }
            for key in order
        ]

        figures = controller.report_figures() if state == "complete" else {}

        return render_template(
            "showcase.html",
            state=state,
            phase=phase,
            phase_title=title,
            phase_description=description,
            steps=steps,
            can_start=state != "running",
            figures=figures,
            log_tail=controller.log_tail(),
            refresh=state == "running",
            active_page="showcase",
        )

    @app.route("/showcase/start", methods=["POST"])
    def showcase_start():
        """Start the demo unless one is already running, then show it."""
        controller.start()
        return redirect(url_for("showcase_page"))

    @app.route("/it-view", methods=["GET"])
    def it_view() -> str:
        """The read-only IT view: real diagnostics, or an honest empty state."""
        runtime = None
        if runtime_factory is not None:
            try:
                runtime = runtime_factory()
            except Exception:
                runtime = None
        from nightkeep.console.providers import it_diagnostics

        return render_template(
            "it_view.html",
            it=it_diagnostics(runtime),
            active_page="safety",
        )

    return app
