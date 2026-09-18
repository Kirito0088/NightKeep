"""Flask application for the Nightkeep Vault console.

The console is intentionally shallow: routes prepare presentation context and
Jinja renders it. Detection, storage, and recovery logic belong to their own
modules.
"""

from __future__ import annotations

import random
from typing import Any

from flask import Flask, render_template, request

from nightkeep.mock_pds import conventions as c


def _default_cards() -> list[dict[str, str]]:
    rng = random.Random(20260922)
    cards: list[dict[str, str]] = []

    for _ in range(5):
        taluka = rng.choice(c.TALUKAS)
        sex = rng.choice(("Male", "Female"))
        middle = rng.choice(c.MALE_FIRST_NAMES)
        card = {
            "card_no": c.draw_card_number(rng),
            "head_of_family": c.draw_name(rng, sex, middle),
            "taluka": taluka,
            "village": c.draw_village(rng, taluka),
            "fps_id": c.draw_fps_id(rng),
            "fps_name": c.draw_shop_name(rng),
            "scheme": c.draw_scheme(rng),
            "status": c.draw_card_status(rng),
        }
        cards.append(card)

    return cards


def _filter_cards(
    cards: list[dict[str, str]],
    filters: dict[str, str],
) -> list[dict[str, str]]:
    def matches(card: dict[str, str]) -> bool:
        if filters["card_no"] and filters["card_no"] not in card["card_no"]:
            return False
        if (
            filters["head_of_family"]
            and filters["head_of_family"].lower() not in card["head_of_family"].lower()
        ):
            return False
        if filters["taluka"] and filters["taluka"] != card["taluka"]:
            return False
        if filters["fps_id"] and filters["fps_id"].lower() not in (
            f"{card['fps_id']} {card['fps_name']}".lower()
        ):
            return False
        if filters["scheme"] and filters["scheme"] != card["scheme"]:
            return False
        if filters["status"] and filters["status"] != card["status"]:
            return False
        return True

    return [card for card in cards if matches(card)]


def _format_number(value: int) -> str:
    return f"{value:,}"


def create_app(
    district_summary: dict[str, Any] | None = None,
    sample_cards: list[dict[str, str]] | None = None,
) -> Flask:
    app = Flask(__name__)

    cards = list(sample_cards) if sample_cards is not None else _default_cards()
    summary = district_summary or {
        "ration_cards": 5000,
        "fps_count": 50,
    }

    app.jinja_env.filters["format_number"] = _format_number

    @app.get("/")
    def index() -> str:
        return _render_search(cards, summary)

    @app.get("/search")
    def search() -> str:
        return _render_search(cards, summary)

    def _render_search(
        records: list[dict[str, str]],
        district_summary: dict[str, Any],
    ) -> str:
        filters = {
            "card_no": request.args.get("card_no", "", type=str).strip(),
            "head_of_family": request.args.get("head_of_family", "", type=str).strip(),
            "taluka": request.args.get("taluka", "", type=str).strip(),
            "fps_id": request.args.get("fps_id", "", type=str).strip(),
            "scheme": request.args.get("scheme", "", type=str).strip(),
            "status": request.args.get("status", "", type=str).strip(),
        }

        filtered = _filter_cards(records, filters)

        return render_template(
            "search.html",
            district_summary=district_summary,
            cards=filtered,
            cards_total=len(records),
            filters=filters,
            talukas=c.TALUKAS,
            schemes=c.SCHEMES,
            statuses=c.CARD_STATUSES,
        )

    app.config["HOST"] = "127.0.0.1"
    app.config["PORT"] = 5000

    return app
