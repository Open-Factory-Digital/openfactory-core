"""The review request must be AUTHENTICATED and it must not be `gh` — ADR-0031, then #95.

WHAT HAPPENED FIRST. The client clicked "Confirmar e registrar", the write ran, the branch was
pushed — and the pull request never opened. The worker's log said it plainly:

    product: gh pr failed: To get started with GitHub CLI, please run: gh auth login

The module authenticated TWICE, by two different mechanisms: `git push` through a clone URL with
the credential embedded, and `gh` through its own ambient login. Only the first was ever fed.
Nobody runs `gh auth login` in the worker container and no GH_TOKEN was exported for the
subprocess, so every `gh pr create` from the product role failed. The single baseline PR that
exists was created from a laptop, which is exactly why this looked like it worked. Requirement
authoring had NEVER opened a pull request in production.

WHAT HAPPENED NEXT. Handing `gh` a token fixed that on GitHub and created a second problem one
vendor over: the token a caller passes is `ProductModule.token`, which on an Azure Repos project is
that project's `AZURE_DEVOPS_PAT` — so a Microsoft secret was about to be exported as `GH_TOKEN`
to a process that talks to github.com. The stopgap was a runner that REFUSED on any non-GitHub
forge, which was honest and lost the whole ceremony.

WHAT IS TRUE NOW. There is no `gh` in this module. Every pull-request act goes through the forge
adapter, which carries its own credential, mints its own token where the registry says so, and
speaks its own vendor. This file therefore asserts the property the token argument was standing in
for — *the review request is opened by something that is authenticated for the repository it is
opening it in* — plus the one guard that keeps the old defect from walking back in: no subprocess
here may be a forge CLI.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from openfactory.product import authoring

_SRC = Path("openfactory/product/authoring.py").read_text()
_FORGE_CLIS = ("gh", "glab", "az", "tf")


def test_no_forge_CLI_is_ever_shelled_out_to_from_this_module():
    """THE DEFECT CLASS, ASSERTED STRUCTURALLY. Two separate production failures came out of this
    module running a vendor's command line: an unauthenticated one, and an authenticated one
    pointed at the wrong vendor. The only `subprocess.run` left must be `git`, which is
    vendor-neutral and takes its credential inside the clone URL.

    Read from the AST rather than grepped, so a `gh` inside a docstring or a marker name cannot
    make this pass or fail for the wrong reason."""
    tree = ast.parse(_SRC)
    programs: list[str] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and ast.unparse(node.func).endswith("subprocess.run")):
            continue
        argv = node.args[0] if node.args else None
        assert argv is not None, f"subprocess.run with no argv at line {node.lineno}"
        first = argv.elts[0] if isinstance(argv, ast.List) and argv.elts else None
        programs.append(getattr(first, "value", ast.unparse(first) if first else "?"))

    assert programs, "nothing runs a subprocess at all — this guard is watching an empty room"
    assert set(programs) == {"git"}, f"a vendor CLI is back in the product path: {programs}"
    for cli in _FORGE_CLIS:
        assert cli not in programs


def test_the_gh_runner_and_its_helper_are_GONE():
    """A reachability guard on a DELETION. `gh_runner` returning "" on a non-GitHub forge was the
    honest stopgap; leaving it importable is how a fourth call site quietly re-adopts it and the
    product path becomes GitHub-only again in one commit."""
    assert not hasattr(authoring, "gh_runner")
    assert not hasattr(authoring, "_gh")


@pytest.mark.parametrize("fn", ["propose_requirement", "propose_baseline", "land_open_proposals"])
def test_every_public_writer_takes_the_FORGE(fn):
    """The credential travels inside the adapter now, so the adapter is the argument that must be
    there. All three: the two writers, and the sweep that finishes what a writer could not."""
    assert "forge" in inspect.signature(getattr(authoring, fn)).parameters, fn


@pytest.mark.parametrize("fn", ["propose_requirement", "propose_baseline"])
def test_the_module_passes_a_forge_it_BUILT(fn):
    """REACH. The parameter existing while `ProductModule` never fills it changes nothing — that is
    this codebase's most repeated defect, and the version of it that shipped here was the token
    parameter: accepted, documented, and never passed.

    `_forge()` and not any expression: it is the seam that reads the registry, so it is the one
    thing that makes a deployment's declared vendor the vendor this write actually uses."""
    tree = ast.parse(Path("openfactory/product/module.py").read_text())
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and getattr(n.func, "id", None) == fn]
    assert calls, f"{fn} is not called from the module at all"
    for call in calls:
        forged = [k for k in call.keywords if k.arg == "forge"]
        assert forged, (f"{fn} is called without a forge at line {call.lineno} — the push would "
                        f"work and the pull request would not, which is exactly what shipped")
        assert "_forge()" in ast.unparse(forged[0].value), ast.unparse(forged[0].value)


def test_a_failed_PR_tells_the_CLIENT_something_they_can_act_on():
    """The message that reached a person read: "the branch req/0001-… was pushed but the pull
    request could not be opened; open it by hand against main". English, a branch name, and an
    instruction somebody who runs an accounting firm cannot carry out — three things ADR-0026
    forbids, in one sentence."""
    from openfactory.product.voice import client_safe_detail

    # the DETAIL the client reads, isolated from the operator log line above it
    i = _SRC.index("OPENFACTORY_PRODUCT_PR_FAILED")
    detail = _SRC[i:i + 900].split("return WriteResult")[1]
    assert "{branch}" not in detail, "the branch name is still interpolated into the client's text"
    assert "by hand" not in detail, "the client is still told to open a pull request themselves"
    assert "Nada se perdeu" in detail, "the client is not told the work is safe"

    # and the old sentence would now be caught even if it came back
    old = ("the branch req/0001-x was pushed but the pull request could not be opened; "
           "open it by hand against main")
    safe, raw = client_safe_detail(old, language="pt-BR")
    assert raw == old and safe != old, "the sanitiser still lets delivery vocabulary through"


def test_the_failure_is_shouted_for_an_operator():
    """A pull request that never opens is work sitting on a branch nobody is watching."""
    assert "OPENFACTORY_PRODUCT_PR_FAILED" in _SRC
    assert "OPENFACTORY_PRODUCT_PR_CREATE_FAILED" in _SRC, (
        "the forge's own refusal is swallowed — `open_pr` raises, and this module turns the raise "
        "into an empty string; a marker is the only trace left of WHY")
