"""The suite never reads or writes the registry the shell running it names (#260).

`ProjectRegistry()` with no path reads `OPENFACTORY_REGISTRY` and, when that is unset, the
operator's own `~/.openfactory/registry.yaml`. MEASURED 2026-09-24, before `tests/conftest.py`
named a registry of its own: with the variable pointing at a file, the test files that touch the
registry or the CLI ran green — 2789 passed — and left a project `p` in that file, written by
`test_the_synchronous_release_asks_the_same_question`. A contributor who follows CONTRIBUTING and
has a deployment on the same machine would have had the suite write into it, with nothing red.

The conftest now names a registry of its own twice, and each half has a guard here that goes red
without it:

  · for every test (`_a_registry_of_its_own`) — the in-process check below, and the writer that
    did the damage, driven again as a real pytest run with the variable set the way a shell sets
    it: the file it names must come back byte for byte;
  · before collection (`pytest_configure`) — a probe that registers a project while its module is
    being IMPORTED, which is before any fixture exists.

THE HONEST CHECK IS A PYTEST RUN, for the reason `test_the_suite_cannot_reach_a_live_engine.py`
gives: a hook and an autouse fixture are applied by pytest and by nothing else. And each run is
repeated WITHOUT the conftest, where it must write into the shell's file — otherwise a green run
here would only mean the writer stopped writing.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: The test that wrote into the shell's registry on 2026-09-24. Driven by its node id, so a rename
#: fails this guard by name ("no tests ran") instead of letting it pass over nothing.
WRITER = ("tests/test_a_store_that_cannot_be_read_authorizes_nobody_and_says_so.py"
          "::test_the_synchronous_release_asks_the_same_question")

#: A module that writes the default registry at IMPORT time — while pytest is still collecting.
PROBE = textwrap.dedent("""
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.registry import ProjectRegistry

    ProjectRegistry().add(Project(name="at-import", repo_path="/nowhere",
                                  tracker=ProviderRef(kind="local", repo="at-import")))


    def test_collected():
        pass
""")

#: What a person's registry holds before the run; the protected run must leave exactly this.
BEFORE = "projects: {}\n"


def _pytest(*args: str, registry: Path) -> subprocess.CompletedProcess[str]:
    """A child pytest from the repository root, with the shell's variable pointing at `registry`.

    `-p no:cacheprovider` because a child run would otherwise create `.pytest_cache` at the root
    of a fresh checkout — the new top-level entry `test_this_file_writes_NOTHING_into_the_tree_
    under_test` exists to catch."""
    return subprocess.run(
        [sys.executable, "-m", "pytest", *args, "-q", "-p", "no:randomly",
         "-p", "no:cacheprovider", "--no-header"],
        cwd=ROOT, env={**os.environ, "OPENFACTORY_REGISTRY": str(registry)},
        capture_output=True, text=True, timeout=300)


def _run_the_writer(registry: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return _pytest(WRITER, *extra, registry=registry)


def _run_the_probe(arena: Path, registry: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    """The probe, OUTSIDE the tree, with a faithful copy of the conftest beside it.

    Outside, because a `.py` written into `tests/` is a real source file for as long as the child
    runs, and `knowledge/staleness.py` checksums every one of them (the live-engine guard paid for
    that on 2026-09-04). The conftest is copied because it reaches only what is under it, and `-c`
    passes the ini so the rootdir — and `pythonpath = ["."]` — are this repository's."""
    arena.mkdir()
    assert ROOT not in arena.resolve().parents, "the probe would be written inside the tree"
    (arena / "conftest.py").write_text(
        (ROOT / "tests" / "conftest.py").read_text(encoding="utf-8"), encoding="utf-8")
    probe = arena / "test__registry_at_import_probe__.py"
    probe.write_text(PROBE)
    return _pytest(str(probe), "-c", str(ROOT / "pyproject.toml"), *extra, registry=registry)


