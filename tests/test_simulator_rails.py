"""The simulator's one hard safety rail, as a test.

CLAUDE.md: the simulator "hard-codes a path check and refuses to run
outside the demo folder." Here "the demo folder" means a folder
mock_pds.build_district actually built, checked by reading the district
database's own schema, not by trusting a folder name.
"""

import sqlite3

import pytest

from nightkeep.config import District, Span
from nightkeep.mock_pds import build_district
from nightkeep.simulator._rails import UnsafeRootError, confirm_demo_district

DISTRICT = District(
    ration_cards=50,
    fps_count=5,
    members_per_card=Span(low=1, high=5),
    transactions_per_card_per_month=Span(low=0, high=2),
)


def test_a_folder_mock_pds_built_is_accepted(tmp_path):
    district_dir = build_district(20260922, DISTRICT, tmp_path / "district")
    assert confirm_demo_district(district_dir) == district_dir.resolve()


def test_a_folder_named_demo_that_mock_pds_never_built_is_refused(tmp_path):
    fake = tmp_path / "demo"
    (fake / "data").mkdir(parents=True)
    (fake / "data" / "district.db").write_bytes(b"not a database")

    with pytest.raises(UnsafeRootError):
        confirm_demo_district(fake)


def test_an_ordinary_folder_with_no_database_at_all_is_refused(tmp_path):
    with pytest.raises(UnsafeRootError):
        confirm_demo_district(tmp_path)


def test_a_database_missing_one_required_table_is_refused(tmp_path):
    root = tmp_path / "district"
    (root / "data").mkdir(parents=True)
    connection = sqlite3.connect(root / "data" / "district.db")
    connection.execute("CREATE TABLE cards (card_no TEXT)")
    connection.commit()
    connection.close()

    with pytest.raises(UnsafeRootError):
        confirm_demo_district(root)
