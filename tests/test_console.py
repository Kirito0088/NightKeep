"""Console tests: all seven Nightkeep frontend screens, base chrome, and CSS contract."""

import re
from pathlib import Path
import pytest
from dataclasses import replace

from nightkeep.console.app import (
    DEFAULT_CARD_DETAILS,
    DEFAULT_SAMPLE_RECORDS,
    TransactionPresentation,
    ServerAlertPresentation,
    create_app,
)

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
        CONSOLE_DIR / "templates" / "server_alert.html",
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
    assert "1 record found" in suspended_html
    suspended_tbody = suspended_html.split("<tbody>")[1].split("</tbody>")[0]
    assert "Anil Eknath More" in suspended_tbody
    assert "Sunita Ramesh Kadam" not in suspended_tbody

    # Filter by scheme=AAY gives 1 row
    aay_resp = client.get("/search?scheme=AAY")
    aay_html = aay_resp.get_data(as_text=True)
    assert "1 record found" in aay_html
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


def test_locked_route_without_incident_is_a_drill(client):
    """Unwired /locked must not claim a live attack locked the records."""
    response = client.get("/locked")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "DEMONSTRATION DRILL" in html
    assert "No real incident is active." in html
    assert (
        "The system detected an abnormal program attempting to modify "
        "database files" not in html
    )


def test_locked_route_has_empty_results_table(client):
    response = client.get("/locked")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "0 records available" in html
    assert "Ration card records cannot be opened" in html
    assert "Database access is suspended to prevent file damage." in html


def test_locked_route_has_threat_note(client):
    response = client.get("/locked")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "Simulated Threat Note (Demonstration Artifact)" in html
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
    # Honest calm state: no runtime has run, so no safe copies exist yet.
    assert "No safe copies yet" in html
    assert "STATUS: NORMAL" in html


def test_safety_home_protected_record_count(client):
    response = client.get("/safety")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    # Honest calm state: no fabricated protection counts without a runtime.
    assert "5,000" not in html
    assert "No clean copy yet" in html


def test_safety_home_clean_point(client):
    response = client.get("/safety")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    # Honest calm state: no fabricated clean point or safe-copy count.
    assert "No clean copy yet" in html
    assert "Day 9, 01:20" not in html
    assert "24 safe copies" not in html


def test_safety_home_night_tasks_table(client):
    response = client.get("/safety")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "Night Tasks Activity" in html
    assert '<th scope="col">Task</th>' in html
    assert '<th scope="col">Usually</th>' in html
    assert '<th scope="col">Last night</th>' in html
    assert '<th scope="col">Status</th>' in html

    # Honest calm state: no runtime has run, so no task history exists.
    # No fabricated task names or rows.
    assert "Day-end upload" not in html
    assert "Data format maintenance" not in html

    # Count rows in tbody: zero, no fabricated activity.
    tbody_content = html.split("<tbody>")[1].split("</tbody>")[0]
    row_count = tbody_content.count("<tr")
    assert row_count == 0


def test_safety_home_later_than_usual_state(client):
    response = client.get("/safety")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    # Honest calm state: no fabricated "later than usual" task activity.
    assert "Later than usual" not in html
    assert "03:40 (6 files modified)" not in html


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
    assert "Incident Report" in html


def test_alert_exact_headline_present(client):
    response = client.get("/alert")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    # Unwired fallback: calm and honest, never a fabricated attack.
    assert "No incidents. Nightkeep is watching." in html
    assert "STATUS: ALL CLEAR" in html
    assert "STATUS: ATTACK STOPPED" not in html
    assert "Someone tried to lock your files. It was stopped." not in html


def test_alert_fallback_shows_no_fabricated_figures(client):
    response = client.get("/alert")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    # No fabricated incident metrics may appear without backend state.
    for label in (
        "files damaged",
        "Detected in 6 seconds",
        "Clean copy from 01:20 ready",
        "counter entries to re-check",
    ):
        assert label not in html
    assert 'class="alert-stat-card"' not in html


def test_alert_fallback_shows_no_fabricated_timeline(client):
    response = client.get("/alert")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "Incident Timeline" in html
    for title in (
        "Suspicious activity began",
        "Detected in 6 seconds",
        "37 files damaged",
        "Clean copy from 01:20 ready",
        "Office follow-up required",
    ):
        assert title not in html

    timeline_content = html.split('<ol class="timeline-list">')[1].split("</ol>")[0]
    assert timeline_content.count('class="timeline-item"') == 0


