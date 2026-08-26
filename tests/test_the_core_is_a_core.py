"""The core runs with every VENDOR package refused — not just the cloud ones (#106).

`test_the_core_does_not_need_a_cloud` already proves this for AWS, and states the distinction the
whole card rests on: *"a provider being AVAILABLE is the product working. A provider being
UNAVOIDABLE is the product broken."*

That file guards ONE vendor. The card's claim is larger and the document it comes from is blunt
about the state: `docs/core/07-extensibility.md` — *"an axis is agnostic when it is born with two;
a platform is extensible when a stranger can add the third without editing our files."* An axis
whose only working implementation needs a package the core does not depend on is an axis in name.

So this asks the harder question, in a subprocess where **every** vendor SDK refuses to import:
does the core still load, does the ACTION CATALOGUE still resolve, and does the panel still come
up? Those three because they are what a stranger touches first — install, ask what it can do, open
the page.

WHAT THIS DOES NOT CLAIM. Not that the platform can DO everything without them: with `slack_sdk`
absent the Slack channel cannot be built, and it should not be. What it claims is that nothing on
the way to a working install requires one — which is the difference between an extra and a
dependency.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys
import textwrap

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: Every third-party package that ties an install to one vendor's product. DERIVED in spirit from
#: the extras in `pyproject.toml` — `runtime`, `sandbox`, `slack` — and stated here so the guard
#: has one list to grow: a vendor added to an extra must be added here, and the test below fails
#: if the extras name one this list does not.
VENDOR_SDKS = ("boto3", "botocore", "slack_sdk", "temporalio",
               "google-cloud", "azure-identity", "azure-storage")


def _probe(body: str) -> subprocess.CompletedProcess:
    """A subprocess where every vendor SDK refuses to import, running `body`.

    Blocked on `__import__` rather than by emptying `sys.modules`, because a LAZY import inside a
    function is exactly the shape this file exists to catch: it happens long after module load,
    and only a live hook is present when it fires.
    """
    probe = textwrap.dedent(f"""
        import builtins, sys
        real = builtins.__import__
        # NORMALISED ON BOTH SIDES. `__import__` receives the IMPORT name (`slack_sdk`) and this
        # list carries distribution-shaped names (`azure-identity`); comparing one to the other
        # let `slack_sdk` straight through — caught by the positive twin below, which is the whole
        # reason it runs first.
        BLOCKED = {{v.replace("-", "_") for v in {VENDOR_SDKS!r}}}
        reached = []

        def guarded(name, *a, **k):
            if name.split(".")[0].replace("-", "_") in BLOCKED:
                reached.append(name)
                raise ImportError(f"{{name}} is not installed on this deployment")
            return real(name, *a, **k)

        builtins.__import__ = guarded
        {body}
    """)
    return subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True,
                          cwd=str(ROOT), timeout=300)


def test_the_probe_can_SEE_a_vendor_import():
    """THE POSITIVE TWIN, FIRST. Every assertion below is of the form "it started", which a probe
    that blocked nothing satisfies perfectly — and this repository has shipped guards that were
    green over live defects for exactly that reason."""
    done = _probe("""
        def a_lazy_one():
            import slack_sdk    # noqa: F401
        try:
            a_lazy_one()
        except ImportError:
            print("BLOCKED:", reached); raise SystemExit(3)
        print("NOT BLOCKED — the probe is decoration")
    """)

    assert done.returncode == 3, (
        f"the probe let a vendor import through:\n{done.stdout[-600:]}{done.stderr[-600:]}")
    assert "slack_sdk" in done.stdout, done.stdout


def test_the_vendor_list_covers_every_extra():
    """The list above has to be the list `pyproject` actually declares, or the guard is about a
    world that no longer exists. Derived rather than trusted: a vendor added to an extra and not
    to `VENDOR_SDKS` would be silently unguarded — which is the exact shape of the gap this file
    was written to close for `slack_sdk`."""
    import tomllib

    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    declared = {
        name.split(">")[0].split("=")[0].split("[")[0].strip().replace("_", "-")
        for group, deps in data["project"]["optional-dependencies"].items()
        if group != "dev"
        for name in deps
    }
    known = {v.replace("_", "-") for v in VENDOR_SDKS}
    missing = sorted(declared - known)

    assert not missing, (
        f"these are optional-dependency vendors and this guard does not block them: {missing}. "
        f"Add them to VENDOR_SDKS — a vendor nobody blocks is a vendor the core may quietly start "
        f"requiring")


# ── the three things a stranger touches first ───────────────────────────────────────────────────

def test_the_core_IMPORTS_with_every_vendor_refused():
    """Install and `import openfactory`. If this fails, nothing else about the product matters to
    somebody evaluating it."""
    done = _probe("""
        import openfactory.approvals, openfactory.cli, openfactory.factory, openfactory.loader, openfactory.orchestrator, openfactory.registry
        import openfactory.namespace, openfactory.plugins            # noqa: F401
        from openfactory.adapters.board import build_board    # noqa: F401
        from openfactory.adapters.forge.registry import build_forge      # noqa: F401
        from openfactory.adapters.tracker.registry import build_tracker  # noqa: F401
        assert not reached, f"the core reached for {reached}"
        print("OK")
    """)

    assert done.returncode == 0 and "OK" in done.stdout, (
        f"the core cannot be imported without a vendor SDK — an install now needs somebody's "
        f"account:\n{done.stderr[-2000:]}")


def test_the_ACTION_CATALOGUE_resolves_with_every_vendor_refused():
    """"What can this thing do?" is the second question, and the catalogue is the answer. A row
    that could not even be LISTED without a vendor package would make the product's own
    self-description depend on somebody's account."""
    done = _probe("""
        from openfactory import actions
        names = sorted(actions.names())
        assert len(names) > 30, names
        for name in names:
            spec = actions.CATALOG[name]
            assert spec.summary and spec.run is not None, name
        assert not reached, f"resolving the catalogue reached for {reached}"
        print("OK", len(names))
    """)

    assert done.returncode == 0 and "OK" in done.stdout, (
        f"the action catalogue cannot be resolved without a vendor SDK:\n{done.stderr[-2000:]}")


