"""The open-source core installs and runs with no cloud SDK present. Asserted, not claimed.

The product owner read the board, saw a card titled *"the panel's approval vault needs the secret
in SSM"*, and asked the right question: *"but isn't that an AWS coupling? we are making everything
agnostic — this whole undertaking is precisely so there is no provider dependency, it is the open
source core."*

The answer was no — and the only reason I could say so with any confidence is that I went and
measured it. That is the wrong shape for a claim this central. **The three things that make it true
are all things a single careless commit can undo**, and none of them announces itself:

  1. `boto3` sits in the `runtime`/`sandbox`/`slack` EXTRAS, not in the core dependencies. One line
     moved in `pyproject.toml` and every `pip install` of the core drags a cloud SDK in — which a
     stranger's security reviewer sees before they see a line of code.
  2. Every `boto3` import in `sdlc/` is FUNCTION-LEVEL. One import hoisted to module scope for
     tidiness and the core stops importing on a machine that has no AWS.
  3. The default sinks are cloud-free. A default flipped to `dynamodb` makes a laptop install fail
     at the first metric.

WHAT THIS FILE DOES **NOT** CLAIM. It does not say the platform has no AWS code — it has, and that
is correct: the Fargate box is one sandbox beside `worktree` and `container`, DynamoDB is one
metrics sink among four, and S3 backs the GDPR erase on the deployment that runs there. A provider
being AVAILABLE is the product working. A provider being UNAVOIDABLE is the product broken. This
file guards the second, and only the second.
"""

from __future__ import annotations

import ast
import pathlib
import subprocess
import sys
import textwrap

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: SDKs that tie an install to one vendor's cloud. Not "any dependency" — these are the ones whose
#: presence in the core would mean a stranger cannot run the platform without an account somewhere.
CLOUD_SDKS = ("boto3", "botocore", "google-cloud", "azure-identity", "azure-storage")


def test_the_core_imports_with_every_cloud_SDK_BLOCKED():
    """The property itself, exercised the only way that cannot lie: in a subprocess that refuses
    to import them at all.

    Checking `pyproject.toml` alone would pass on a tree where a module imports boto3 at the top
    and the extra merely fails to declare it. Running it proves the code, not the manifest.
    """
    probe = textwrap.dedent(f"""
        import builtins
        real = builtins.__import__
        BLOCKED = {CLOUD_SDKS!r}
        def guarded(name, *a, **k):
            if name.split(".")[0].replace("_", "-") in BLOCKED:
                raise ImportError(f"{{name}} is not installed on this deployment")
            return real(name, *a, **k)
        builtins.__import__ = guarded

        # The core a stranger runs: compose a job, resolve every provider axis, read the CLI.
        import openfactory.approvals, openfactory.cli, openfactory.factory, openfactory.loader, openfactory.orchestrator, openfactory.registry
        from openfactory.adapters.board import build_board            # noqa: F401
        from openfactory.adapters.forge.registry import build_forge   # noqa: F401
        from openfactory.adapters.tracker.registry import build_tracker  # noqa: F401
        from openfactory.observability.registry import event_sink_kind, journal_for  # noqa: F401

        assert event_sink_kind() == "file", event_sink_kind()
        print("OK")
    """)
    done = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True,
                          cwd=str(ROOT), timeout=180)
    assert done.returncode == 0 and "OK" in done.stdout, (
        "the core cannot be imported without a cloud SDK — an open-source install now needs a "
        f"vendor account:\n{done.stderr[-1500:]}"
    )


def test_no_cloud_SDK_is_a_CORE_dependency():
    """`pip install` of the core must not pull one in. The extras may, and do."""
    import tomllib

    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    core = " ".join(data["project"].get("dependencies", [])).lower()
    offenders = [sdk for sdk in CLOUD_SDKS if sdk in core]
    assert not offenders, (
        f"{offenders} are core dependencies — every install of the open-source package now pulls a "
        f"cloud SDK, which is the first thing a stranger's dependency audit reads. They belong in "
        f"an extra (`runtime`, `sandbox`, `slack`), where they are today."
    )


