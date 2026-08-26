"""A card names its repository, and EVERY door must honour it — not just the durable one.

C-18 says the product owns the board and the repository travels on the ticket. The view that
implements it lived beside the Temporal activities, so only the poller applied it. `sdlc run` built
its runner from the raw registry entry and edited the DEFAULT repository whatever the card said.

FOUND ON THE FIRST REAL MULTI-REPO TICKET, and the platform's own guard caught the consequence
before this test existed. `Deskline/fx-dsk-ui#15` — a card about the TypeScript UI — produced a
PR against `fx-dsk-flows` editing `src/Admissao.cs`, the .NET backend. The independent review
rejected it, score 10: *"the diff only modifies the .NET backend but the ticket's entire premise is
the UI."* The review was right and the routing was wrong.

THE CLI IS THE DOOR THAT MATTERED MOST HERE. It is what an operator uses to try the platform, and
what an onboarding session runs in front of a client's developers. A capability that works on the
poller and not there is a capability that is missing exactly when somebody is watching.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: Every place a job is composed from a ticket. Named one by one, because a sweep would be
#: satisfied by a door being deleted — and the point is that these specific doors keep asking.
ENTRY_POINTS = [
    ("openfactory/cli.py", "run"),
    ("openfactory/runtime/temporal/activities.py", "_do_run_job"),
    ("openfactory/runtime/temporal/activities.py", "_run_ci_repair"),
]


def _calls_in(path: str, func: str) -> set[str]:
    tree = ast.parse((ROOT / path).read_text())
    node = next((n for n in ast.walk(tree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == func), None)
    assert node is not None, f"{func} vanished from {path} — this guard now guards nothing"
    return {c.func.id for c in ast.walk(node)
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}


@pytest.mark.parametrize(("path", "func"), ENTRY_POINTS)
def test_the_entry_point_resolves_the_CARDS_repository(path, func):
    assert "_runner_view" in _calls_in(path, func), (
        f"{path}::{func} composes a job without asking which repository the card names — on a "
        f"multi-repo product it edits the default one and the PR lands in the wrong place"
    )


def test_the_view_lives_where_every_door_can_reach_it():
    """It was in `runtime/temporal/`, which is why only the durable door used it.

    An import path is an architectural claim: a C-18 helper inside the Temporal package says C-18
    is a Temporal concern. It is not — it is what the ticket means.
    """
    from openfactory.runtime import card_repo

    assert hasattr(card_repo, "_runner_view") and hasattr(card_repo, "_ref_repo")


def test_a_qualified_card_moves_the_code_and_not_the_board():
    """The property itself, on the shape that exposed the bug: two coordinates, different levels."""
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.runtime.card_repo import _runner_view

    opts = {"organization": "acme-ai"}
    project = Project(
        name="fx-dsk", repo_path="https://dev.azure.com/acme-ai/Deskline/_git/fx-dsk-flows",
        tracker=ProviderRef(kind="azure_devops", repo="Deskline", options=opts),
        forge=ProviderRef(kind="azure_devops", repo="fx-dsk-flows", options=opts),
        ci=ProviderRef(kind="azure_devops", repo="fx-dsk-flows", options=opts),
    )

    view, key = _runner_view(project, "Deskline/fx-dsk-ui#15")

    assert view.forge.repo == "Deskline/fx-dsk-ui", "the PR would open on the wrong repository"
    assert view.repo_path.endswith("/fx-dsk-ui"), "the agent would edit the wrong checkout"
    assert view.tracker.repo == "Deskline", "the board belongs to the product"
    assert key != "fx-dsk", "two repositories of one product would share a checkout"
