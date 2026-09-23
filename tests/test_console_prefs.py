"""A-, A, A+ and English / Marathi in the utility strip.

Both are plain forms that set a cookie, so they work without JavaScript
and carry across every page. Marathi covers chrome and headings; the
disclaimer line stays in English on every screen (ADR-0005).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from nightkeep.config import load_config
from nightkeep.console.__main__ import create_console_app
from nightkeep.console.i18n import MARATHI, catalogue, translate

CONFIG = load_config(Path(__file__).resolve().parent.parent / "nightkeep" / "config.yaml")
TEMPLATES = Path(__file__).resolve().parent.parent / "nightkeep" / "console" / "templates"
DISCLAIMER = "Prototype on invented data. Not a live government system."


@pytest.fixture
def client():
    app = create_console_app(CONFIG)
    app.config["TESTING"] = True
    return app.test_client()


def scale_of(html: str) -> str:
    return re.search(r"--text-scale: ([0-9.]+);", html).group(1)


# --- A-, A, A+ ------------------------------------------------------------


def test_text_starts_at_normal_size(client):
    assert scale_of(client.get("/").get_data(as_text=True)) == "1.0"


def test_a_plus_and_a_minus_step_through_the_configured_sizes(client):
    client.post("/prefs/text-size", data={"step": "up", "next": "/safety"})
    assert scale_of(client.get("/").get_data(as_text=True)) == "1.125"
    client.post("/prefs/text-size", data={"step": "up"})
    client.post("/prefs/text-size", data={"step": "up"})
    assert scale_of(client.get("/").get_data(as_text=True)) == "1.25"
    client.post("/prefs/text-size", data={"step": "reset"})
    client.post("/prefs/text-size", data={"step": "down"})
    client.post("/prefs/text-size", data={"step": "down"})
    assert scale_of(client.get("/").get_data(as_text=True)) == "0.875"


def test_text_size_returns_to_the_page_it_came_from(client):
    response = client.post("/prefs/text-size", data={"step": "up", "next": "/night-jobs"})
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/night-jobs")


def test_largest_size_disables_a_plus(client):
    for _ in range(5):
        client.post("/prefs/text-size", data={"step": "up"})
    html = client.get("/").get_data(as_text=True)
    assert 'value="up" aria-label="Increase text size" disabled' in html


def test_a_tampered_cookie_falls_back_safely(client):
    client.set_cookie("nk_text", "99")
    assert scale_of(client.get("/").get_data(as_text=True)) == "1.25"
    client.set_cookie("nk_text", "large")
    assert scale_of(client.get("/").get_data(as_text=True)) == "1.0"


def test_every_type_size_follows_the_scale():
    css = (TEMPLATES.parent / "static" / "style.css").read_text(encoding="utf-8")
    sizes = re.findall(r"--font-size-[a-z0-9]+: ([^;]+);", css)
    assert len(sizes) == 7
    assert all("var(--text-scale" in size for size in sizes)
    assert not re.search(r"font-size: \d+(\.\d+)?px;", css)


# --- English / Marathi ------------------------------------------------------


def test_marathi_switches_the_chrome_and_headings(client):
    client.post("/prefs/language", data={"lang": "mr", "next": "/safety"})
    html = client.get("/safety").get_data(as_text=True)
    assert '<html lang="mr"' in html
    assert "शिधापत्रिका शोध" in html          # nav: Ration Card Search
    assert "डेटा सुरक्षा" in html              # nav and heading: Data Safety
    assert "रात्रीची कामे" in html            # nav: Night Jobs
    assert "संरक्षण सारांश" in html            # panel: Protection Summary
    assert DISCLAIMER in html


def test_english_switches_back(client):
    client.post("/prefs/language", data={"lang": "mr"})
    client.post("/prefs/language", data={"lang": "en"})
    html = client.get("/").get_data(as_text=True)
    assert '<html lang="en"' in html
    assert ">Ration Card Search</a>" in html


def test_unknown_language_is_english(client):
    client.post("/prefs/language", data={"lang": "fr"})
    assert '<html lang="en"' in client.get("/").get_data(as_text=True)


@pytest.mark.parametrize("path", ["/", "/safety", "/night-jobs", "/alert",
                                  "/restore", "/it-view", "/showcase", "/locked"])
def test_disclaimer_survives_marathi_on_every_screen(client, path):
    client.post("/prefs/language", data={"lang": "mr"})
    assert DISCLAIMER in client.get(path).get_data(as_text=True)


def test_missing_entries_fall_back_to_english():
    assert translate("A sentence nobody translated.", MARATHI) == "A sentence nobody translated."
    assert translate("Data Safety", "en") == "Data Safety"


def test_every_wrapped_template_string_has_a_marathi_entry():
    """Chrome and headings are fully covered: nothing wrapped in t() with a
    literal string is left in English in Marathi mode."""
    known = catalogue()
    missing = set()
    for template in TEMPLATES.glob("*.html"):
        for text in re.findall(r'\bt\("((?:[^"\\]|\\.)*)"\)', template.read_text(encoding="utf-8")):
            if text not in known:
                missing.add(text)
    assert missing == set()


def test_no_em_dash_in_the_marathi_catalogue():
    for english, marathi in catalogue().items():
        assert "—" not in english and "—" not in marathi
