"""The suite never reads the operator's own `~/.openfactory/` or an ambient `OPENFACTORY_*` (#365).

Filed upstream as Open-Factory-Digital/openfactory-core#365. A real OpenFactory deployment lives
under `~/.openfactory/` — the generated `env`, `registry.yaml`, `board.db`, `metrics.db` — and it
exports its configuration into the shell (`OPENFACTORY_BOARD_DB`, `OPENFACTORY_OWN_WORK`,
`TEMPORAL_ADDRESS`, …). ADR-0049 puts that deployment on the very machine a contributor works on,
so the suite read BOTH: `board_db.db_path()` with no override falls to `namespace.operator_path`,
which is `Path.home()/.openfactory/board.db` — the operator's live database — and `own_work`,
`cloud_region`, the box kind and the engine address all read the shell the deployment loaded. A
suite whose meaning, and whose writes, depend on who runs it is the leak `tests/conftest.py` exists
to end (the credential floor and the registry floor are its earlier halves).

`tests/conftest.py` closes it in two strokes, and each has a guard here:

  · HOME is a directory of each test's own (`_a_home_of_its_own`), so every `~/.openfactory/…` a
    default resolves to lands there and never at the real deployment;
  · every ambient `OPENFACTORY_*` / `TEMPORAL_*` is deleted before collection
    (`_isolate_the_operator`, from `pytest_configure`), so the shell the deployment loaded reaches
    no test.

THE HONEST CHECK IS A PYTEST RUN, for the reason `test_the_suite_cannot_reach_a_live_engine.py`
and `test_the_suite_never_writes_the_registry_your_shell_names.py` give: a hook and an autouse
fixture are applied by pytest and by nothing else. So the verifier below plants a whole fake
deployment — a `~/.openfactory/` full of files and a loaded environment — runs a probe against it
WITH the conftest and WITHOUT it, and requires the two to differ: isolated with, leaking without.
The protected run must also leave the planted deployment byte-for-byte unchanged.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import conftest

ROOT = Path(__file__).resolve().parents[1]


# ── for every test: what THIS test sees is a home of its own and none of the operator's env ──────

def test_a_test_sees_a_home_of_its_own_not_the_operators():
    """`Path.home()` — and so every `~/.openfactory/…` a default resolves to — is under this run's
    temporary directory, not the operator's real home."""
    from openfactory import namespace
    from openfactory.adapters import board_db

    here = Path.home().resolve()
    assert here != conftest.operators_real_home(), (
        f"a test's HOME is the operator's own: {here}")
    for path in (namespace.operator_path("board.db"), board_db.db_path(),
                 namespace.operator_path("registry.yaml")):
        assert here in Path(path).resolve().parents, (
            f"a default resolves outside this test's home — it can reach the operator's "
            f"deployment: {path}")


def test_no_ambient_openfactory_or_temporal_reaches_a_test():
    """Not one of the `OPENFACTORY_*` / `TEMPORAL_*` values the shell that launched the suite
    carried survives into a test. The suite may SET its own under those prefixes (a registry, a log
    directory); what it may never do is read the operator's.

    Vacuous on a machine with nothing loaded, and that is deliberate: this direct check is the
    same run whether or not a deployment is present (ADR-0049), and the honest proof that the
    stripping works at all — on a clean machine too — is the planted verifier below, which supplies
    its own `OPENFACTORY_LEAKED`/`TEMPORAL_LEAKED` and requires the conftest to remove them."""
    leaked = {name: value for name, value in conftest.operators_ambient_environment().items()
              if os.environ.get(name) == value}
    assert not leaked, (
        f"the operator's own environment reached a test unchanged: {sorted(leaked)} — a suite that "
        f"reads these measures the deployment on the machine, not the code")


# ── the honest verifier: a whole planted deployment, isolated WITH the conftest and leaking WITHOUT ─

