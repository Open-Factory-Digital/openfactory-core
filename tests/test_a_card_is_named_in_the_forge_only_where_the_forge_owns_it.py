"""A card is named in the forge's own terms only where the forge owns the card (#167).

The job wrote the tracker's card id, verbatim, into three things the FORGE owns and reads: the
commit message (`#12: title`), the pull request title (the same) and the pull request body
(`Closes #12`). That is right for exactly one pairing — a tracker and a forge that number the same
items — and the registry builds every other pairing too. Reproduced with a local board over a
hosted forge whose `#N` is an organisation-wide work item: ids 6, 7, 9, 10, 11, 12, 14, 15, 20, 50
and 100 all existed there, in other projects, so every early card's pull request mentioned (and on
a forge that honours the keyword, could close) somebody else's item.

What is held here, on the REAL path — a real worktree box, the real commit the job pushes, the
title and body the forge is handed:

  * each shipped row declares where its numbers live, and the pairing is decided by comparing the
    two declarations — equality, with an absent declaration matching nothing;
  * where the forge owns the card, the commit and the title carry the forge's own mention of it
    (`#12: title`, and `#1234: title` for a work item whose id carries no `#`);
  * everywhere else, the forge is handed text it cannot read as one of its items: the card's title
    alone, a `Card: 12` trailer on the commit, and the card named in the body with its URL;
  * a closing line is written only where the forge owns the card AND its row declares a word for
    it: GitHub, whose issue nothing else closes (the tracker's Done moves a column or a label).
    Azure Repos owns its organisation's work items and declares none, because its row already
    refuses to be a second writer of the card's state — so the card is named there and not closed.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from openfactory.contracts import AcceptanceCriterion, JobState, Manifest, Ticket

#: What a forge reads as one of its own items. `#12` alone, not `owner/name#12`, because the
#: neutral path writes neither.
_MENTION = re.compile(r"#\d")
#: A closing keyword anywhere at all — the neutral path has no business writing one, and after
#: this change neither has the owned one.
_CLOSING = re.compile(r"\b(close[sd]?|fix(e[sd])?|resolve[sd]?)\b", re.IGNORECASE)


# ── the shipped rows, built with no network ─────────────────────────────────────────────────────

def _local_tracker(tmp_path):
    from openfactory.adapters.tracker.local import LocalTracker

    return LocalTracker("shop", db_path=tmp_path / "board.db")


def _local_forge(tmp_path):
    from openfactory.adapters.forge.local import LocalForge

    return LocalForge("shop", str(tmp_path / "repo"), db_path=tmp_path / "board.db")


def _github_tracker(repo):
    from openfactory.adapters.tracker.github import GitHubIssuesTracker

    return GitHubIssuesTracker(repo, token="t")


def _github_forge(repo):
    from openfactory.adapters.forge.github import GitHubForge

    return GitHubForge(repo, token="t")


def _jira_tracker():
    from openfactory.adapters.tracker.jira import JiraTracker

    return JiraTracker(site="https://acme.atlassian.example", project_key="PROJ",
                       email="bot@acme.example", token="t")


def _ado_tracker(org):
    from openfactory.adapters.tracker.azure_devops import AzureBoardsTracker

    return AzureBoardsTracker(organization=org, project="Shop", token="t")


def _ado_forge(org):
    from openfactory.adapters.forge.azure_devops import AzureReposForge

    return AzureReposForge("shop-api", organization=org, project="Shop", token="t")


#: (label, tracker, forge, the id the tracker row produces, the card's repo, owned?, owned title).
#: The closing line an owned pairing gets is `_OWNED_CLOSING[label]`, "" for none.
#: Built lazily, because a row's constructor is an import of its vendor module.
_PAIRINGS = [
    ("local board over GitHub", lambda p: _local_tracker(p), lambda p: _github_forge("acme/api"),
     "#12", "shop", False, None),
    ("local board over Azure Repos", lambda p: _local_tracker(p), lambda p: _ado_forge("acme"),
     "#12", "shop", False, None),
    ("local board over the local forge", lambda p: _local_tracker(p), lambda p: _local_forge(p),
     "#12", "shop", False, None),
    ("GitHub issues over the same GitHub repository",
     lambda p: _github_tracker("acme/api"), lambda p: _github_forge("acme/api"),
     "#12", "acme/api", True, "#12: add the export"),
    ("GitHub issues kept in another repository",
     lambda p: _github_tracker("acme/issues"), lambda p: _github_forge("acme/api"),
     "#12", "acme/issues", False, None),
    # C-18: one board routes cards to several repositories, and the CARD's repository is the one
    # its `#12` lives in — here the tracker's default is the forge's repository and the card's
    # is not, so a declaration read from the adapter instead of the card would say "owned".
    ("GitHub issues, a card routed to another repository of the board",
     lambda p: _github_tracker("acme/api"), lambda p: _github_forge("acme/api"),
     "#12", "acme/web", False, None),
    ("Jira over GitHub", lambda p: _jira_tracker(), lambda p: _github_forge("acme/api"),
     "PROJ-12", "PROJ", False, None),
    ("Azure Boards over Azure Repos, same organisation",
     lambda p: _ado_tracker("Acme"), lambda p: _ado_forge("acme"),
     "1234", "Shop", True, "#1234: add the export"),
    ("Azure Boards over Azure Repos, another organisation",
     lambda p: _ado_tracker("acme"), lambda p: _ado_forge("elsewhere"),
     "1234", "Shop", False, None),
]
_IDS = [row[0] for row in _PAIRINGS]
#: GitHub closes its own issue at the merge and nothing else does; Azure Repos owns the work item
#: and declares no word, so the owned card is named and NOT closed — `Closes 1234` was inert before.
_OWNED_CLOSING = {
    "GitHub issues over the same GitHub repository": "Closes #12",
    "Azure Boards over Azure Repos, same organisation": "",
}


def _ticket(card_id: str, repo: str) -> Ticket:
    return Ticket(
        id=card_id, title="add the export", objective="export the orders as CSV", repo=repo,
        acceptance_criteria=[AcceptanceCriterion(text="feature.py exists")],
    )


@pytest.mark.parametrize(("label", "tracker", "forge", "card_id", "repo", "owned", "title"),
                         _PAIRINGS, ids=_IDS)
def test_the_shipped_rows_declare_whose_numbers_they_are(
        tmp_path, label, tracker, forge, card_id, repo, owned, title) -> None:
    """The verdict comes from the rows' own declarations — no vendor name in the core."""
    from openfactory.contracts.item_space import forge_owns_the_card

    assert forge_owns_the_card(tracker(tmp_path), forge(tmp_path), _ticket(card_id, repo)) is owned


