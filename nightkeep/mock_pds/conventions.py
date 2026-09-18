"""Every PDS data convention Nightkeep uses, in one place.

CLAUDE.md: "All of these are constants in one file, mock_pds/conventions.py.
Every generator and every template uses that file." No generator and no
console template keeps its own copy of a card number format, a scheme name
or an entitlement rule.

ADR-0003 fixes the ration card number's leading digits so it can never be
Aadhaar-shaped. ADR-0005 adds the six fields the mockups need (card status,
card type, address, village, issue date, transaction status). ADR-0006 keeps
the district and talukas real (Thane, Kalyan) and everything attached to
them invented.
"""

import random
from datetime import date, time, timedelta

from nightkeep.mock_pds._names import (  # noqa: F401  (re-exported)
    FEMALE_FIRST_NAMES,
    LOCALITIES,
    MALE_FIRST_NAMES,
    SURNAMES,
    VILLAGES_BY_TALUKA,
    draw_address,
    draw_name,
    draw_shop_name,
    draw_village,
    mask_mobile,
)

# --- Ration card numbers (ADR-0003) -----------------------------------

CARD_NUMBER_PREFIX = "11"
CARD_NUMBER_LENGTH = 12

# --- Fair price shops ---------------------------------------------------

FPS_ID_LENGTH = 11

# --- Schemes and card types ----------------------------------------------

SCHEMES = ("AAY", "NFSA-PHH", "Kesari (APL)")
# Most cards are Priority Household, AAY (the poorest-of-poor scheme) is a
# minority, Kesari (above poverty line) is a middle slice.
SCHEME_WEIGHTS = (0.10, 0.65, 0.25)

CARD_TYPE_BY_SCHEME = {
    "AAY": "Antyodaya",
    "NFSA-PHH": "Priority Household",
    "Kesari (APL)": "Kesari",
}

# --- Card status (ADR-0005) ----------------------------------------------

CARD_STATUSES = ("Active", "Suspended")
CARD_STATUS_WEIGHTS = (0.92, 0.08)

# --- Issue price -----------------------------------------------------------

ISSUE_PRICE_TEXT = "Free under PMGKAY"

# --- ePoS transactions -----------------------------------------------------

AUTH_MODES = ("Biometric", "Iris", "OTP", "Nominee")
TRANSACTION_STATUSES = ("Collected", "Part collected")
TRANSACTION_STATUS_WEIGHTS = (0.85, 0.15)
# ePoS counters are open these hours. Every transaction falls inside them.
SHOP_OPENS = time(9, 0)
SHOP_CLOSES = time(18, 0)
# The smallest quantity an ePoS counter issues in one transaction.
MIN_ISSUE_KG = 0.5

# --- Members ---------------------------------------------------------------

RELATIONS_TO_HEAD = (
    "Self", "Spouse", "Son", "Daughter", "Father", "Mother", "Brother",
    "Sister", "Daughter-in-law", "Son-in-law", "Grandson", "Granddaughter",
)
EKYC_STATUSES = ("Done", "Pending")
EKYC_STATUS_WEIGHTS = (0.7, 0.3)
AADHAAR_SEEDED_PROBABILITY = 0.75

# --- District and talukas (ADR-0006) ---------------------------------------

DISTRICT = "Thane"
TALUKAS = ("Thane", "Kalyan")

# The fixed anchor every relative date (card issue date, current allotment
# month) is computed against, so build_district stays reproducible
# independent of the real calendar. Matches the Round 2 demo date.
SIMULATED_TODAY = date(2026, 9, 22)

_ISSUE_DATE_EARLIEST_YEARS_AGO = 8
_ISSUE_DATE_LATEST_DAYS_AGO = 90


def draw_scheme(rng: random.Random) -> str:
    return rng.choices(SCHEMES, weights=SCHEME_WEIGHTS, k=1)[0]


def draw_card_status(rng: random.Random) -> str:
    return rng.choices(CARD_STATUSES, weights=CARD_STATUS_WEIGHTS, k=1)[0]


def draw_transaction_status(rng: random.Random) -> str:
    return rng.choices(
        TRANSACTION_STATUSES, weights=TRANSACTION_STATUS_WEIGHTS, k=1
    )[0]


def draw_ekyc_status(rng: random.Random) -> str:
    return rng.choices(EKYC_STATUSES, weights=EKYC_STATUS_WEIGHTS, k=1)[0]


def draw_aadhaar_seeded(rng: random.Random) -> bool:
    return rng.random() < AADHAAR_SEEDED_PROBABILITY


def draw_card_number(rng: random.Random) -> str:
    """A 12-digit card number, no prefix, no dashes. Never Aadhaar-shaped.

    Aadhaar never begins with 0 or 1, so fixing the leading digits at "11"
    satisfies "no Aadhaar-format numbers" by construction, not by chance.
    """
    remaining_digits = CARD_NUMBER_LENGTH - len(CARD_NUMBER_PREFIX)
    tail = "".join(str(rng.randint(0, 9)) for _ in range(remaining_digits))
    return f"{CARD_NUMBER_PREFIX}{tail}"


def draw_fps_id(rng: random.Random) -> str:
    """An 11-digit numeric FPS ID, first digit non-zero."""
    first = str(rng.randint(1, 9))
    rest = "".join(str(rng.randint(0, 9)) for _ in range(FPS_ID_LENGTH - 1))
    return f"{first}{rest}"


def draw_issue_date(rng: random.Random) -> date:
    """A seeded date, plausible for an active card: multi-year range ending
    before the simulated present."""
    earliest = SIMULATED_TODAY - timedelta(
        days=365 * _ISSUE_DATE_EARLIEST_YEARS_AGO
    )
    latest = SIMULATED_TODAY - timedelta(days=_ISSUE_DATE_LATEST_DAYS_AGO)
    span_days = (latest - earliest).days
    return earliest + timedelta(days=rng.randint(0, span_days))


def current_allotment_month() -> str:
    return SIMULATED_TODAY.strftime("%Y-%m")


def entitlement_kg(scheme: str, member_count: int) -> dict[str, float]:
    """Monthly foodgrain entitlement in kg, by scheme.

    NFSA-PHH draws 5 kg per member (3 kg rice, 2 kg wheat), issued in
    Maharashtra, sourced in CLAUDE.md's PDS data conventions table. AAY is
    35 kg per card regardless of family size, plus 1 kg sugar, also sourced.

    Kesari (APL) has no sourced entitlement figure (CLAUDE.md's table only
    covers PHH and AAY), so it draws the same per-member formula as PHH as a
    placeholder pending a sourced figure, the same way ADR-0005 flagged the
    unsourced card-colour claim rather than publishing it silently.
    """
    if scheme == "AAY":
        return {"rice": 21.0, "wheat": 14.0, "sugar": 1.0}
    rice = round(3.0 * member_count, 3)
    wheat = round(2.0 * member_count, 3)
    return {"rice": rice, "wheat": wheat}
