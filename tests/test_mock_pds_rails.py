"""The hard safety rails around mock_pds, as tests.

CLAUDE.md: "No real personal data anywhere, ever" and "No Aadhaar-shaped
numbers, ever. No field named aadhaar_no." ADR-0003 requires a test that no
generated ration card number begins with a digit 2 to 9, and that no field
named aadhaar_no exists in the schema.
"""

import ast
from pathlib import Path

from nightkeep.config import District, Span
from nightkeep.mock_pds import build_district
from nightkeep.mock_pds import conventions as c

MOCK_PDS = Path(__file__).resolve().parent.parent / "nightkeep" / "mock_pds"

DISTRICT = District(
    ration_cards=300,
    fps_count=10,
    members_per_card=Span(low=1, high=5),
    transactions_per_card_per_month=Span(low=0, high=2),
)


def _build(tmp_path, seed=20260922):
    out_dir = build_district(seed, DISTRICT, tmp_path / "run")
    import sqlite3

    return sqlite3.connect(out_dir / "data" / "district.db")


def test_no_card_number_is_aadhaar_shaped(tmp_path):
    conn = _build(tmp_path)
    card_numbers = [row[0] for row in conn.execute("SELECT card_no FROM cards")]
    conn.close()

    assert len(card_numbers) == DISTRICT.ration_cards
    for card_no in card_numbers:
        assert len(card_no) == 12
        assert card_no.isdigit()
        # Aadhaar never begins with 0 or 1.
        assert card_no[0] in "01"


def test_no_field_named_aadhaar_no_anywhere(tmp_path):
    conn = _build(tmp_path)
    columns = [
        row[1]
        for table in ("shops", "cards", "members", "transactions")
        for row in conn.execute(f"PRAGMA table_info({table})")
    ]
    conn.close()

    assert "aadhaar_no" not in columns

    for source in MOCK_PDS.glob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        names = {
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name)
        } | {
            node.arg
            for node in ast.walk(tree)
            if isinstance(node, ast.arg)
        }
        assert "aadhaar_no" not in names, source


def test_names_come_from_the_fixed_invented_pools(tmp_path):
    conn = _build(tmp_path)
    names = [row[0] for row in conn.execute("SELECT name FROM members")]
    conn.close()

    assert len(names) > 0
    first_names = set(c.MALE_FIRST_NAMES) | set(c.FEMALE_FIRST_NAMES)
    for name in names:
        given, middle, surname = name.split(" ")
        assert given in first_names
        assert middle in c.MALE_FIRST_NAMES
        assert surname in c.SURNAMES


def test_mobile_numbers_are_masked():
    import random

    rng = random.Random(1)
    for _ in range(20):
        masked = c.mask_mobile(rng)
        assert len(masked) == 10
        assert "XXXXXX" in masked


def test_shops_and_cards_are_confined_to_the_modelled_talukas(tmp_path):
    conn = _build(tmp_path)
    talukas = {row[0] for row in conn.execute("SELECT DISTINCT taluka FROM shops")}
    talukas |= {row[0] for row in conn.execute("SELECT DISTINCT taluka FROM cards")}
    conn.close()

    assert talukas <= {"Thane", "Kalyan"}