def test_alert_fallback_calm_action_step_present(client):
    response = client.get("/alert")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "What to do now" in html
    assert "Nothing to do." in html
    assert "No tripwire has fired." in html
    # The fabricated incident action steps must be gone.
    assert "Restarting can wipe the evidence" not in html
    assert "Restore records using the clean copy." not in html


def test_alert_fallback_has_no_restore_cta(client):
    response = client.get("/alert")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "Get my records back" not in html
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


def test_restore_route_returns_200(client):
    response = client.get("/restore")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Get my records back" in html
    assert "Restore Records" in html


def test_restore_clean_point_info_present(client):
    response = client.get("/restore")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    # Unwired fallback: no fabricated clean point.
    assert "No clean copy yet" in html
    assert "Day 9, 01:20" not in html
    assert "District Supply Office, Thane" in html


def test_restore_three_steps_rendered(client):
    response = client.get("/restore")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "Restore Progress" in html
    assert "Step 1: Select clean copy" in html
    assert "Step 2: Verify records" in html
    assert "Step 3: Confirm and restore" in html
    assert "Current Step" in html

    steps_content = html.split('<ol class="restore-steps-list">')[1].split("</ol>")[0]
    assert steps_content.count("restore-step-item") == 3


def test_restore_five_verification_checks_rendered(client):
    response = client.get("/restore")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "Safety Verification (Five Checks)" in html
    assert "0 of 5 verified" in html
    assert "5 of 5 verified" not in html
    assert html.count(">Pending<") == 5
    # The apostrophe renders HTML-escaped; assert the unescaped remainder.
    assert "Every restored file" in html
    assert "hash matches the safe copy from the Vault." in html
    assert "Every restored file still opens as its own type." in html
    assert "Every restored export parses as a CSV." in html
    assert "The database backup passes its integrity check." in html
    assert "All ration cards are present and readable." in html

    checks_content = html.split('<ul class="verification-checks-list">')[1].split("</ul>")[0]
    assert checks_content.count("verification-check-item") == 5


def test_restore_loss_window_advisory_present(client):
    response = client.get("/restore")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "Loss Window Advisory" in html
    assert "The loss window cannot be measured without a clean copy." in html
    assert "19 counter entries recorded between 01:20 and the incident at 03:41" not in html


def test_restore_pin_field_accessible(client):
    response = client.get("/restore")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert '<label for="restore_pin"' in html
    assert 'id="restore_pin"' in html
    assert 'type="password"' in html
    assert "Supervisor authorisation PIN" in html


def test_restore_primary_action_present(client):
    response = client.get("/restore")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "Restore records to office computer" in html
    assert "btn-restore-confirm" in html
    assert '<a href="#"' not in html, "Found dead anchor href='#' in restore template"
    # No incident behind the unwired console: the way back is Data Safety,
    # not an incident report that has nothing to report.
    assert 'href="/safety"' in html
    assert "No attack has been detected" in html


def test_restore_retains_government_chrome(client):
    response = client.get("/restore")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "जिल्हा पुरवठा कार्यालय, ठाणे" in html
    assert "District Supply Office, Thane" in html
    assert "Prototype on invented data. Not a live government system." in html
    assert '<a href="#main-content" class="skip-link">Skip to main content</a>' in html
    assert 'id="main-content"' in html


def test_restore_no_technical_detection_terms_in_clerk_sections(client):
    response = client.get("/restore")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

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
        "PRAGMA",
    ]
    for term in technical_terms:
        assert term not in html, f"Technical term '{term}' leaked to clerk-facing restore content"


# ---------------------------------------------------------------------------
# Screen 7: Server Alert Pop-up (ServerAlert.dc.html)
# ---------------------------------------------------------------------------

def test_server_alert_route_returns_200(client):
    response = client.get("/server-alert")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Nightkeep Security Alert" in html


def test_server_alert_exact_copy_and_instructions(client):
    response = client.get("/server-alert")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    # Exact title and headline from mockup-log.md / CLAUDE.md
    assert '<h1 id="server-alert-title" class="server-alert-header-title">Nightkeep Security Alert</h1>' in html
    # Honest fallback: no backend state, so no claim a program was paused.
    assert "Unusual activity was detected on the office computer." in html
    assert "It was paused." not in html

    # Exact three instructions in order
    assert "Do not restart the office computer." in html
    assert "Disconnect the network cable." in html
    assert "Go to the Data Safety console on the Vault machine." in html

    # First instruction must have the highlighted red treatment
    assert "server-alert-action-highlight" in html


def test_server_alert_popup_dialog_accessibility(client):
    response = client.get("/server-alert")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert 'role="alertdialog"' in html
    assert 'aria-modal="true"' in html
    assert 'aria-labelledby="server-alert-title"' in html
    assert 'aria-describedby="server-alert-headline"' in html


