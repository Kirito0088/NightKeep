"""The Flask console on the Vault's own screen. Routes only.

Shallow presentation layer. Bound to 127.0.0.1, never the LAN.
Renders the plain-language reasons carried by HabitScore, Verdict and
RestoreResult. It never re-derives them.
"""

from dataclasses import dataclass
from flask import Flask, render_template, request

from nightkeep.mock_pds import conventions as c


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
    protection_status: str
    protected_cards_count: str
    fps_count: str
    safe_copies_count: str
    clean_point: str
    tasks: tuple[NightTaskPresentation, ...]


DEFAULT_SAFETY_HOME_DATA: SafetyHomePresentation = SafetyHomePresentation(
    protection_status="Your records are safe",
    protected_cards_count="5,000",
    fps_count="50",
    safe_copies_count="24",
    clean_point="Day 9, 01:20",
    tasks=(
        NightTaskPresentation(
            task_name="Day-end upload",
            usually="01:00 to 02:30, writes ~240 rows",
            last_night="01:14 (248 rows)",
            status="Normal",
        ),
        NightTaskPresentation(
            task_name="Allotment file creation",
            usually="23:15 to 00:45, writes 50 files",
            last_night="23:30 (50 files)",
            status="Normal",
        ),
        NightTaskPresentation(
            task_name="Safe copy of the database",
            usually="10 to 45 min after upload",
            last_night="01:45 (clean database backup)",
            status="Normal",
        ),
        NightTaskPresentation(
            task_name="Old file clean-up",
            usually="03:00 to 04:30 when folder > 40 MB",
            last_night="Did not run (folder under limit)",
            status="Normal",
        ),
        NightTaskPresentation(
            task_name="Data format maintenance",
            usually="02:00 to 05:00, occasional nights",
            last_night="03:40 (6 files modified)",
            status="Later than usual",
        ),
        NightTaskPresentation(
            task_name="Counter clerk entries",
            usually="10:00 to 17:00, Mon to Sat",
            last_night="10:15 to 16:50 (24 entries)",
            status="Normal",
        ),
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
) -> Flask:
    """Create and configure the Nightkeep console Flask application."""
    app = Flask(__name__)
    records_pool = sample_records if sample_records is not None else DEFAULT_SAMPLE_RECORDS
    figures = district_figures if district_figures is not None else DEFAULT_DISTRICT_FIGURES
    card_details_pool = card_details if card_details is not None else DEFAULT_CARD_DETAILS
    safety_pool = safety_home_data if safety_home_data is not None else DEFAULT_SAFETY_HOME_DATA

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

        return render_template(
            "search.html",
            records=filtered,
            query=query,
            district_figures=figures,
            talukas=c.TALUKAS,
            schemes=c.SCHEMES,
            statuses=c.CARD_STATUSES,
            active_page="search",
        )

    @app.route("/card/<card_no>", methods=["GET"])
    def card_detail(card_no: str) -> tuple[str, int] | str:
        detail = card_details_pool.get(card_no)
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
            safety=safety_pool,
            active_page="safety",
        )

    return app