def test_the_PANEL_comes_up_with_every_vendor_refused():
    """The third thing a stranger touches. The panel is the reference surface (ADR-0038), so a
    panel that needs a vendor to START is a product whose front door is behind somebody's
    account.

    Built rather than requested: constructing the app resolves every route and its dependencies,
    which is where an import-time vendor reach would fire."""
    done = _probe("""
        from fastapi.testclient import TestClient
        from openfactory.api.app import app
        with TestClient(app) as client:
            r = client.get("/api/whoami")
        assert r.status_code in (200, 401, 403), r.status_code
        assert not reached, f"starting the panel reached for {reached}"
        print("OK", r.status_code)
    """)

    assert done.returncode == 0 and "OK" in done.stdout, (
        f"the panel cannot start without a vendor SDK — the reference surface is behind an "
        f"account:\n{done.stderr[-2500:]}")


@pytest.mark.parametrize("axis,builder,kind", [
    ("forge", "openfactory.adapters.forge.registry:build_forge", "github"),
    ("tracker", "openfactory.adapters.tracker.registry:build_tracker", "github"),
])
def test_an_axis_still_DISPATCHES_with_every_vendor_refused(axis, builder, kind):
    """The axes are the claim. Resolving a kind must not need a vendor package — building the
    adapter may, and that is the correct place for the dependency to bite: at use, named, on the
    deployment that chose it."""
    module, _, func = builder.partition(":")
    done = _probe(f"""
        import importlib
        mod = importlib.import_module({module!r})
        table = [v for k, v in vars(mod).items() if k.isupper() and isinstance(v, dict)]
        assert any({kind!r} in t for t in table), "the axis lost its built-in row"
        assert not reached, f"resolving the {axis} axis reached for {{reached}}"
        print("OK")
    """)

    assert done.returncode == 0 and "OK" in done.stdout, (
        f"the {axis} axis cannot be resolved without a vendor SDK:\n{done.stderr[-1500:]}")
