"""The entrypoint is the glue: it reads config once and hands values on.

What matters here is the failure. A bad config.yaml must stop Nightkeep at
start-up with a message naming the key, not three minutes into a demo run.
"""

import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
REPO_CONFIG = REPO / "nightkeep" / "config.yaml"


def _run(*arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "nightkeep", *arguments],
        cwd=REPO,
        capture_output=True,
        text=True,
    )


def test_starting_nightkeep_with_the_repo_config_succeeds():
    finished = _run()

    assert finished.returncode == 0, finished.stderr
    assert "5,000 ration cards" in finished.stdout
    assert "6 jobs configured" in finished.stdout


def test_a_broken_config_stops_nightkeep_at_startup(tmp_path):
    raw = yaml.safe_load(REPO_CONFIG.read_text(encoding="utf-8"))
    raw["clock"].pop("simulated_day_seconds")
    broken = tmp_path / "config.yaml"
    broken.write_text(yaml.safe_dump(raw), encoding="utf-8")

    finished = _run(str(broken))

    assert finished.returncode != 0
    assert "clock.simulated_day_seconds" in finished.stderr
