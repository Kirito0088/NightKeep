"""Tests for Feature 1: Console foundation + Ration Card Search screen."""

import re
from pathlib import Path
import pytest
from nightkeep.console.app import DEFAULT_SAMPLE_RECORDS, create_app

CONSOLE_DIR = Path(__file__).resolve().parent.parent / "nightkeep" / "console"


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_app_creation():
    app = create_app()
    assert app is not None


def test_get_root_renders_search(client):
    response = client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Ration Card Search" in html
    assert "District Supply Office, Thane" in html


def test_get_search_returns_200(client):
    response = client.get("/search")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "<h1>Ration Card Search</h1>" in html


def test_default_screen_renders_exactly_five_rows(client):
    response = client.get("/search")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    # Check each default card number is in the rendered page
    for record in DEFAULT_SAMPLE_RECORDS:
        assert record.card_no in html
        assert record.head_of_family in html

    # Count rows in tbody
    tbody_content = html.split("<tbody>")[1].split("</tbody>")[0]
    row_count = tbody_content.count("<tr")
    assert row_count == 5


def test_mandatory_disclaimer_present(client):
    response = client.get("/search")
    html = response.get_data(as_text=True)
    disclaimer = "Prototype on invented data. Not a live government system."
    assert disclaimer in html


def test_bilingual_office_titles_present(client):
    response = client.get("/search")
    html = response.get_data(as_text=True)
    assert "जिल्हा पुरवठा कार्यालय, ठाणे" in html
    assert "District Supply Office, Thane" in html


def test_district_figures_present(client):
    response = client.get("/search")
    html = response.get_data(as_text=True)
    assert "5,000" in html
    assert "ration cards" in html
    assert "50" in html
    assert "fair price shops" in html


def test_data_safety_panel_present(client):
    response = client.get("/search")
    html = response.get_data(as_text=True)
    assert "Data Safety" in html
    assert "Open Data Safety" in html


def test_semantic_table_markup(client):
    response = client.get("/search")
    html = response.get_data(as_text=True)
    assert "<table" in html
    assert "<caption" in html
    assert "<thead" in html
    assert "<tbody" in html
    assert "<th scope=\"col\">Card Number</th>" in html
    assert "<th scope=\"col\">Head of Family</th>" in html
    assert "<th scope=\"col\">Taluka / Village</th>" in html
    assert "<th scope=\"col\">Fair Price Shop</th>" in html
    assert "<th scope=\"col\">Scheme</th>" in html
    assert "<th scope=\"col\">Status</th>" in html


def test_explicit_label_associations(client):
    response = client.get("/search")
    html = response.get_data(as_text=True)

    expected_associations = [
        ("card_no", "Ration card number"),
        ("head_of_family", "Head of family"),
        ("taluka", "Taluka"),
        ("fps", "Fair Price Shop"),
        ("scheme", "Scheme"),
        ("status", "Status"),
    ]

    for field_id, label_text in expected_associations:
        pattern = rf'<label\s+for="{field_id}"[^>]*>\s*{re.escape(label_text)}\s*</label>'
        assert re.search(pattern, html) is not None, f"Missing explicit label for {field_id}"
        assert f'id="{field_id}"' in html, f"Missing input id for {field_id}"


def test_skip_link_target(client):
    response = client.get("/search")
    html = response.get_data(as_text=True)
    assert '<a href="#main-content" class="skip-link">Skip to main content</a>' in html
    assert 'id="main-content"' in html


def test_loopback_configuration():
    main_file = CONSOLE_DIR / "__main__.py"
    assert main_file.is_file()
    content = main_file.read_text(encoding="utf-8")
    assert '127.0.0.1' in content
    assert '0.0.0.0' not in content


def test_no_em_dashes_in_console_assets():
    files_to_check = [
        CONSOLE_DIR / "static" / "style.css",
        CONSOLE_DIR / "templates" / "base.html",
        CONSOLE_DIR / "templates" / "search.html",
        CONSOLE_DIR / "app.py",
        CONSOLE_DIR / "__init__.py",
        CONSOLE_DIR / "__main__.py",
    ]

    for file_path in files_to_check:
        assert file_path.is_file(), f"Expected file {file_path} to exist"
        content = file_path.read_text(encoding="utf-8")
        assert "—" not in content, f"Em-dash found in {file_path}"
        assert "&mdash;" not in content, f"HTML entity em-dash found in {file_path}"
        assert "\u2014" not in content, f"Unicode em-dash found in {file_path}"


def test_card_number_format(client):
    response = client.get("/search")
    html = response.get_data(as_text=True)

    card_numbers = re.findall(r'class="card-number-link">(\d+)</a>', html)
    assert len(card_numbers) == 5
    for num in card_numbers:
        assert len(num) == 12, f"Card number {num} is not 12 digits"
        assert num.startswith("11"), f"Card number {num} does not start with 11"


def test_search_filter_changes_result_set(client):
    # Default gives 5 rows
    default_resp = client.get("/search")
    default_html = default_resp.get_data(as_text=True)
    assert "5 records found" in default_html

    # Filter by status=Suspended gives 1 row
    suspended_resp = client.get("/search?status=Suspended")
    suspended_html = suspended_resp.get_data(as_text=True)
    assert "1 records found" in suspended_html
    suspended_tbody = suspended_html.split("<tbody>")[1].split("</tbody>")[0]
    assert "Anil Eknath More" in suspended_tbody
    assert "Sunita Ramesh Kadam" not in suspended_tbody

    # Filter by scheme=AAY gives 1 row
    aay_resp = client.get("/search?scheme=AAY")
    aay_html = aay_resp.get_data(as_text=True)
    assert "1 records found" in aay_html
    aay_tbody = aay_html.split("<tbody>")[1].split("</tbody>")[0]
    assert "Rajesh Vithal Shinde" in aay_tbody
    assert "Anil Eknath More" not in aay_tbody

    # Filter with no matches
    nomatch_resp = client.get("/search?head_of_family=NonexistentPerson")
    nomatch_html = nomatch_resp.get_data(as_text=True)
    assert "0 records found" in nomatch_html
    nomatch_tbody = nomatch_html.split("<tbody>")[1].split("</tbody>")[0]
    assert "No ration cards found matching the criteria" in nomatch_tbody
    assert "Clear Filters" in nomatch_tbody
    assert 'href="/search"' in nomatch_tbody


def test_card_number_links_target_detail_route(client):
    response = client.get("/search")
    html = response.get_data(as_text=True)

    for record in DEFAULT_SAMPLE_RECORDS:
        expected_link = f'href="/card/{record.card_no}"'
        assert expected_link in html, f"Expected detail link {expected_link} not found in search results"


def test_search_form_contains_reset_action(client):
    response = client.get("/search")
    html = response.get_data(as_text=True)

    assert "Reset Filters" in html
    assert 'class="btn btn-secondary btn-reset"' in html


def test_empty_state_contains_clear_action(client):
    response = client.get("/search?card_no=999999999999")
    html = response.get_data(as_text=True)

    assert "Clear Filters" in html
    assert "empty-results-message" in html
    assert 'class="btn btn-secondary btn-reset-empty"' in html


def test_main_content_has_max_width_constraint():
    style_path = CONSOLE_DIR / "static" / "style.css"
    content = style_path.read_text(encoding="utf-8")
    assert "max-width: 1280px;" in content
    assert "transform: translateY(1px);" in content
    assert "text-wrap: pretty;" in content

