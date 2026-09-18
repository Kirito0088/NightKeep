"""Name, address and village pools, plus the builders that draw from them.

Split out of conventions.py only because the pools themselves are long.
conventions.py re-exports everything here, so no other module imports
_names.py directly. See CLAUDE.md: "Every generator and every template uses
that file."

Every name below is invented. Villages and localities are invented too, even
though the district (Thane) and talukas (Thane, Kalyan) they sit under are
real: ADR-0006 keeps the geography real but everything attached to it fake.
"""

import random

MALE_FIRST_NAMES = (
    "Ramesh", "Suresh", "Ganesh", "Vitthal", "Sanjay", "Prakash", "Dinesh",
    "Anil", "Sunil", "Vilas", "Shivaji", "Balaji", "Namdev", "Eknath",
    "Bhaskar", "Dattatray", "Vasant", "Pandurang", "Ashok", "Manohar",
)

FEMALE_FIRST_NAMES = (
    "Sunita", "Sunanda", "Kavita", "Meera", "Anita", "Vandana", "Pratibha",
    "Shobha", "Jyoti", "Lata", "Mangala", "Sarita", "Rekha", "Nirmala",
    "Kalpana", "Savita", "Vaishali", "Pushpa", "Sangita", "Usha",
)

SURNAMES = (
    "Kadam", "Patil", "Jadhav", "Shinde", "Pawar", "Deshmukh", "Bhosale",
    "More", "Gaikwad", "Chavan", "Sawant", "Naik", "Joshi", "Kulkarni",
    "Salunkhe", "Thorat", "Waghmare", "Mane", "Kale", "Nikam", "Ghadge",
    "Rane", "Chougule", "Sathe", "Bagul",
)

VILLAGES_BY_TALUKA = {
    "Thane": (
        "Ganeshpada", "Bhairavwadi", "Saraswatipada", "Devnagar",
        "Ambikawadi", "Somnathpada", "Kalikapada", "Shivpada",
    ),
    "Kalyan": (
        "Chandikawadi", "Tulshipada", "Kopreshwarnagar", "Gaurichapada",
        "Bholenathwadi", "Sidheshwarpada", "Kanhopada", "Mauliwadi",
    ),
}

LOCALITIES = (
    "Ganesh Nagar", "Shivaji Chowk", "Tulsi Vihar", "Ambika Colony",
    "Sant Nagar", "Krishna Vihar", "Ram Mandir Road", "Station Road",
    "Gandhi Chowk", "Netaji Nagar", "Kranti Nagar", "Subhash Colony",
)

SHOP_NAME_PREFIXES = (
    "Jai Bhavani", "Jai Malhar", "Ganesh", "Ambika", "Shivshakti",
    "Jai Bhole", "Tuljabhavani", "Vithal Rukmini", "Sai", "Ekvira",
    "Jai Hind", "Krishna",
)
SHOP_NAME_SUFFIX = "Swasta Dhanya Dukan"


def draw_name(rng: random.Random, sex: str, father_or_husband: str) -> str:
    """A Marathi name with a middle name: given, father's/husband's given, surname."""
    pool = MALE_FIRST_NAMES if sex == "Male" else FEMALE_FIRST_NAMES
    given = rng.choice(pool)
    surname = rng.choice(SURNAMES)
    return f"{given} {father_or_husband} {surname}"


def draw_address(rng: random.Random, taluka: str) -> str:
    """A street-level line: plot/house number, an invented locality, the taluka."""
    plot_no = rng.randint(1, 999)
    locality = rng.choice(LOCALITIES)
    return f"Plot No. {plot_no}, {locality}, {taluka} Taluka"


def draw_village(rng: random.Random, taluka: str) -> str:
    return rng.choice(VILLAGES_BY_TALUKA[taluka])


def draw_shop_name(rng: random.Random) -> str:
    return f"{rng.choice(SHOP_NAME_PREFIXES)} {SHOP_NAME_SUFFIX}"


def mask_mobile(rng: random.Random) -> str:
    """A masked mobile number, e.g. '98XXXXXX41'."""
    first_two = rng.choice(("98", "99", "97", "96", "90", "91"))
    last_two = f"{rng.randint(0, 99):02d}"
    return f"{first_two}XXXXXX{last_two}"
