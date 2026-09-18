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
        CONSOLE_DIR / "templates" / "card_detail.html",
        CONSOLE_DIR / "templates" / "card_not_found.html",
        CONSOLE_DIR / "templates" / "locked.html",
        CONSOLE_DIR / "templates" / "safety.html",
        CONSOLE_DIR / "templates" / "alert.html",
        CONSOLE_DIR / "templates" / "restore.html",
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


def test_card_detail_returns_200(client):
    response = client.get("/card/110300512847")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Ration Card Detail: 110300512847" in html
    assert "Sunita Ramesh Kadam" in html


def test_card_detail_household_summary(client):
    response = client.get("/card/110300512847")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "Household Details" in html
    assert "110300512847" in html
    assert "Sunita Ramesh Kadam" in html
    assert "Priority Household (NFSA-PHH)" in html
    assert "Active" in html
    assert "Plot 14, Ghodbunder Road, Navghar, Thane" in html
    assert "Thane / Navghar" in html
    assert "14 Mar 2021" in html
    assert "98XXXXXX41" in html
    assert "27030300145" in html
    assert "Jai Bhavani Swasta Dhanya Dukan" in html
    assert "1 Cylinder (HP Gas)" in html
    assert "3 of 4 members seeded" in html


def test_card_detail_monthly_entitlement(client):
    response = client.get("/card/110300512847")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "Monthly Entitlement" in html
    assert "Free under PMGKAY" in html
    assert "Rice" in html
    assert "12.000 kg" in html
    assert "Wheat" in html
    assert "8.000 kg" in html
    assert "20.000 kg" in html
    assert "3.000 kg per member" in html
    assert "2.000 kg per member" in html


def test_card_detail_family_members_table(client):
    response = client.get("/card/110300512847")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "Family Members" in html
    assert "4 members registered" in html
    assert '<th scope="col">Sr No</th>' in html
    assert '<th scope="col">Member Name</th>' in html
    assert '<th scope="col">Relation to Head</th>' in html
    assert '<th scope="col">Sex</th>' in html
    assert '<th scope="col">Age</th>' in html
    assert '<th scope="col">Aadhaar Seeded</th>' in html
    assert '<th scope="col">e-KYC Status</th>' in html

    # Verify member rows
    assert "Sunita Ramesh Kadam" in html
    assert "Ramesh Ananda Kadam" in html
    assert "Amit Ramesh Kadam" in html
    assert "Priya Ramesh Kadam" in html

    # Verify e-KYC statuses
    assert "Done" in html
    assert "Pending" in html


def test_card_detail_epos_transactions(client):
    response = client.get("/card/110300512847")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "ePoS Collection History" in html
    assert '<th scope="col">Date &amp; Time</th>' in html
    assert '<th scope="col">Allotment Month</th>' in html
    assert '<th scope="col">Commodity / Quantity</th>' in html
    assert '<th scope="col">Fair Price Shop</th>' in html
    assert '<th scope="col">Authentication Mode</th>' in html
    assert '<th scope="col">Status</th>' in html

    assert "2026-09-08 11:24" in html
    assert "Biometric" in html
    assert "Collected" in html


def test_card_detail_not_found_404(client):
    response = client.get("/card/999999999999")
    assert response.status_code == 404
    html = response.get_data(as_text=True)
    assert "Ration Card Not Found" in html
    assert "999999999999" in html
    assert "Return to Ration Card Search" in html


def test_card_detail_disclaimer_and_skip_link(client):
    response = client.get("/card/110300512847")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "Prototype on invented data. Not a live government system." in html
    assert '<a href="#main-content" class="skip-link">Skip to main content</a>' in html
    assert 'id="main-content"' in html


def test_all_default_sample_cards_open_successfully(client):
    for record in DEFAULT_SAMPLE_RECORDS:
        response = client.get(f"/card/{record.card_no}")
        assert response.status_code == 200, f"Card {record.card_no} failed to load"
        html = response.get_data(as_text=True)
        assert record.head_of_family in html
        assert record.card_no in html


def test_locked_route_returns_200(client):
    response = client.get("/locked")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Ration Card Search (System Protected)" in html


def test_locked_route_has_primary_message(client):
    response = client.get("/locked")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    # Must contain exact operational message
    assert "Ration card records cannot be opened" in html


