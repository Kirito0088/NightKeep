"""The district database schema. One function, called once per build."""

import sqlite3

_DDL = """
CREATE TABLE shops (
    fps_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    taluka TEXT NOT NULL,
    village TEXT NOT NULL
);

CREATE TABLE cards (
    card_no TEXT PRIMARY KEY,
    scheme TEXT NOT NULL,
    card_type TEXT NOT NULL,
    status TEXT NOT NULL,
    address TEXT NOT NULL,
    taluka TEXT NOT NULL,
    village TEXT NOT NULL,
    issue_date TEXT NOT NULL,
    fps_id TEXT NOT NULL REFERENCES shops(fps_id)
);

CREATE TABLE members (
    member_id INTEGER PRIMARY KEY,
    card_no TEXT NOT NULL REFERENCES cards(card_no),
    name TEXT NOT NULL,
    sex TEXT NOT NULL,
    age INTEGER NOT NULL,
    relation_to_head TEXT NOT NULL,
    ekyc_status TEXT NOT NULL,
    aadhaar_seeded INTEGER NOT NULL
);

CREATE TABLE transactions (
    transaction_id INTEGER PRIMARY KEY,
    card_no TEXT NOT NULL REFERENCES cards(card_no),
    fps_id TEXT NOT NULL REFERENCES shops(fps_id),
    occurred_at TEXT NOT NULL,
    allotment_month TEXT NOT NULL,
    commodity TEXT NOT NULL,
    quantity_kg REAL NOT NULL,
    auth_mode TEXT NOT NULL,
    status TEXT NOT NULL
);
"""


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_DDL)
