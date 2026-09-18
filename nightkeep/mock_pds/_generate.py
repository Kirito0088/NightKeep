"""Orchestrates one district build: shops, then cards, members, transactions.

One random.Random(seed) instance is threaded through every draw, in a fixed
order, so the same seed always produces the same rows regardless of any
dict/set iteration order elsewhere in the process.
"""

import random
import sqlite3
from datetime import date, datetime, timedelta

from nightkeep.config import District
from nightkeep.mock_pds import conventions as c

_RELATION_SEX = {
    "Son": "Male", "Daughter": "Female",
    "Father": "Male", "Mother": "Female",
    "Brother": "Male", "Sister": "Female",
    "Daughter-in-law": "Female", "Son-in-law": "Male",
    "Grandson": "Male", "Granddaughter": "Female",
}

# Sanity floor/ceiling an age must fall in regardless of the household head's
# own age, so a parent, sibling or grandchild relation can never drift into
# an implausible bracket (a "Father" younger than the head, say).
_AGE_ABSOLUTE_RANGE = {
    "Self": (18, 75), "Spouse": (18, 75),
    "Son": (0, 55), "Daughter": (0, 55),
    "Father": (40, 95), "Mother": (40, 95),
    "Brother": (5, 80), "Sister": (5, 80),
    "Daughter-in-law": (18, 55), "Son-in-law": (18, 55),
    "Grandson": (0, 25), "Granddaughter": (0, 25),
}

_NON_SELF_RELATIONS = tuple(r for r in c.RELATIONS_TO_HEAD if r != "Self")


def generate(conn: sqlite3.Connection, seed: int, district: District) -> None:
    rng = random.Random(seed)
    shop_fps_ids = _generate_shops(rng, conn, district.fps_count)
    used_card_numbers: set[str] = set()
    for _ in range(district.ration_cards):
        card_no, fps_id, entitlement = _generate_card(
            rng, conn, shop_fps_ids, district, used_card_numbers
        )
        _generate_transactions(rng, conn, card_no, fps_id, entitlement, district)
    conn.commit()


def _generate_shops(
    rng: random.Random, conn: sqlite3.Connection, fps_count: int
) -> list[tuple[str, str]]:
    used_ids: set[str] = set()
    rows = []
    for _ in range(fps_count):
        fps_id = c.draw_fps_id(rng)
        while fps_id in used_ids:
            fps_id = c.draw_fps_id(rng)
        used_ids.add(fps_id)
        taluka = rng.choice(c.TALUKAS)
        village = c.draw_village(rng, taluka)
        name = c.draw_shop_name(rng)
        rows.append((fps_id, name, taluka, village))
    conn.executemany(
        "INSERT INTO shops (fps_id, name, taluka, village) VALUES (?, ?, ?, ?)",
        rows,
    )
    return [(fps_id, taluka) for fps_id, _name, taluka, _village in rows]


