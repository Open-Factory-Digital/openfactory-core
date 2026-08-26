"""Four registries, one spelling — enforced, because four comments could not enforce it.

Azure DevOps nests `organization / project / repository`, one level deeper than GitHub, so every
axis needs coordinates GitHub can read off `owner/name`. Each of the four registries grew its own
copy of that resolution, and each carried a comment promising the other three would move with it.
Two had already drifted by the time the fourth was written:

- the board's copy raised `ValueError` on a registry row spelled exactly the way the tracker
  registry documents (`org` as an alias, the ADO project from `tracker.repo`) — and `scan_todo`
  does not catch it, so that is a poller tick with a stack trace where the pickup queue should be;
- the environment's copy did not honour the tracker fallback at all, so a documented row built a
  working tracker, board and forge and then raised at `PromotionRunner` construction — the
  promotion dying before a pipeline was ever read.

THE WORSE FAILURE IS THE ONE NEITHER OF THOSE WAS. A drift does not have to raise: two axes can
both succeed and resolve to DIFFERENT ADO projects, and a board reporting on work items the
tracker never writes to is a factory that looks like it is running.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

ADAPTERS = pathlib.Path(__file__).resolve().parents[1] / "openfactory" / "adapters"
HOME = ADAPTERS / "azure_devops.py"

REGISTRIES = [
    "tracker/registry.py",
    "forge/registry.py",
    "environment/registry.py",
    "board/factory.py",
]


def _reads_the_org_option(path: pathlib.Path) -> list[str]:
    """Functions in `path` that pull `organization`/`org` out of an options dict themselves.

    AST over the string constants inside each call, not a grep for the word: the docstrings that
    explain this rule contain `organization` several times each, and a substring guard tripping on
    its own explanation is a trap this repository has already fallen into three times in one day.
    """
    out = []
    for node in ast.walk(ast.parse(path.read_text())):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for call in ast.walk(node):
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "get"):
                continue
            args = [a.value for a in call.args if isinstance(a, ast.Constant)]
            if "organization" in args or "org" in args:
                out.append(node.name)
                break
    return out


def test_the_one_home_actually_resolves_the_coordinates():
    """The positive twin. Without it, deleting `coordinates` makes every check below pass."""
    assert _reads_the_org_option(HOME) == ["coordinates"], (
        "adapters/azure_devops.py::coordinates is meant to be the one place that reads these "
        "options; if it no longer does, the guards below are asserting nothing"
    )


@pytest.mark.parametrize("registry", REGISTRIES)
def test_no_registry_spells_the_coordinates_itself(registry):
    offenders = _reads_the_org_option(ADAPTERS / registry)
    assert not offenders, (
        f"{registry} resolves the Azure DevOps coordinates itself in {offenders} — call "
        f"`coordinates(project, ref=…)` instead. Four copies is how two of them came to disagree "
        f"about which ADO project a registry row names."
    )


def test_every_axis_resolves_a_documented_row_to_THE_SAME_project():
    """The property the copies existed to keep, asserted instead of promised.

    The row is written the way `tracker/registry.py` documents — the organization named once, the
    ADO project inherited from the tracker's `repo` — which is precisely the shape two of the four
    copies used to get wrong.
    """
    from openfactory.adapters.board import build_board
    from openfactory.adapters.environment.registry import build_observer
    from openfactory.adapters.forge.registry import build_forge
    from openfactory.adapters.tracker.registry import build_tracker
    from openfactory.contracts.project import Project, ProviderRef

    project = Project(
        name="fx-ado", repo_path="/tmp/fx-ado",
        tracker=ProviderRef(kind="azure_devops", repo="factory",
                            options={"organization": "acme-ai"}),
        forge=ProviderRef(kind="azure_devops", repo="fx-ado",
                          options={"organization": "acme-ai"}),
    )
    built = {
        "tracker": build_tracker(project, token="t"),
        "board": build_board(project, token="t"),
        "forge": build_forge(project, token="t"),
        "observer": build_observer(project, token="t"),
    }
    resolved = {axis: _coordinates_on_the_wire(adapter) for axis, adapter in built.items()}
    assert set(resolved.values()) == {("acme-ai", "factory")}, (
        f"the axes disagree about which Azure DevOps project this row names: {resolved}"
    )


def _coordinates_on_the_wire(adapter) -> tuple[str | None, str | None]:
    """The org/project the adapter's own HTTP client will put in a URL.

    THROUGH THE CLIENT, not off the adapter. Two of the four keep the coordinates as their own
    attributes and two keep only a client — so reading `adapter.organization` scored the observer
    as `(None, None)` and would have scored a genuinely divergent one the same way. Absence read as
    agreement, which is the failure this whole file exists to catch.

    The client is also the honest place to ask: it is what builds the URL, so this asserts what
    reaches Azure DevOps rather than what a constructor happened to keep.
    """
    from openfactory.adapters.azure_devops import AzureDevOpsClient

    if isinstance(adapter, AzureDevOpsClient):
        return adapter.organization, adapter.project
    for value in vars(adapter).values():
        if isinstance(value, AzureDevOpsClient):
            return value.organization, value.project
    # a lazily-built client (the forge mints one per call so a rotating token is re-read)
    factory = getattr(adapter, "_client", None)
    if callable(factory):
        made = factory()
        if isinstance(made, AzureDevOpsClient):
            return made.organization, made.project
    return None, None