#: A probe that FAILS the moment it can see the deployment planted around it — its home, its files,
#: or its environment. Run WITH the conftest it must pass (all isolated); run with `--noconftest` it
#: must fail (everything leaks), which is what proves it measures the conftest and not the weather.
PROBE = textwrap.dedent("""
    import os
    from pathlib import Path

    PLANTED = Path(os.environ["PLANTED_HOME"]).resolve()


    def test_the_deployment_planted_around_this_run_is_not_visible():
        from openfactory import namespace
        from openfactory.adapters import board_db

        home = Path.home().resolve()
        assert home != PLANTED, f"HOME is the planted deployment's home: {home}"
        assert PLANTED not in home.parents and home != PLANTED

        # the board falls back through namespace.operator_path to ~/.openfactory/board.db; with the
        # ambient OPENFACTORY_BOARD_DB stripped and HOME re-homed it must not be the planted file
        for path in (board_db.db_path(), namespace.operator_path("board.db")):
            resolved = Path(path).resolve()
            assert PLANTED not in resolved.parents, f"a default reaches the deployment: {resolved}"

        # and none of the planted environment survives
        assert "OPENFACTORY_LEAKED" not in os.environ, os.environ.get("OPENFACTORY_LEAKED")
        assert "TEMPORAL_LEAKED" not in os.environ, os.environ.get("TEMPORAL_LEAKED")
        assert os.environ.get("OPENFACTORY_BOARD_DB") != str(PLANTED / ".openfactory" / "board.db")

        # exercise the write path the suite would take: it must land in the isolated home, not here
        with board_db.connect(write=True):
            pass


    def test_collected():
        pass
""")

#: What a person's deployment holds before the run. Every file the acceptance criteria name, with
#: bytes we can recognise, so the protected run proving "unchanged" is proving something.
PLANTED_FILES = {
    "registry.yaml": "projects: {}\n",
    "board.db": "SQLite format 3\x00-- not a real database, just recognisable bytes\n",
    "metrics.db": "SQLite format 3\x00-- metrics, untouched\n",
    "env": "OPENFACTORY_BOARD_DB=/home/someone/.openfactory/board.db\n",
}


def _plant_a_deployment(home: Path) -> Path:
    """A `~/.openfactory/` full of the files a real one has, under a home of `home`."""
    okf = home / ".openfactory"
    okf.mkdir(parents=True)
    for name, body in PLANTED_FILES.items():
        (okf / name).write_text(body, encoding="utf-8")
    return okf


def _snapshot(okf: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(okf.iterdir())}


def _child_env(home: Path) -> dict[str, str]:
    """The environment a loaded deployment leaves in the shell that launches the suite."""
    return {
        **os.environ,
        "HOME": str(home),
        "OPENFACTORY_BOARD_DB": str(home / ".openfactory" / "board.db"),
        "OPENFACTORY_LEAKED": "an-operators-value",
        "TEMPORAL_LEAKED": "an-operators-value",
        "PLANTED_HOME": str(home),
    }


def _run_the_probe(arena: Path, home: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    """The probe, OUTSIDE the tree with a faithful copy of the conftest beside it — for the reason
    `test_the_suite_never_writes_the_registry_your_shell_names.py` gives: a `.py` under `tests/`
    is a real source file every staleness checksum then reads, and `-c` gives the child this
    repository's rootdir and `pythonpath`."""
    arena.mkdir(parents=True)
    assert ROOT not in arena.resolve().parents, "the probe would be written inside the tree"
    (arena / "conftest.py").write_text(
        (ROOT / "tests" / "conftest.py").read_text(encoding="utf-8"), encoding="utf-8")
    probe = arena / "test__operator_home_probe__.py"
    probe.write_text(PROBE)
    return subprocess.run(
        [sys.executable, "-m", "pytest", str(probe), "-c", str(ROOT / "pyproject.toml"),
         *extra, "-q", "-p", "no:randomly", "-p", "no:cacheprovider", "--no-header"],
        cwd=ROOT, env=_child_env(home), capture_output=True, text=True, timeout=300)


def _passed(done: subprocess.CompletedProcess[str]) -> None:
    assert done.returncode == 0 and "2 passed" in done.stdout, (
        f"the protected probe did not run and pass, so this measures nothing:\n"
        f"{done.stdout[-2000:]}{done.stderr[-800:]}")


def test_the_conftest_isolates_a_planted_deployment(tmp_path):
    home = tmp_path / "operator"
    okf = _plant_a_deployment(home)
    before = _snapshot(okf)

    done = _run_the_probe(tmp_path / "with", home)

    _passed(done)
    assert _snapshot(okf) == before, (
        "the protected run changed the operator's deployment files — on a contributor's machine "
        "that is their live board, registry and metrics")


def test_without_the_conftest_the_same_probe_DOES_see_the_deployment(tmp_path):
    """`--noconftest` takes away exactly the isolation, and the probe must then FAIL — otherwise
    the run above is green because there was nothing to isolate, not because the conftest isolated
    it. If this stops failing, the probe is no longer touching the operator's world by default."""
    home = tmp_path / "operator"
    _plant_a_deployment(home)

    done = _run_the_probe(tmp_path / "without", home, "--noconftest")

    assert done.returncode != 0, (
        f"without the conftest the probe still saw an isolated world — it is not measuring the "
        f"conftest:\n{done.stdout[-2000:]}{done.stderr[-800:]}")