def test_server_alert_geometry_and_styling():
    style_path = CONSOLE_DIR / "static" / "style.css"
    content = style_path.read_text(encoding="utf-8")

    assert "width: 600px;" in content
    assert "height: 380px;" in content
    assert "box-shadow: 0 10px 30px rgba(0, 0, 0, 0.35);" in content
    assert ".server-alert-window" in content


def test_server_alert_controls_and_simulation_link(client):
    response = client.get("/server-alert")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    # Presentation-only acknowledge button
    assert '<button type="button" class="btn btn-primary btn-alert-ack">Acknowledge</button>' in html

    # Simulation secondary link to the attack report, not the calm home screen
    assert 'href="/alert"' in html
    assert 'href="/safety"' not in html
    assert "Open Vault Console (Simulation)" in html
    assert "btn-secondary" in html

    # Mandatory disclaimer
    assert "Prototype on invented data. Not a live government system." in html


def test_server_alert_no_dead_anchors(client):
    response = client.get("/server-alert")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert '<a href="#"' not in html, "Found dead anchor href='#' in server_alert template"


def test_server_alert_distinct_chrome_no_government_nav(client):
    response = client.get("/server-alert")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    # Server alert is the isolated popup on the office computer, not full portal chrome
    assert "site-nav" not in html
    assert "utility-strip" not in html
    assert "breadcrumb-nav" not in html


def test_server_alert_no_technical_detection_terms(client):
    response = client.get("/server-alert")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

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
        "PRAGMA",
        "heuristic",
        "Thane",
    ]
    for term in technical_terms:
        assert term not in html, f"Technical or invented term '{term}' leaked to server alert popup"


def test_custom_server_alert_data_injection():
    custom_alert = ServerAlertPresentation(
        title="Custom Alert Title",
        headline="Custom alert headline.",
        actions=(
            "Custom step one.",
            "Custom step two.",
        ),
    )
    app = create_app(server_alert_data=custom_alert)
    app.config["TESTING"] = True
    with app.test_client() as c:
        resp = c.get("/server-alert")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "Custom Alert Title" in html
        assert "Custom alert headline." in html
        assert "Custom step one." in html
        assert "Custom step two." in html

# ---------------------------------------------------------------------------
# Polish regression tests (breadcrumb structure, title, copy, CSS)
# ---------------------------------------------------------------------------

PAGES_WITH_CHROME = [
    "/",
    "/search",
    "/locked",
    "/card/110300512847",
    "/safety",
    "/alert",
    "/restore",
    "/card/999999999999",  # 404 page
]

NIGHTKEEP_PAGES = ["/safety", "/alert", "/restore"]


def test_title_tags_have_no_doubled_suffix(client):
    """Rendered <title> must not repeat the office suffix."""
    doubled = "District Supply Office, Thane - District Supply Office, Thane"
    for path in PAGES_WITH_CHROME:
        resp = client.get(path)
        html = resp.get_data(as_text=True)
        assert doubled not in html, (
            f"Doubled office suffix found in <title> on {path}"
        )


def test_breadcrumb_items_are_list_elements(client):
    """Every breadcrumb entry must be inside its own <li>, not a bare span/a."""
    for path in PAGES_WITH_CHROME:
        resp = client.get(path)
        html = resp.get_data(as_text=True)
        # Extract breadcrumb-list content
        assert 'class="breadcrumb-list"' in html, f"No breadcrumb-list on {path}"
        bc_start = html.index('class="breadcrumb-list"')
        bc_section = html[bc_start: bc_start + 800]
        # Must have at least one <li> item
        assert "<li>" in bc_section or '<li ' in bc_section, (
            f"Breadcrumb has no <li> elements on {path}"
        )
        # Must not have a bare <a> or <span> directly inside the <ol>
        # (i.e. the old broken pattern of crammed items)
        # We check that no breadcrumb separator is a <span> (they're now <li>)
        assert '<span class="breadcrumb-separator"' not in bc_section, (
            f"Breadcrumb still has bare <span> separators on {path} "
            "(items are not wrapped in <li>)"
        )


def test_breadcrumb_exactly_one_aria_current_page(client):
    """Each page's breadcrumb nav must have exactly one aria-current='page' attribute."""
    for path in PAGES_WITH_CHROME:
        resp = client.get(path)
        html = resp.get_data(as_text=True)
        # Scope to the breadcrumb nav only — the site nav also uses aria-current
        # on the active tab, which is correct ARIA practice.
        bc_start = html.find('aria-label="Breadcrumb"')
        bc_end = html.find('</nav>', bc_start) + 6
        bc_section = html[bc_start:bc_end]
        count = bc_section.count('aria-current="page"')
        assert count == 1, (
            f"Expected 1 aria-current='page' in breadcrumb on {path}, found {count}"
        )


