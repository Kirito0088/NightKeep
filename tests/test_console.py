from pathlib import Path
import re

from nightkeep.console import create_app


REPO_ROOT = Path(__file__).resolve().parent.parent
CONSOLE_DIR = REPO_ROOT / "nightkeep" / "console"


def test_get_root_returns_200_and_renders_five_rows():
    app = create_app()
    client = app.test_client()

    response = client.get("/")

    assert response.status_code == 200
    assert len(re.findall(rb"<tbody>\s*<tr>", response.data)) == 1
    assert response.data.count(b"<tr>") == 6


def test_get_search_returns_200():
    app = create_app()
    response = app.test_client().get("/search")

    assert response.status_code == 200


def test_search_filters_sample_rows():
    app = create_app()
    response = app.test_client().get("/search?taluka=Thane")

    assert response.status_code == 200
    assert b"Showing 2" in response.data or b"Showing 3" in response.data or b"Showing 4" in response.data or b"Showing 5" in response.data


def test_required_disclaimer_is_present():
    app = create_app()
    response = app.test_client().get("/")

    assert b"Prototype on invented data. Not a live government system." in response.data


def test_accessibility_and_semantic_markup():
    app = create_app()
    html = app.test_client().get("/").data.decode("utf-8")

    assert 'href="#main-content"' in html
    assert 'id="main-content"' in html
    assert "<table" in html
    assert "<thead>" in html
    assert "<tbody>" in html
    for field_id in (
        "card_no",
        "head_of_family",
        "taluka",
        "fps_id",
        "scheme",
        "status",
    ):
        assert f'for="{field_id}"' in html
        assert f'id="{field_id}"' in html


def test_loopback_host_configuration():
    app = create_app()

    assert app.config["HOST"] == "127.0.0.1"
    assert app.config["PORT"] == 5000


def test_no_em_dash_in_console_assets():
    for path in (
        CONSOLE_DIR / "app.py",
        CONSOLE_DIR / "__init__.py",
        CONSOLE_DIR / "__main__.py",
        CONSOLE_DIR / "templates" / "base.html",
        CONSOLE_DIR / "templates" / "search.html",
        CONSOLE_DIR / "static" / "style.css",
    ):
        assert "\u2014" not in path.read_text(encoding="utf-8")


def test_card_numbers_follow_the_convention():
    app = create_app()
    html = app.test_client().get("/").data.decode("utf-8")

    numbers = re.findall(r">\s*(11\d{10})\s*</a>", html)
    assert len(numbers) == 5
    assert all(len(value) == 12 for value in numbers)