def _generate_card(
    rng: random.Random,
    conn: sqlite3.Connection,
    shop_fps_ids: list[tuple[str, str]],
    district: District,
    used_card_numbers: set[str],
) -> tuple[str, str, dict[str, float]]:
    card_no = c.draw_card_number(rng)
    while card_no in used_card_numbers:
        card_no = c.draw_card_number(rng)
    used_card_numbers.add(card_no)

    fps_id, taluka = rng.choice(shop_fps_ids)
    scheme = c.draw_scheme(rng)
    village = c.draw_village(rng, taluka)
    address = c.draw_address(rng, taluka)
    issue_date = c.draw_issue_date(rng)
    status = c.draw_card_status(rng)

    conn.execute(
        """INSERT INTO cards
           (card_no, scheme, card_type, status, address, taluka, village,
            issue_date, fps_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            card_no,
            scheme,
            c.CARD_TYPE_BY_SCHEME[scheme],
            status,
            address,
            taluka,
            village,
            issue_date.isoformat(),
            fps_id,
        ),
    )

    member_count = _generate_members(rng, conn, card_no, district)
    entitlement = c.entitlement_kg(scheme, member_count)
    return card_no, fps_id, entitlement


def _draw_age(rng: random.Random, relation: str, head_age: int) -> int:
    """An age plausible for this relation given the household head's age."""
    if relation == "Self":
        return head_age
    if relation == "Spouse":
        candidate = head_age + rng.randint(-8, 8)
    elif relation in ("Son", "Daughter"):
        candidate = head_age - rng.randint(15, 40)
    elif relation in ("Father", "Mother"):
        candidate = head_age + rng.randint(18, 35)
    elif relation in ("Brother", "Sister"):
        candidate = head_age + rng.randint(-12, 12)
    elif relation in ("Daughter-in-law", "Son-in-law"):
        candidate = head_age - rng.randint(10, 30)
    else:  # Grandson, Granddaughter
        candidate = head_age - rng.randint(35, 60)

    low, high = _AGE_ABSOLUTE_RANGE.get(relation, (0, 95))
    return min(max(candidate, low), high)


def _generate_members(
    rng: random.Random,
    conn: sqlite3.Connection,
    card_no: str,
    district: District,
) -> int:
    span = district.members_per_card
    count = max(1, rng.randint(span.low, span.high))
    head_sex = rng.choice(("Male", "Female"))
    head_age = rng.randint(*_AGE_ABSOLUTE_RANGE["Self"])
    father_or_husband = rng.choice(c.MALE_FIRST_NAMES)

    rows = []
    for index in range(count):
        if index == 0:
            relation = "Self"
            sex = head_sex
        else:
            relation = rng.choice(_NON_SELF_RELATIONS)
            if relation == "Spouse":
                sex = "Female" if head_sex == "Male" else "Male"
            else:
                sex = _RELATION_SEX.get(relation, rng.choice(("Male", "Female")))
        age = _draw_age(rng, relation, head_age)
        name = c.draw_name(rng, sex, father_or_husband)
        ekyc_status = c.draw_ekyc_status(rng)
        aadhaar_seeded = int(c.draw_aadhaar_seeded(rng))
        rows.append(
            (card_no, name, sex, age, relation, ekyc_status, aadhaar_seeded)
        )

    conn.executemany(
        """INSERT INTO members
           (card_no, name, sex, age, relation_to_head, ekyc_status,
            aadhaar_seeded)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    return count


def _generate_transactions(
    rng: random.Random,
    conn: sqlite3.Connection,
    card_no: str,
    fps_id: str,
    entitlement: dict[str, float],
    district: District,
) -> None:
    span = district.transactions_per_card_per_month
    count = rng.randint(span.low, span.high)
    if count == 0:
        return

    allotment_month = c.current_allotment_month()

    today = c.SIMULATED_TODAY
    month_start = today.replace(day=1)
    rows = []
    for _ in range(count):
        day = month_start + timedelta(days=rng.randint(0, (today - month_start).days))
        rows.append(
            draw_transaction(rng, card_no, fps_id, entitlement, day, allotment_month)
        )
    insert_transactions(conn, rows)


def draw_transaction(
    rng: random.Random,
    card_no: str,
    fps_id: str,
    entitlement: dict[str, float],
    day: date,
    allotment_month: str,
) -> tuple:
    """One ePoS row for this card at its own shop, in shop hours on day."""
    commodity = rng.choice(list(entitlement))
    ceiling = max(entitlement[commodity], c.MIN_ISSUE_KG)
    quantity_kg = round(rng.uniform(c.MIN_ISSUE_KG, ceiling), 3)
    opens = datetime.combine(day, c.SHOP_OPENS)
    open_seconds = int(
        (datetime.combine(day, c.SHOP_CLOSES) - opens).total_seconds()
    )
    occurred_at = opens + timedelta(seconds=rng.randrange(open_seconds))
    auth_mode = rng.choice(c.AUTH_MODES)
    status = c.draw_transaction_status(rng)
    return (
        card_no,
        fps_id,
        occurred_at.isoformat(),
        allotment_month,
        commodity,
        quantity_kg,
        auth_mode,
        status,
    )


def insert_transactions(conn: sqlite3.Connection, rows: list[tuple]) -> None:
    conn.executemany(
        """INSERT INTO transactions
           (card_no, fps_id, occurred_at, allotment_month, commodity,
            quantity_kg, auth_mode, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
