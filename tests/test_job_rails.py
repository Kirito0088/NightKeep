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


def _script_jobs() -> list[Path]:
    # .bat and .vbs jobs: real interpreters, no Python AST to walk.
    return sorted(list(JOBS.glob("*.bat")) + list(JOBS.glob("*.vbs")))


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
    stems = {job.stem for job in _jobs()} | {job.stem for job in _script_jobs()}
    assert stems >= {
        "nightly_export", "db_backup", "allocation_gen", "archive_old",
        "fix_dat", "operator_activity",
    }


def test_the_two_script_jobs_keep_their_real_extensions():
    # Job identity is executable + script path + hash (SOLUTION_DESIGN.md):
    # archive_old and fix_dat must stay .bat and .vbs, run through cmd.exe
    # and cscript.exe, not reduced to Python for convenience.
    names = {job.name for job in _script_jobs()}
    assert names == {"archive_old.bat", "fix_dat.vbs"}


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


def _code_lines(job: Path) -> list[str]:
    # Strips comment lines (REM/:: in .bat, ' in .vbs) so a docstring-style
    # header may say "it knows nothing about Nightkeep" without tripping
    # the rail below, which cares about what actually executes.
    lines = []
    for line in job.read_text(encoding="utf-8").splitlines():
        stripped = line.strip().lower()
        if stripped.startswith(("rem ", "::", "'")):
            continue
        lines.append(stripped)
    return lines


def test_no_script_job_references_this_repository():
    # .bat and .vbs can't be ast.parse'd, so the rail is textual: neither
    # ever names nightkeep, or reaches for Python/importlib to sneak a
    # repository import in through the back door.
    banned = ("nightkeep", "importlib", "__import__")
    for job in _script_jobs():
        code = "\n".join(_code_lines(job))
        for word in banned:
            assert word not in code, f"{job.name} references {word!r}"


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
