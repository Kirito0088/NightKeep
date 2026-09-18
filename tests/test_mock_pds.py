"""build_district(seed, district, out_dir): the Thane district PDS server.

Covers ticket #2's acceptance criteria: the database and folder layout,
row counts, reproducibility from a seed, and the data conventions (schemes,
entitlements, transaction shape) sourced into mock_pds/conventions.py.
"""

import sqlite3

from nightkeep.config import District, Span
from nightkeep.mock_pds import build_district
from nightkeep.mock_pds import conventions as c

DISTRICT = District(
    ration_cards=200,
    fps_count=10,
    members_per_card=Span(low=1, high=5),
    transactions_per_card_per_month=Span(low=0, high=2),
)


def _dump(conn: sqlite3.Connection, table: str, order_by: str) -> list[tuple]:
    return conn.execute(f"SELECT * FROM {table} ORDER BY {order_by}").fetchall()


def _build(tmp_path, name, seed=20260922, district=DISTRICT):
    out_dir = build_district(seed, district, tmp_path / name)
    conn = sqlite3.connect(out_dir / "data" / "district.db")
    return out_dir, conn


def test_creates_the_database_and_the_district_folders(tmp_path):
    out_dir, conn = _build(tmp_path, "run")
    conn.close()

    assert (out_dir / "data" / "district.db").is_file()
    for folder in ("data", "reports", "archive", "logs"):
        assert (out_dir / folder).is_dir(), folder
    # ADR-0007: the one folder shared read-only with the Vault.
    for folder in ("exports", "allocations", "backups"):
        assert (out_dir / "share" / folder).is_dir(), folder


def test_the_live_database_is_never_inside_the_share(tmp_path):
    # ADR-0007 and MVP F7: the Vault never copies the live database.
    out_dir, conn = _build(tmp_path, "run")
    conn.close()

    assert list((out_dir / "share").rglob("*.db")) == []


def test_row_counts_match_the_configured_district_size(tmp_path):
    _, conn = _build(tmp_path, "run")

    assert conn.execute("SELECT COUNT(*) FROM shops").fetchone()[0] == 10
    assert conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 200
    assert conn.execute("SELECT COUNT(*) FROM members").fetchone()[0] > 0
    conn.close()


def test_same_seed_reproduces_the_same_district(tmp_path):
    _, first = _build(tmp_path, "a", seed=42)
    _, second = _build(tmp_path, "b", seed=42)

    for table, order_by in (
        ("shops", "fps_id"),
        ("cards", "card_no"),
        ("members", "member_id"),
        ("transactions", "transaction_id"),
    ):
        assert _dump(first, table, order_by) == _dump(second, table, order_by)

    first.close()
    second.close()


def test_a_different_seed_produces_a_different_district(tmp_path):
    _, first = _build(tmp_path, "a", seed=1)
    _, second = _build(tmp_path, "b", seed=2)

    assert _dump(first, "cards", "card_no") != _dump(second, "cards", "card_no")
    first.close()
    second.close()


def test_shops_use_the_fps_and_scheme_conventions(tmp_path):
    _, conn = _build(tmp_path, "run")
    rows = conn.execute("SELECT fps_id, taluka FROM shops").fetchall()
    conn.close()

    assert len(rows) == 10
    for fps_id, taluka in rows:
        assert len(fps_id) == 11 and fps_id.isdigit()
        assert taluka in ("Thane", "Kalyan")


def test_cards_carry_the_fields_the_mockups_need(tmp_path):
    _, conn = _build(tmp_path, "run")
    rows = conn.execute(
        "SELECT scheme, card_type, status, address, village, issue_date "
        "FROM cards"
    ).fetchall()
    conn.close()

    for scheme, card_type, status, address, village, issue_date in rows:
        assert scheme in c.SCHEMES
        assert card_type == c.CARD_TYPE_BY_SCHEME[scheme]
        assert status in ("Active", "Suspended")
        assert address and "Taluka" in address
        assert village
        assert issue_date < c.SIMULATED_TODAY.isoformat()


def test_transactions_happen_at_the_cards_own_shop(tmp_path):
    _, conn = _build(
        tmp_path,
        "run",
        district=District(
            ration_cards=100,
            fps_count=10,
            members_per_card=Span(low=1, high=3),
            transactions_per_card_per_month=Span(low=1, high=2),
        ),
    )
    rows = conn.execute(
        "SELECT t.fps_id, c.fps_id FROM transactions t "
        "JOIN cards c ON c.card_no = t.card_no"
    ).fetchall()
    conn.close()

    assert len(rows) > 0
    for transaction_fps_id, card_fps_id in rows:
        assert transaction_fps_id == card_fps_id


def test_transactions_carry_the_epos_fields(tmp_path):
    _, conn = _build(
        tmp_path,
        "run",
        district=District(
            ration_cards=50,
            fps_count=5,
            members_per_card=Span(low=1, high=3),
            transactions_per_card_per_month=Span(low=1, high=2),
        ),
    )
    rows = conn.execute(
        "SELECT allotment_month, commodity, quantity_kg, auth_mode, status "
        "FROM transactions"
    ).fetchall()
    conn.close()

    assert len(rows) > 0
    for month, commodity, quantity_kg, auth_mode, status in rows:
        assert month == c.SIMULATED_TODAY.strftime("%Y-%m")
        assert commodity in ("rice", "wheat", "sugar")
        assert round(quantity_kg, 3) == quantity_kg
        assert auth_mode in c.AUTH_MODES
        assert status in ("Collected", "Part collected")


def test_member_ages_stay_plausible_for_their_relation(tmp_path):
    _, conn = _build(
        tmp_path,
        "run",
        district=District(
            ration_cards=500,
            fps_count=10,
            members_per_card=Span(low=2, high=7),
            transactions_per_card_per_month=Span(low=0, high=1),
        ),
    )
    rows = conn.execute(
        "SELECT card_no, relation_to_head, age FROM members"
    ).fetchall()
    conn.close()

    head_age = {card_no: age for card_no, relation, age in rows if relation == "Self"}
    parent_relations = {"Father", "Mother"}
    child_relations = {"Son", "Daughter"}
    checked_parent = checked_child = False
    for card_no, relation, age in rows:
        if card_no not in head_age:
            continue
        if relation in parent_relations:
            assert age > head_age[card_no]
            checked_parent = True
        elif relation in child_relations:
            assert age < head_age[card_no]
            checked_child = True

    assert checked_parent and checked_child


def test_entitlement_follows_the_scheme_rules():
    aay = c.entitlement_kg("AAY", member_count=4)
    assert aay["rice"] + aay["wheat"] == 35.0
    assert aay["sugar"] == 1.0

    phh = c.entitlement_kg("NFSA-PHH", member_count=4)
    assert phh["rice"] == 12.0
    assert phh["wheat"] == 8.0


def test_no_price_shown_for_current_grain():
    assert c.ISSUE_PRICE_TEXT == "Free under PMGKAY"
    for old_rate in ("Rs 3", "Rs 2", "Rs. 3", "Rs. 2", "₹3", "₹2"):
        assert old_rate not in c.ISSUE_PRICE_TEXT
