"""UI regression tests for the Round 2 showcase polish pass.

Presentation-only contracts:
  * the showcase never exposes the demo's CLI command surface,
  * required titles, actions, navigation, and the exact project disclaimer
    survive the redesign,
  * final destination links and report-derived figures remain,
  * no em dash sneaks into console UI copy.
"""

import pytest

from nightkeep.console.app import create_app

DISCLAIMER = "Prototype on invented data. Not a live government system."

FORBIDDEN_SHOWCASE_TERMS = (
    "python -m nightkeep",
    "--demo-run",
    "--variant",
    "recovery-killer",
    "Demo output",
)


def run_fake_demo_to_completion(tmp_path):
    """Start a fake demo run and block until the controller finalises it."""
    import json
    import sys
    import time

    from nightkeep.console.showcase import ShowcaseController

    base = tmp_path / "showcase"
    base.mkdir()
    script = base / "fake_demo.py"
    script.write_text(
        "import json, sys\n"
        "from pathlib import Path\n"
        "d = Path(sys.argv[1]); (d / 'reports').mkdir(parents=True, exist_ok=True)\n"
        "(d / 'reports' / 'demo_run.json').write_text(json.dumps({\n"
        "  'passed': True,\n"
        "  'restore': {'records_verified': 5000, 'records_expected': 5000},\n"
        "  'attack': {'level': 'INCIDENT', 'detection_latency_seconds': 4.2,\n"
        "             'affected_files_at_incident': 37},\n"
        "}))\n"
        "print('--- proof PASSED ---', flush=True)\n",
        encoding="utf-8",
    )
    district = base / "district"
    controller = ShowcaseController(
        status_path=base / "showcase_status.json",
        log_path=base / "showcase_demo.log",
        demo_cmd=[sys.executable, str(script), str(district)],
        district_dir=district,
    )
    controller.start()
    deadline = time.time() + 30
    while time.time() < deadline:
        status = controller.read_status()
        if status.get("state") in ("complete", "failed"):
            return controller
        time.sleep(0.2)
    raise AssertionError("fake demo did not finish: %r" % controller.read_status())


@pytest.fixture
def client():
    app = create_app(
        showcase_controller=None,
        runtime_factory=None,
    )
    app.config["TESTING"] = True
    return app.test_client()


def test_showcase_hides_cli_command_surface(client):
    """The showcase must not leak the demo's command-line surface."""
    html = client.get("/showcase").get_data(as_text=True)
    for term in FORBIDDEN_SHOWCASE_TERMS:
        assert term not in html, f"showcase leaks forbidden term: {term!r}"


def test_showcase_keeps_title_and_primary_action(client):
    html = client.get("/showcase").get_data(as_text=True)
    assert "Full MVP Demo" in html
    assert "Run Full MVP Demo" in html


def test_showcase_keeps_plain_language_story(client):
    """The story stages stay in plain operational language."""
    html = client.get("/showcase").get_data(as_text=True)
    for stage in ("Learn", "Guard", "Attack", "Contain", "Protect", "Recover"):
        assert stage in html


def test_showcase_keeps_technical_output_section(client):
    html = client.get("/showcase").get_data(as_text=True)
    assert "Technical output" in html


def test_primary_nav_survives_on_all_primary_pages(client):
    for route in ("/", "/safety", "/showcase", "/alert"):
        html = client.get(route).get_data(as_text=True)
        assert 'href="/showcase"' in html, f"nav lost /showcase link on {route}"
        assert "Full MVP Demo" in html


def test_exact_disclaimer_survives_on_all_primary_pages(client):
    for route in ("/", "/safety", "/showcase", "/alert", "/restore", "/locked", "/it-view"):
        html = client.get(route).get_data(as_text=True)
        assert DISCLAIMER in html, f"disclaimer missing or altered on {route}"


def test_no_em_dash_in_console_templates():
    """No em dash may appear in console UI copy."""
    import re
    from pathlib import Path

    templates = Path("nightkeep/console/templates")
    assert templates.is_dir()
    for path in sorted(templates.glob("*.html")):
        text = path.read_text(encoding="utf-8")
        assert "\u2014" not in text, f"em dash found in {path.name}"
        assert "&mdash;" not in text, f"em dash entity found in {path.name}"


def test_showcase_still_offers_restore_after_complete(tmp_path):
    """After a completed run, the final destination links must resolve."""
    controller = run_fake_demo_to_completion(tmp_path)

    app = create_app(showcase_controller=controller, runtime_factory=None)
    app.config["TESTING"] = True
    client = app.test_client()
    html = client.get("/showcase").get_data(as_text=True)

    for link in ("/alert", "/restore", "/locked", "/it-view"):
        assert f'href="{link}"' in html, f"missing final destination link {link}"

    for route in ("/alert", "/restore", "/locked", "/it-view"):
        assert client.get(route).status_code == 200, f"{route} not 200 after run"


def test_showcase_figures_come_from_run_report(tmp_path):
    """The figure hero and measured figures must be report-derived."""
    controller = run_fake_demo_to_completion(tmp_path)

    app = create_app(showcase_controller=controller, runtime_factory=None)
    app.config["TESTING"] = True
    html = app.test_client().get("/showcase").get_data(as_text=True)

    assert "records recovered and verified" in html
    assert "detection latency" in html
    assert "4.2s" in html
    assert "37" in html
    assert "INCIDENT" in html