def _a_persons_registry(tmp_path: Path) -> Path:
    home = tmp_path / "shell"
    home.mkdir(parents=True)
    registry = home / "registry.yaml"
    registry.write_text(BEFORE)
    return registry


def _passed_once(done: subprocess.CompletedProcess[str]) -> None:
    assert done.returncode == 0 and "1 passed" in done.stdout, (
        f"the child run did not run and pass, so this measures nothing:\n"
        f"{done.stdout[-1500:]}{done.stderr[-800:]}")


def _untouched(registry: Path) -> None:
    assert registry.read_text() == BEFORE, (
        f"the suite wrote into the registry OPENFACTORY_REGISTRY names — on a contributor's "
        f"machine that is their own deployment's registry:\n{registry.read_text()}")
    assert sorted(p.name for p in registry.parent.iterdir()) == ["registry.yaml"], (
        f"the suite touched the directory of the shell's registry: "
        f"{sorted(p.name for p in registry.parent.iterdir())}")


def _skip_where_the_writer_cannot_run() -> None:
    # The writer's own `store` fixture skips as root (root reads a mode-000 file), and a writer
    # that skipped writes nothing — which would read as protection here.
    if os.geteuid() == 0:
        pytest.skip("root: the writer this guard drives skips itself, so it would prove nothing")


# ── for every test ──────────────────────────────────────────────────────────────────────────────

def test_the_writer_leaves_the_registry_the_shell_names_untouched(tmp_path):
    _skip_where_the_writer_cannot_run()
    registry = _a_persons_registry(tmp_path)

    done = _run_the_writer(registry)

    _passed_once(done)
    _untouched(registry)


def test_inside_a_test_the_default_registry_is_the_suites_own(tmp_path_factory):
    """What `ProjectRegistry()` resolves while a test runs is a file of this test's own under
    pytest's temporary directory — neither the shell's path nor the operator's home file — and
    nothing is in it yet."""
    from openfactory.registry import ProjectRegistry

    path = ProjectRegistry().path.resolve()

    assert path != (Path.home() / ".openfactory" / "registry.yaml").resolve(), path
    assert tmp_path_factory.getbasetemp().resolve() in path.parents, (
        f"the default registry is outside this run's temporary directory: {path}")
    assert not path.exists(), f"a test starts with a registry someone already filled: {path}"


# ── before collection ───────────────────────────────────────────────────────────────────────────

def test_a_module_that_writes_the_registry_at_IMPORT_leaves_the_shells_untouched(tmp_path):
    registry = _a_persons_registry(tmp_path)

    done = _run_the_probe(tmp_path / "arena", registry)

    _passed_once(done)
    _untouched(registry)


# ── verify the verifier: without the conftest, both runs DO write into the shell's registry ─────

def test_without_the_conftest_the_same_runs_DO_write_into_it(tmp_path):
    """`--noconftest` takes away exactly the protection. The writer and the probe must then land
    in the file — otherwise the guards above are green because nothing wrote, not because the
    suite stopped it. If the writer stops writing, point WRITER at a test that registers a
    project through `ProjectRegistry()` with no path."""
    _skip_where_the_writer_cannot_run()
    by_the_writer = _a_persons_registry(tmp_path / "writer")
    by_the_probe = _a_persons_registry(tmp_path / "probe")

    wrote = _run_the_writer(by_the_writer, "--noconftest")
    probed = _run_the_probe(tmp_path / "arena", by_the_probe, "--noconftest")

    _passed_once(wrote)
    _passed_once(probed)
    assert "  p:" in by_the_writer.read_text(), (
        f"without the conftest the writer no longer writes the shell's registry:\n"
        f"{by_the_writer.read_text()}")
    assert "  at-import:" in by_the_probe.read_text(), (
        f"without the conftest the probe no longer writes the shell's registry:\n"
        f"{by_the_probe.read_text()}")
