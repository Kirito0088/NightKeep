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

DEFAULT_DISTRICT_FIGURES: dict[str, str] = {
    "ration_cards": "5,000",
    "fps_count": "50",
}


def create_app(
    sample_records: tuple[RationCardPresentation, ...] | None = None,
    district_figures: dict[str, str] | None = None,
) -> Flask:
    """Create and configure the Nightkeep console Flask application."""
    app = Flask(__name__)
    records_pool = sample_records if sample_records is not None else DEFAULT_SAMPLE_RECORDS
    figures = district_figures if district_figures is not None else DEFAULT_DISTRICT_FIGURES

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
        )

    return app