# ── the real job path ───────────────────────────────────────────────────────────────────────────

def _git(args: list[str], cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout


def _make_repo(root: Path) -> Path:
    """The walking skeleton's shape: a checkout whose `origin` is a bare repository, so the job's
    push is real and its commit can be read back from the far side."""
    origin = root / "origin.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(origin)], check=True,
                   capture_output=True)
    checkout = root / "repo"
    checkout.mkdir()
    _git(["init", "-b", "main"], checkout)
    _git(["config", "user.email", "t@t.dev"], checkout)
    _git(["config", "user.name", "t"], checkout)
    _git(["remote", "add", "origin", str(origin)], checkout)
    (checkout / "README.md").write_text("# app\n")
    _git(["add", "-A"], checkout)
    _git(["commit", "-m", "init"], checkout)
    _git(["push", "-u", "origin", "main"], checkout)
    return checkout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return _make_repo(tmp_path)


def _declaring(fake, row, *, with_url: bool = True):
    """The fake takes the REAL row's declaration and its URL, and nothing else from it — so what is
    decided below is decided by what each shipped row actually says. A row that declares nothing
    leaves the fake declaring nothing: `hasattr` is the question the core itself asks."""
    if hasattr(row, "item_space"):
        fake.item_space = row.item_space
    fake.ticket_url = row.ticket_url if with_url else (lambda ref: "")
    return fake


def _run(repo: Path, tmp_path: Path, tracker_row, forge_row, ticket: Ticket, *,
         with_url: bool = True):
    from tests.test_walking_skeleton import FakeForge, FakeTracker, _runner

    tracker = _declaring(FakeTracker(ticket), tracker_row, with_url=with_url)
    forge = FakeForge()
    if forge_row is not None and hasattr(forge_row, "item_space"):
        forge.item_space = forge_row.item_space
    if forge_row is not None and hasattr(forge_row, "closing_keyword"):
        forge.closing_keyword = forge_row.closing_keyword
    runner = _runner(repo, tracker, Manifest(validate={"test": "true", "security": "true"}),
                     tmp_path, forge=forge)
    runner.project = type("_Project", (), {"name": "shop"})()
    result = runner.run(ticket.id)
    assert result.state is JobState.PR_OPEN, result
    origin = repo.parent / "origin.git"
    # THE COMMIT THE JOB PUSHED, read back from the forge's side of the push — not the string
    # the code meant to write.
    message = _git(["log", "-1", "--format=%B", forge.opened["head"]], origin)
    return forge.opened, message


