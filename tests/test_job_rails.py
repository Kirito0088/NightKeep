"""The two rails around the jobs and their ground truth, as tests.

CLAUDE.md: "The jobs contain zero imports from Nightkeep and do not know it
exists." And: "Nothing outside mock_pds/ and tests/ may read logs/_truth/."
Both are checked by reading source, not by trusting a comment.
"""

import ast
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent / "nightkeep"
JOBS = PACKAGE / "mock_pds" / "jobs"
TRUTH_BLIND = ("watcher", "habit", "judge", "vault")


def _jobs() -> list[Path]:
    return sorted(JOBS.glob("*.py"))


def _imports(tree: ast.AST) -> list[tuple[str, int]]:
    """(top-level module, relative level) for every import in the tree."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [(alias.name.split(".")[0], 0) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            found.append(((node.module or "").split(".")[0], node.level))
    return found


def test_there_are_jobs_to_police():
    # Without this, the rail below passes by finding nothing.
    assert {job.stem for job in _jobs()} >= {"nightly_export", "db_backup"}


def test_the_jobs_are_not_a_package_nightkeep_can_import():
    assert not (JOBS / "__init__.py").exists()


def test_no_job_import_resolves_to_anything_in_this_repository():
    # A file beside the jobs named like a standard module (jobs/csv.py) would
    # shadow it for any job run without -I, so none may exist.
    siblings = {path.stem for path in JOBS.iterdir()}
    assert not siblings & sys.stdlib_module_names, "a file in jobs/ shadows the standard library"
    for job in _jobs():
        tree = ast.parse(job.read_text(encoding="utf-8"))
        for module, level in _imports(tree):
            assert level == 0, f"{job.name} has a relative import"
            assert module in sys.stdlib_module_names, (
                f"{job.name} imports {module}, which is not the standard library"
            )


def test_no_job_imports_by_name_at_runtime():
    # These would slip past the syntax-tree walk above.
    for job in _jobs():
        tree = ast.parse(job.read_text(encoding="utf-8"))
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        modules = {module for module, _level in _imports(tree)}
        assert not names & {"__import__", "exec", "eval"}, job.name
        assert not modules & {"importlib", "runpy", "imp"}, job.name
        assert "path" not in attributes or "sys" not in modules, (
            f"{job.name} may be editing sys.path"
        )


def test_nothing_under_watcher_habit_judge_or_vault_reads_the_ground_truth():
    # Passes on empty packages today, on purpose: the rail is in place before
    # the Watcher is written, so the Watcher is written against it.
    reaching = [
        source.relative_to(PACKAGE).as_posix()
        for package in TRUTH_BLIND
        for source in (PACKAGE / package).rglob("*.py")
        if "_truth" in source.read_text(encoding="utf-8")
    ]

    assert reaching == [], f"these modules name logs/_truth/: {reaching}"