def test_locked_route_has_empty_results_table(client):
    response = client.get("/locked")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "0 records available" in html
    assert "Ration card records cannot be opened" in html
    assert "Database access is suspended to prevent file damage." in html


def test_locked_route_has_ransom_note(client):
    response = client.get("/locked")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "Simulated Ransom Note (Demonstration Artifact)" in html
    assert "PROTOTYPE DEMONSTRATION ARTIFACT" in html
    assert "README_LOCKED.txt" in html
    assert "NIGHTKEEP-SIM-2026" in html


def test_locked_route_has_what_the_office_does_next(client):
    response = client.get("/locked")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "What the office does next" in html
    # Step 1 highlighted
    assert "Do not restart the office computer." in html
    assert "Restarting can wipe the evidence and can let the locking program start again." in html
    # Step 2
    assert "Disconnect the network cable." in html
    # Step 3
    assert "Inform the District Supply Office IT team." in html


def test_locked_route_has_open_data_safety_and_no_dead_anchor(client):
    response = client.get("/locked")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "Open Data Safety" in html
    # Reject dead anchor href="#" for Open Data Safety
    assert '<a href="#" class="btn btn-secondary btn-data-safety">Open Data Safety</a>' not in html
    assert '<a href="#"' not in html, "Found dead anchor href='#' in locked template"


def test_locked_route_retains_government_chrome(client):
    response = client.get("/locked")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "जिल्हा पुरवठा कार्यालय, ठाणे" in html
    assert "District Supply Office, Thane" in html
    assert "Prototype on invented data. Not a live government system." in html
    assert '<a href="#main-content" class="skip-link">Skip to main content</a>' in html
    assert 'id="main-content"' in html


def test_locked_route_no_technical_detection_terms(client):
    response = client.get("/locked")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    # Technical detection terms must not leak to the counter clerk
    technical_terms = [
        "entropy",
        "SHA-256",
        "sha256",
        "Habit Score",
        "habit score",
        "MAD",
        "script hash",
        "manifest",
        "snapshot ID",
        "watcher internals",
        "verdict table",
    ]
    for term in technical_terms:
        assert term not in html, f"Technical term '{term}' leaked to clerk-facing locked screen"


def test_safety_home_returns_200(client):
    response = client.get("/safety")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Data Safety" in html


def test_safety_home_protection_headline(client):
    response = client.get("/safety")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Your records are safe" in html
    assert "STATUS: NORMAL" in html


def test_safety_home_protected_record_count(client):
    response = client.get("/safety")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "5,000" in html
    assert "ration cards protected" in html


def test_safety_home_clean_point(client):
    response = client.get("/safety")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Day 9, 01:20" in html
    assert "24" in html
    assert "safe copies on Vault" in html


def test_safety_home_night_tasks_table(client):
    response = client.get("/safety")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "Night Tasks Activity" in html
    assert '<th scope="col">Task</th>' in html
    assert '<th scope="col">Usually</th>' in html
    assert '<th scope="col">Last night</th>' in html
    assert '<th scope="col">Status</th>' in html

    # Verify all 6 documented task names
    assert "Day-end upload" in html
    assert "Allotment file creation" in html
    assert "Safe copy of the database" in html
    assert "Old file clean-up" in html
    assert "Data format maintenance" in html
    assert "Counter clerk entries" in html

    # Count rows in tbody
    tbody_content = html.split("<tbody>")[1].split("</tbody>")[0]
    row_count = tbody_content.count("<tr")
    assert row_count == 6


def test_safety_home_later_than_usual_state(client):
    response = client.get("/safety")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "Later than usual" in html
    assert "03:40 (6 files modified)" in html


def test_safety_home_for_it_person_present(client):
    response = client.get("/safety")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "For the IT person" in html
    assert "btn-it-access" in html
    # Check no dead anchor href="#"
    assert '<a href="#"' not in html, "Found dead anchor href='#' in safety template"


def test_safety_home_retains_government_chrome(client):
    response = client.get("/safety")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "जिल्हा पुरवठा कार्यालय, ठाणे" in html
    assert "District Supply Office, Thane" in html
    assert "Prototype on invented data. Not a live government system." in html
    assert '<a href="#main-content" class="skip-link">Skip to main content</a>' in html
    assert 'id="main-content"' in html