@pytest.mark.parametrize(("label", "tracker", "forge", "card_id", "repo_name", "owned", "title"),
                         _PAIRINGS, ids=_IDS)
def test_the_forge_reads_the_card_only_where_it_owns_it(
        repo, tmp_path, label, tracker, forge, card_id, repo_name, owned, title) -> None:
    ticket = _ticket(card_id, repo_name)
    opened, message = _run(repo, tmp_path, tracker(tmp_path), forge(tmp_path), ticket)
    subject, _, rest = message.strip().partition("\n")
    body = opened["body"]

    # the commit never carries a closing keyword
    assert not _CLOSING.search(message), message

    if owned:
        # the forge's own mention, which is what links the card to the change natively — and a
        # closing line only in the word the forge row declares, and only if it declares one
        assert opened["title"] == title
        assert subject == title
        mention = title.split(":", 1)[0]
        assert f"Automated by OpenFactory for {mention}." in body
        closing = _OWNED_CLOSING[label]
        if closing:
            assert closing in body.splitlines(), body
            assert len(_CLOSING.findall(body)) == 1, body
        else:
            assert not _CLOSING.search(body), body
    else:
        assert opened["title"] == "add the export"
        assert subject == "add the export"
        bare = card_id.lstrip("#")
        assert f"Card: {bare}" in rest.splitlines(), message
        assert f"card {bare} on the shop board" in body
        assert not _CLOSING.search(body), body
        # nothing the forge could read as one of its own items: the title, the commit, the body
        for text in (opened["title"], message, body):
            assert not _MENTION.search(text), text


def test_the_url_goes_in_the_body_and_an_empty_one_leaves_no_line(repo, tmp_path) -> None:
    """The card's address is the tracker's answer, in the body and never in a title — and a
    tracker that cannot say (the port allows `""`) leaves no dangling separator either."""
    ticket = _ticket("#12", "shop")
    opened, message = _run(repo, tmp_path, _local_tracker(tmp_path), _ado_forge("acme"), ticket)
    url = _local_tracker(tmp_path).ticket_url("#12")
    assert url and url in opened["body"]
    assert url not in opened["title"]
    assert url not in message.splitlines()[0]

    elsewhere = tmp_path / "second"
    elsewhere.mkdir()
    opened, message = _run(_make_repo(elsewhere), elsewhere, _local_tracker(tmp_path),
                           _ado_forge("acme"), _ticket("#12", "shop"), with_url=False)
    first = opened["body"].splitlines()[0]
    assert first == "Automated by OpenFactory for card 12 on the shop board."
    assert not _MENTION.search(opened["body"])


def test_the_shipped_forges_declare_whether_they_close_what_they_own(tmp_path) -> None:
    """Read from the rows themselves: a word on GitHub, none on Azure Repos or the local forge. A
    mock, a phrase or a non-string is no declaration — the answer that cannot close anything."""
    from unittest.mock import MagicMock

    from openfactory.contracts.item_space import closing_keyword

    assert closing_keyword(_github_forge("acme/api")) == "Closes"
    assert closing_keyword(_ado_forge("acme")) == ""
    assert closing_keyword(_local_forge(tmp_path)) == ""
    assert closing_keyword(MagicMock()) == ""
    assert closing_keyword(type("_F", (), {"closing_keyword": "Closes #1"})()) == ""


def test_a_declaration_that_is_not_a_space_owns_nothing() -> None:
    """A test double answers every attribute, and a mock that 'declares' a mock is not a
    declaration: both sides would compare two different objects and happen to disagree today, and
    the same mock handed to both sides would happen to agree. Only a tuple of named parts counts."""
    from unittest.mock import MagicMock

    from openfactory.contracts.item_space import forge_owns_the_card

    both = MagicMock()
    assert forge_owns_the_card(both, both, _ticket("#12", "shop")) is False


def test_a_body_built_without_a_verdict_is_the_neutral_one() -> None:
    """Thirteen tests build a pull request body from a stub holder with no tracker and no forge.
    Handed no verdict, the body must take the side that cannot misname anything."""
    import types

    from openfactory.contracts import RunResult
    from openfactory.orchestrator.machine import JobRunner

    body = JobRunner._pr_body(types.SimpleNamespace(manifest=Manifest()), _ticket("#12", "shop"),
                              RunResult(ticket_id="#12", state="pr_open"))
    assert body.splitlines()[0] == "Automated by OpenFactory for card 12."
    assert not _MENTION.search(body)
    assert not _CLOSING.search(body)
