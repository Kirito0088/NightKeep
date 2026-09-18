"""config.yaml is read in exactly one place.

CLAUDE.md: "config.yaml is read once, at startup, by one loader. Modules take
values as arguments. They never reach for config themselves." This is that
rule as a test, so the next six tickets cannot quietly break it.
"""

from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent / "nightkeep"
THE_ONE_LOADER = PACKAGE / "config.py"
ENTRYPOINT = PACKAGE / "__main__.py"


def _package_sources() -> list[Path]:
    return sorted(
        source
        for source in PACKAGE.rglob("*.py")
        if source not in (THE_ONE_LOADER, ENTRYPOINT)
    )


def test_the_package_has_sources_to_police():
    # Without this, the two tests below pass by finding nothing.
    assert len(_package_sources()) >= 7


def test_no_module_opens_config_yaml_itself():
    reaching = [
        source.relative_to(PACKAGE).as_posix()
        for source in _package_sources()
        if "config.yaml" in source.read_text(encoding="utf-8")
    ]

    assert reaching == [], (
        "these modules name config.yaml; they must take values as arguments "
        f"from the entrypoint instead: {reaching}"
    )


def test_no_module_parses_yaml_itself():
    parsing = [
        source.relative_to(PACKAGE).as_posix()
        for source in _package_sources()
        if "import yaml" in source.read_text(encoding="utf-8")
    ]

    assert parsing == [], (
        f"only nightkeep/config.py may parse YAML, but these do: {parsing}"
    )


def test_the_loader_is_the_only_one():
    loaders = [
        source.relative_to(PACKAGE).as_posix()
        for source in PACKAGE.rglob("*.py")
        if "def load_config" in source.read_text(encoding="utf-8")
    ]

    assert loaders == ["config.py"]