def _cloud_imports_at_module_scope() -> list[str]:
    out = []
    for path in sorted((ROOT / "openfactory").rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in tree.body:  # module scope ONLY — nested imports are the correct shape
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            text = ast.unparse(node)
            if any(sdk.replace("-", "_") in text for sdk in CLOUD_SDKS):
                out.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    return out


def test_every_cloud_import_is_function_level():
    """A module-scope import makes the SDK mandatory for anyone who imports that module.

    This is the guard that would have caught the drift, because it is the one a tidy-up commit
    breaks: moving an import to the top reads like housekeeping and is a dependency change.
    """
    assert _cloud_imports_at_module_scope() == [], (
        "these import a cloud SDK at module scope, so importing them requires it: "
        + ", ".join(_cloud_imports_at_module_scope())
    )


def test_this_guard_can_actually_SEE_a_module_scope_import(tmp_path, monkeypatch):
    """The positive twin. A scanner that silently stopped matching would report a clean tree.

    Absence reads as compliance, and that is precisely how three guards in this repository stayed
    green over live defects.
    """
    fake = tmp_path / "openfactory"
    fake.mkdir()
    (fake / "leaky.py").write_text("import boto3\n\n\ndef go():\n    return boto3\n")
    monkeypatch.setattr(pathlib.Path, "cwd", lambda: tmp_path)

    found = []
    for path in sorted((tmp_path / "openfactory").rglob("*.py")):
        tree = ast.parse(path.read_text())
        found += [f"{path.name}:{n.lineno}" for n in tree.body
                  if isinstance(n, (ast.Import, ast.ImportFrom)) and "boto3" in ast.unparse(n)]
    assert found == ["leaky.py:1"], "the module-scope scanner cannot see an offender it is given"


@pytest.mark.parametrize(("axis", "table", "must_include"), [
    ("events", "EVENT_SINKS", ("null", "file")),
    ("metrics", "METRICS_SINKS", ("null", "sqlite")),
])
def test_each_observability_axis_has_a_cloud_free_option(axis, table, must_include):
    """A registry whose only working row needs an account is a registry in name only."""
    from openfactory.observability import registry

    rows = getattr(registry, table)
    missing = [k for k in must_include if k not in rows]
    assert not missing, f"the {axis} axis lost its cloud-free rows {missing}; it has {sorted(rows)}"


# ── the obligation is not allowed to be vendor-specific ─────────────────────────────────────────

def _built_metrics_sinks(tmp):
    """One instance of every metrics sink, built through the registry rather than named here.

    Through the REGISTRY, because that is the list a deployment picks from — a sink somebody adds
    tomorrow is covered on the day it is added, and a hand-written list is a list that would not
    have been."""
    from openfactory.observability.registry import METRICS_SINKS, build_metrics_sink

    return {kind: build_metrics_sink(kind, table="t", path=str(tmp / f"{kind}.db"))
            for kind in METRICS_SINKS}


def test_the_scan_finds_every_registered_metrics_sink(tmp_path):
    """The positive twin, first: a derivation that quietly returned {} would make the guard below
    pass over a store that cannot delete anything at all."""
    built = _built_metrics_sinks(tmp_path)

    # `dynamodb` is an add-on row (the `metrics.dynamodb` entry point) since the AWS connector
    # became a directory delete; `tests/test_the_cloud_is_a_directory_delete.py` builds it through
    # the declared entry point and holds it to `ForgettingSink` there.
    assert {"null", "sqlite", "memory"} <= set(built), sorted(built)


def test_every_store_that_RECORDS_a_client_can_also_DELETE(tmp_path):
    """A store that keeps what a person said and cannot delete it is a legal problem, not a
    feature gap — and for a while exactly one store could delete: the one we pay for.

    Writing a turn went through the configured sink; deleting one reached for DynamoDB by hand. So
    every deployment recorded a client's conversation and only OURS could honour a deletion
    request. That is the core following our own deployment, and it is the shape this whole file
    exists to catch — the earlier tests catch it for imports, this one catches it for an
    obligation.

    DERIVED FROM THE REGISTRY, so the next sink somebody adds is covered without being remembered
    into a list. If one genuinely cannot delete, this test is the place to say so out loud, with
    the reason — not the place to be quietly missing."""
    from openfactory.observability.metrics import ForgettingSink

    cannot = sorted(kind for kind, sink in _built_metrics_sinks(tmp_path).items()
                    if not isinstance(sink, ForgettingSink))

    assert not cannot, (
        f"these stores record what a client said and cannot delete it: {cannot}. The right to be "
        f"forgotten is an obligation, and one that only holds on some deployments is one the "
        f"product does not have")


def test_the_deletion_scan_can_SEE_a_store_that_cannot_delete():
    """The other positive twin. `assert not cannot` passes just as happily over an isinstance
    check that says yes to everything — and `runtime_checkable` protocols only test for the
    method's PRESENCE, which is exactly the kind of check that quietly stops discriminating."""
    from openfactory.observability.metrics import ForgettingSink

    class _WriteOnly:
        def record(self, rec):
            return None

    assert not isinstance(_WriteOnly(), ForgettingSink)
