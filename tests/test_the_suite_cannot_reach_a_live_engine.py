"""The suite cannot start a workflow on an engine somebody is actually running — #107.

`tests/conftest.py` already guarantees that *"a test can never hold a credential that acts on
something real"*, and states its own criterion in as many words: **authority, not
confidentiality**. That criterion has a hole it cannot see from the inside — a durable engine on
`localhost:7233` needs **no credential at all**. `connection.address()` defaults to it and
`_auth()` adds nothing, so stripping `TEMPORAL_API_KEY` protects the deployment that was never
reachable from a laptop and none of the ones that are.

MEASURED, NOT SUSPECTED. With the OSS `docker compose` stack up — the development loop this
repository ships and documents — a suite run left a real workflow behind:

    workflow_id : openfactory-demo-7
    identity    : 40513@Mac.lan          ← the host running pytest
    input       : {"project":"demo","issue":"7","sandbox":"worktree", …}
    state       : on_hold — KeyError: "project not registered: 'demo'"

It parked only because `demo` is a test name no registry carries. A project that HAPPENED to
exist under that name would have been worked on for real: an agent, a checkout, a client's board.
And the suite stayed green throughout — the damage is invisible from inside the run that caused
it, which is what makes this the signature defect rather than a flake.

Same family as `test_the_suite_cannot_act_with_production_credentials` (C-07b), where an
import-time `load_dotenv()` ran the whole suite on live write-capable credentials. There the leak
was a credential; here it is an engine.
"""

from __future__ import annotations

import ast
import pathlib
import subprocess
import sys
import textwrap

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


# ── the barrier itself ──────────────────────────────────────────────────────────────────────────

async def test_a_test_that_opens_a_connection_is_refused():
    """The property, exercised the only way that cannot lie: by trying it.

    Asserting that the fixture *exists*, or that it patches *something*, is satisfied by a fixture
    that patches the wrong name — which is precisely the version of this guard that would have
    shipped, since three production modules bind `connect` at import and a `connection.connect`
    patch leaves them untouched.
    """
    from temporalio.client import Client

    with pytest.raises(RuntimeError, match="REAL connection to a durable engine"):
        await Client.connect("localhost:7233")


async def test_the_refusal_says_what_to_do_instead():
    """A barrier that only says no teaches people to delete it. This one names the seam every
    durable test in the suite already patches, and says how a genuine integration test would opt
    in — deliberately, rather than by removing the fixture."""
    from temporalio.client import Client

    with pytest.raises(RuntimeError) as caught:
        await Client.connect("localhost:7233")

    said = str(caught.value)
    assert "openfactory.runtime.temporal.view.connect" in said, said
    assert "#107" in said, "the refusal does not say where the story is"


@pytest.mark.parametrize("route", [
    # every name a production caller resolves `connect` through — the point of blocking at the
    # library rather than at our wrapper
    "openfactory.runtime.temporal.connection",
    "openfactory.runtime.temporal.view",
])
async def test_every_route_to_the_engine_is_closed(route, monkeypatch):
    """`view.connect` imports `connection.connect` inside the function; activities do the same;
    `worker`, `schedule` and `starter` bind it at MODULE level. A barrier on any one name is a
    barrier the other routes walk around — so this drives the two that are callable without a
    worker and asserts the same refusal comes back.

    THE ADDRESS IS DECLARED HERE, DELIBERATELY (#163). `address()` now raises when nobody said
    where the engine is, and that refusal would arrive FIRST — so this guard would pass while
    proving nothing about the barrier it exists for. Declaring `localhost:7233` reproduces exactly
    the configuration that did the damage: a developer's machine with the compose stack up.
    """
    import importlib

    monkeypatch.setenv("TEMPORAL_ADDRESS", "localhost:7233")
    mod = importlib.import_module(route)
    with pytest.raises(RuntimeError, match="REAL connection to a durable engine"):
        await mod.connect()


async def test_and_an_UNDECLARED_engine_refuses_before_it_reaches_anything(monkeypatch):
    """The other half, and the one that protects a real deployment rather than this suite: a
    worker whose environment says nothing used to connect to whatever happened to be listening on
    the machine it was running on, and then do nothing visible (#163)."""
    from openfactory.runtime.temporal import connection

    for var in ("TEMPORAL_ADDRESS", "TEMPORAL_ENDPOINT"):
        monkeypatch.delenv(var, raising=False)

    with pytest.raises(connection.EngineNotDeclared, match="TEMPORAL_ADDRESS"):
        connection.address()


# ── the marker is not a back door ───────────────────────────────────────────────────────────────

def _marked_files() -> list[pathlib.Path]:
    """Every test module that declares `pytestmark = pytest.mark.owns_its_engine`."""
    out = []
    for path in sorted(ROOT.joinpath("tests").glob("test_*.py")):
        tree = ast.parse(path.read_text())
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            if any(getattr(t, "id", "") == "pytestmark" for t in node.targets) and \
                    "owns_its_engine" in ast.unparse(node.value):
                out.append(path)
    return out


def test_the_marker_scan_finds_the_one_file_that_uses_it():
    """The positive twin, first — the assertion below is satisfied by a scan that found nothing,
    and this repository has shipped three guards that were green for exactly that reason."""
    found = {p.name for p in _marked_files()}

    assert "test_temporal_workflow.py" in found, (
        f"the scan found {sorted(found)} — it cannot see the file it exists to check")