def test_breadcrumb_home_not_duplicated(client):
    """The text 'Home' must not appear more than once in the breadcrumb."""
    for path in PAGES_WITH_CHROME:
        resp = client.get(path)
        html = resp.get_data(as_text=True)
        # Extract the breadcrumb nav element
        bc_start = html.find('aria-label="Breadcrumb"')
        bc_end = html.find('</nav>', bc_start) + 6
        bc_section = html[bc_start:bc_end]
        home_count = bc_section.count(">Home<")
        assert home_count <= 1, (
            f"'Home' appears {home_count} times in breadcrumb on {path}"
        )


def test_nightkeep_screens_home_breadcrumb_links_to_root(client):
    """On /safety, /alert, /restore the Home breadcrumb must link to /."""
    for path in NIGHTKEEP_PAGES:
        resp = client.get(path)
        html = resp.get_data(as_text=True)
        bc_start = html.find('aria-label="Breadcrumb"')
        bc_end = html.find('</nav>', bc_start) + 6
        bc_section = html[bc_start:bc_end]
        # Home link must be href="/"
        assert '<a href="/">Home</a>' in bc_section, (
            f"Home breadcrumb on {path} does not link to /"
        )
        # Must not use /search as the Home href
        assert '<a href="/search">Home</a>' not in bc_section, (
            f"Home breadcrumb on {path} uses /search instead of /"
        )


def test_restore_done_label_no_brackets(client):
    """Completed step indicators must show 'Done', not '[DONE]'."""
    resp = client.get("/restore")
    html = resp.get_data(as_text=True)
    assert "[DONE]" not in html, "Placeholder text '[DONE]' found in /restore"
    # The honest fallback has no completed steps: nothing claims to be done.
    assert "Done" not in html


def test_card_detail_status_badge_not_duplicated(client):
    """The redundant 'Card Status' kv-row must be absent from card detail pages.

    The status is shown canonically in the panel header badge. The old kv-row
    was a duplicate and has been removed. e-KYC and transaction badges are
    intentional and unrelated.
    """
    for card_no in ["110300512847", "110294819203"]:  # one active, one suspended
        resp = client.get(f"/card/{card_no}")
        html = resp.get_data(as_text=True)
        # The removed kv-row had this exact label text
        assert 'class="kv-label">Card Status</dt>' not in html, (
            f"Duplicate 'Card Status' kv-row still present in card detail for {card_no}"
        )
        # The canonical header badge must still be present
        assert 'detail-panel-header' in html
        assert 'status-badge' in html


def test_form_help_text_rule_in_css():
    """style.css must define the .form-help-text rule."""
    style_path = CONSOLE_DIR / "static" / "style.css"
    content = style_path.read_text(encoding="utf-8")
    assert ".form-help-text" in content, ".form-help-text rule missing from style.css"
    assert "font-size: var(--font-size-caption);" in content


def test_module_docstring_updated():
    """The test module docstring must not be the stale Screen 1 description."""
    import nightkeep  # noqa: F401 — just check the test file docstring via source
    test_file = Path(__file__)
    source = test_file.read_text(encoding="utf-8")
    first_line = source.split('\n')[0]
    assert "Feature 1" not in first_line, (
        "Module docstring still references Feature 1 only"
    )
    assert "Console tests" in source[:120], (
        "Module docstring does not describe the full console suite"
    )


def test_card_detail_part_collected_is_not_marked_green():
    card = DEFAULT_CARD_DETAILS["110300512847"]
    tx = TransactionPresentation(
        "2026-09-08 11:24", "2026-09", "Rice (12.000 kg)", 12.000,
        "Biometric", "Part collected", "27030300145",
    )
    app = create_app(card_details={card.card_no: replace(card, transactions=(tx,))})
    html = app.test_client().get(f"/card/{card.card_no}").get_data(as_text=True)
    assert '<span class="status-badge status-badge-suspended">Part collected</span>' in html


def test_alert_calm_banner_uses_calm_not_incident_styling(client):
    response = client.get("/alert")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    # Calm state must carry the green calm variant, not incident-red styling.
    assert 'class="alert-incident-banner alert-incident-calm"' in html
    assert "STATUS: ALL CLEAR" in html
    # Honest empty state for the timeline when there is no incident.
    assert "No incident timeline yet." in html