def test_safety_home_no_technical_detection_terms_in_clerk_sections(client):
    response = client.get("/safety")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    # Inspect clerk-facing content only (preceding the IT-person section)
    clerk_content = html.split('class="panel-block it-person-section"')[0]
    technical_terms = [
        "entropy",
        "SHA-256",
        "sha256",
        "Habit Score",
        "habit score",
        "MAD",
        "snapshot ID",
        "verdict table",
    ]
    for term in technical_terms:
        assert term not in clerk_content, f"Technical term '{term}' leaked to clerk-facing safety content"


def test_search_and_locked_open_data_safety_link_to_safety(client):
    # Test search screen link
    search_resp = client.get("/search")
    assert search_resp.status_code == 200
    search_html = search_resp.get_data(as_text=True)
    assert 'href="/safety"' in search_html

    # Test locked screen link
    locked_resp = client.get("/locked")
    assert locked_resp.status_code == 200
    locked_html = locked_resp.get_data(as_text=True)
    assert 'href="/safety"' in locked_html


def test_alert_route_returns_200(client):
    response = client.get("/alert")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Incident Alert" in html


def test_alert_exact_headline_present(client):
    response = client.get("/alert")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Someone tried to lock your files. It was stopped." in html
    assert "STATUS: ATTACK STOPPED" in html


def test_alert_four_summary_figures_present(client):
    response = client.get("/alert")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    # All four documented figures must be present
    assert "37 files damaged" in html
    assert "Detected in 6 seconds" in html
    assert "Clean copy from 01:20 ready" in html
    assert "19 counter entries to re-check" in html

    # Tabular values and labels
    assert "37" in html
    assert "files damaged" in html
    assert "6s" in html
    assert "01:20" in html
    assert "19" in html
    assert "counter entries to re-check" in html


def test_alert_five_step_timeline_present(client):
    response = client.get("/alert")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "Incident Timeline" in html
    assert "Suspicious activity began" in html
    assert "Detected in 6 seconds" in html
    assert "37 files damaged" in html
    assert "Clean copy from 01:20 ready" in html
    assert "Office follow-up required" in html

    timeline_content = html.split('<ol class="timeline-list">')[1].split("</ol>")[0]
    assert timeline_content.count('class="timeline-item"') == 5


def test_alert_three_action_steps_present(client):
    response = client.get("/alert")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "What to do now" in html
    # Step 1 highlighted
    assert "Do not restart the office computer." in html
    assert "Restarting can wipe the evidence and can let the locking program start again." in html
    # Step 2
    assert "Disconnect the network cable." in html
    assert "Keep this computer separated until the district technician arrives." in html
    # Step 3
    assert "Restore records using the clean copy." in html
    assert "Safe copies are preserved on the Vault." in html


def test_alert_get_my_records_back_action(client):
    response = client.get("/alert")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "Get my records back" in html
    assert 'href="/restore"' in html
    assert '<a href="#"' not in html, "Found dead anchor href='#' in alert template"


def test_alert_for_it_person_present(client):
    response = client.get("/alert")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "For the IT person" in html
    assert "btn-it-access" in html
    assert '<a href="#"' not in html, "Found dead anchor href='#' in alert template"


def test_alert_retains_government_chrome(client):
    response = client.get("/alert")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "जिल्हा पुरवठा कार्यालय, ठाणे" in html
    assert "District Supply Office, Thane" in html
    assert "Prototype on invented data. Not a live government system." in html
    assert '<a href="#main-content" class="skip-link">Skip to main content</a>' in html
    assert 'id="main-content"' in html


def test_alert_no_technical_detection_terms_in_clerk_sections(client):
    response = client.get("/alert")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    # Inspect clerk-facing content only (preceding the IT-person section)
    clerk_content = html.split('class="panel-block it-person-section"')[0]
    technical_terms = [
        "entropy",
        "SHA-256",
        "sha256",
        "Habit Score",
        "habit score",
        "MAD",
        "snapshot ID",
        "verdict table",
        "script hash",
        "watcher internals",
    ]
    for term in technical_terms:
        assert term not in clerk_content, f"Technical term '{term}' leaked to clerk-facing alert content"


def test_restore_placeholder_route_returns_200(client):
    response = client.get("/restore")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Get my records back" in html
    assert "Restore Records" in html
    assert "Prototype on invented data. Not a live government system." in html