@pytest.mark.parametrize("path", _marked_files(), ids=lambda p: p.name)
def test_a_file_that_lifts_the_barrier_really_starts_its_OWN_engine(path):
    """The escape hatch is for a test that boots an ephemeral server and disposes of it. Anything
    else carrying this marker is a file that opted out of the guard without earning it — which is
    how a documented exception becomes a pass.

    `WorkflowEnvironment` is the only thing in this stack that starts one: it picks a free port,
    owns the server's whole life, and tears it down with the fixture.
    """
    src = path.read_text()

    assert "WorkflowEnvironment" in src, (
        f"{path.name} lifts the live-engine barrier and never starts an ephemeral server — it is "
        f"opting out of the guard rather than earning the exception")
    assert "localhost:7233" not in src and "TEMPORAL_ADDRESS" not in src, (
        f"{path.name} lifts the barrier AND names a configured engine — the exception is for a "
        f"server the test starts, never for the one a deployment runs")


# ── the barrier survives the thing it was written for ───────────────────────────────────────────

def test_a_subprocess_running_the_suite_cannot_reach_an_engine_either(tmp_path):
    """WHERE THE ORIGINAL DAMAGE HAPPENED, reproduced. The workflow that started this was created
    by `pytest` on the host while the compose stack was listening — so the honest check is a
    pytest run, not an import.

    Driven as a real collection-and-run of a throwaway test, because the fixture is `autouse` and
    only pytest applies it: calling `Client.connect` from a plain script would prove nothing about
    the suite.

    THE PROBE LIVES OUTSIDE THE TREE, and that is not tidiness. Written into `tests/`, it was a
    real `.py` inside this repository for the ~15 seconds the subprocess takes — and
    `knowledge/staleness.py::is_stale` checksums EVERY source file in the tree. A neighbour that
    generated a bundle and verified it inside that window compared two different trees and reported
    the map stale against itself: measured 2026-09-04, a red
    `test_a_map_generated_from_a_tree_is_never_stale_against_it` with nothing wrong in it. Serial
    runs never see it, because the probe cannot coexist with the scan when one test runs at a time
    — so `.github/workflows/ci.yml` is structurally blind to it and it survived every review.

    THE CONFTEST IS COPIED BESIDE THE PROBE rather than the probe moved under the conftest, because
    `autouse` reaches only what is under it and the barrier lives in `tests/conftest.py`. The copy
    is faithful: that file imports stdlib and `pytest` and nothing from this package, and its one
    use of `__file__` writes a failures log beside itself — which now lands in the arena instead of
    in `tests/`.

    THE INI IS PASSED, NOT INHERITED, and that is measured rather than assumed. The probe is
    `async def` and needs this repository's `asyncio_mode = "auto"`; pytest resolves its ini from
    the ARGUMENTS, and the argument now lives in a temp directory, so a `cwd` of the repository is
    not enough. Without `-c` the child reported *"async def functions are not natively supported"*
    and the probe was collected and never executed — a guard passing for the wrong reason, which is
    the failure this file exists to prevent. `-c` also makes the rootdir the repository again, so
    `pythonpath = ["."]` still applies.

    `-p no:cacheprovider` is the other half of the same lesson: the child used to create
    `.pytest_cache` AT THE REPOSITORY ROOT. That is invisible on any tree that already has one and
    is a new top-level entry on a fresh checkout — which is exactly how it produced a red
    `test_this_file_writes_NOTHING_into_the_tree_under_test` on a fresh worktree (2026-09-04).
    """
    probe = textwrap.dedent("""
        async def test_reaches_out():
            from temporalio.client import Client
            await Client.connect("localhost:7233")
    """)
    scratch = tmp_path / "test__live_engine_probe__.py"
    # BEFORE THE WRITE, and that ordering is the fix rather than a style. Asserted afterwards, a
    # version of this that aims the probe back into `tests/` fails — and leaves the file behind,
    # because the failure is an assertion and there is no cleanup after it. Measured 2026-09-04:
    # the mutation plan for this change did exactly that, and the next full suite COLLECTED the
    # orphan and went red on it. A guard that damages the tree while refusing to is not a guard.
    assert ROOT not in scratch.resolve().parents, (
        "the probe is inside the tree under test — a neighbour scanning the tree can now fail "
        "because of it")
    scratch.write_text(probe)
    (tmp_path / "conftest.py").write_text(
        (ROOT / "tests" / "conftest.py").read_text(encoding="utf-8"), encoding="utf-8")
    done = subprocess.run(
        [sys.executable, "-m", "pytest", str(scratch), "-c", str(ROOT / "pyproject.toml"),
         "-q", "-p", "no:randomly", "-p", "no:cacheprovider", "--no-header"],
        capture_output=True, text=True, cwd=str(ROOT), timeout=300)

    assert done.returncode != 0, (
        "a test that opens a connection to localhost:7233 PASSED — the barrier is not applied to "
        "a real pytest run, which is the only place it matters")
    assert "REAL connection to a durable engine" in done.stdout, done.stdout[-1500:]
