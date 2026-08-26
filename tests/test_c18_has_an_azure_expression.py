"""One board, three repositories — on a provider that gives the card no repository at all.

C-18 says the product owns the board and the repository travels ON the ticket. On GitHub that is a
READ and nothing more: a Projects v2 card IS an issue in a repository, so `GitHubProjectBoard` lifts
`repository { nameWithOwner }` off the GraphQL and mints `owner/name#3` — the card already names
its repository, so routing it to the right clone needs no convention, label, or inference. That
shape is what `docs/ONBOARDING.md` §10 teaches for a product spanning several repositories, and
what ADR-0036 reasons about when it orders work across them.

That sentence is exactly what does not hold on Azure Boards. A work item lives in a PROJECT which
holds N git repositories, with no link to any of them. So the mechanism had nothing to read, every
card on a three-repo product would have arrived bare, resolved to the single registry `forge.repo`,
and sent the agent to edit the wrong tree — silently, which is the only part that matters.

AREA PATH IS THE ADO-NATIVE ANSWER, verified against the live API before it was written: a child
area is creatable by API, `System.AreaPath` comes back on the work item, and WIQL filters `UNDER`
it. It is also how real Azure teams already partition a project, so it asks a client for nothing
they were not going to do.

TWO THINGS THIS FILE EXISTS TO PIN, both learned by running it rather than reading it:

1. The ref must be PROJECT-qualified. `split_repo_ref` only splits a ref whose repo segment
   contains a `/`, so a bare `fx-dsk-ui#3` travels downstream LOOKING qualified and resolves to the
   default repository anyway — the silent misroute this mechanism exists to prevent, reintroduced
   by the mechanism itself.
2. A deployment that asks for nothing gets today's behaviour, byte for byte.
"""

from __future__ import annotations

import pytest

from openfactory.adapters.board.azure_devops import AzureBoardsBoard
from openfactory.contracts.refs import split_repo_ref

DEFAULT = "factory/fx-ado"


def _board(**kw) -> AzureBoardsBoard:
    return AzureBoardsBoard(organization="acme-ai", project="factory", token="t", **kw)


@pytest.mark.parametrize(("area", "expected"), [
    ("factory\\fx-dsk-ui", "factory/fx-dsk-ui"),
    ("factory\\fx-dsk-flows", "factory/fx-dsk-flows"),
    # nested areas: the LEAF carries the meaning, the root is the project every card shares
    ("factory\\Portal\\Admin", "factory/Admin"),
    # the project root means "not partitioned", i.e. the default repository
    ("factory", ""),
    ("", ""),
])
def test_an_area_path_names_the_repository(area, expected):
    assert _board(default_repo=DEFAULT)._repo_for_area(area) == expected


def test_a_client_whose_areas_are_not_named_after_repos_declares_the_map():
    board = _board(default_repo=DEFAULT, areas={"Portal": "dsk-ui"})
    assert board._repo_for_area("factory\\Portal") == "factory/dsk-ui"
    # matched case-insensitively: typing `portal` for an area named `Portal` is not a mistake
    # worth a silent misroute
    assert _board(default_repo=DEFAULT, areas={"portal": "dsk-ui"})._repo_for_area(
        "factory\\Portal") == "factory/dsk-ui"


def test_the_qualified_ref_actually_SPLITS_downstream():
    """The one that a green unit test would have missed.

    `qualify_ref` and `split_repo_ref` are not inverses: the split requires a `/` inside the repo
    segment (`refs.py:86`). A ref qualified as `fx-dsk-ui#3` therefore round-trips to the DEFAULT
    repo while looking, to every reader, like it carried its own. Asserting the mint without
    asserting the split is asserting the bug.
    """
    board = _board(default_repo=DEFAULT)
    minted = f"{board._repo_for_area('factory\\fx-dsk-ui')}#3"

    repo, bare = split_repo_ref(minted, DEFAULT)
    assert repo == "factory/fx-dsk-ui", f"{minted!r} fell back to the default repository"
    assert bare == "3"

    # and the forge takes the last segment, so the extra one costs nothing there
    from openfactory.adapters.forge.azure_devops import AzureReposForge

    assert AzureReposForge(repo, organization="o", project="p", token="t").repo == "fx-dsk-ui"


def test_the_tracker_reads_a_qualified_ref_instead_of_raising():
    """It raised on every qualified ref, so a multi-repo product failed at the FIRST read."""
    from openfactory.adapters.tracker.azure_devops import AzureBoardsTracker

    assert AzureBoardsTracker.work_item_id("factory/fx-dsk-ui#3") == "3"
    assert AzureBoardsTracker.work_item_id("#12") == "12"
    assert AzureBoardsTracker.work_item_id("12") == "12"


def test_a_deployment_that_asks_for_nothing_gets_todays_behaviour(monkeypatch):
    """The whole migration cost. Without a `default_repo` the board must not even LOOK at areas —
    a single-repo project has nothing to disambiguate, and paying a batch read per poll tick to
    learn that would be a cost with no answer."""
    board = _board()
    called = []
    monkeypatch.setattr(board, "_client", lambda **kw: called.append(kw) or _unreachable())

    assert board._qualify(["3", "4"]) == ["3", "4"]
    assert called == [], "the board read metadata it had no use for"


def _unreachable():  # pragma: no cover — reaching this IS the failure the test asserts against
    raise AssertionError("the board should not have made a call")


def test_unreadable_areas_degrade_to_bare_refs_LOUDLY(monkeypatch, caplog):
    """A metadata hiccup must not empty the pickup queue.

    Returning `[]` here would turn "I could not read the area paths" into "nothing is queued",
    which is the failure this adapter is written against end to end. Bare refs still route to the
    default repository — every deployment's behaviour before this existed — and the warning is what
    says the routing is now a guess.
    """
    board = _board(default_repo=DEFAULT)

    class _Boom:
        def values(self, *a, **k):
            raise RuntimeError("502 Bad Gateway")

    monkeypatch.setattr(board, "_client", lambda **kw: _Boom())
    with caplog.at_level("WARNING"):
        assert board._qualify(["3", "4"]) == ["3", "4"]

    assert "WRONG repository" in caplog.text
