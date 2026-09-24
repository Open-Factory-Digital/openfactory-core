"""The forge is handed the card's own text only in words it cannot read as one of its items (#167).

#179 named the CARD in the forge's terms: `#12: title` where the forge owns the card, and the title
alone with a `Card: 12` trailer everywhere else. But the title itself, and the objective under it,
still went to the forge verbatim — and the tracker's own mentions ride in them. The factory writes
one itself: pre-flight titles every child it splits off `Plan 92a — Guest hardening [auto-split of
#37]`, where `#37` is the PARENT CARD's ref on the board. So on a local board over GitHub, the
child's commit subject and pull request title mentioned `acme/api#37`; over Azure Repos, work item
37 of the organisation — the defect #167 reported, one card over. And an objective that says
`Fixes #36` about the board's card 36 put that closing line into the pull request body, where GitHub
closes `acme/api#36` at the merge: an item the factory never delivered.

What is held here, on the walking skeleton's real path — the commit read back from the far side of
the push, and the title and body the forge is handed:

  * where the forge does NOT own the card, no `#<number>` of the card's text reaches the title, the
    commit or the body — each is written `card <number>`, which keeps the reference readable and
    traceable and names nothing in the forge;
  * where the forge owns the card, the text is unchanged: its `#37` is the forge's own item 37,
    which is the card it names;
  * the verdict is the rows' own (`item_space`), the same one #179 decides the card's own name by.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from openfactory.contracts import AcceptanceCriterion, Ticket
from tests.test_a_card_is_named_in_the_forge_only_where_the_forge_owns_it import (
    _IDS,
    _MENTION,
    _PAIRINGS,
    _make_repo,
    _run,
)

#: A closing word followed by something a forge reads as one of its items — the phrase that closes
#: an item at the merge, not the bare word, which is harmless in a sentence.
_CLOSES_AN_ITEM = re.compile(
    r"\b(close[sd]?|fix(e[sd])?|resolve[sd]?)\b:?\s+\S*#\d", re.IGNORECASE)

#: The PARENT's ref on the board, as the splitter writes it into the child's title.
_PARENT = "#37"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return _make_repo(tmp_path)


def _split_child(card_id: str, repo: str) -> Ticket:
    """A child the pre-flight splitter created — its title in the splitter's own words, and an
    objective a person wrote about another card on the same board."""
    from openfactory.runtime.temporal.activities import _child_title

    return Ticket(
        id=card_id, title=_child_title("Plan 92 — Guest hardening", 0, _PARENT),
        objective="Finish what #37 left open. Fixes #36 on the way.", repo=repo,
        acceptance_criteria=[AcceptanceCriterion(text="feature.py exists")],
    )


def test_the_splitter_names_the_parent_by_its_ref_on_the_board() -> None:
    """The premise, read from the splitter rather than assumed: the factory itself writes the
    tracker's `#37` into a card's title."""
    child = _split_child("#38", "shop")
    assert child.title == "Plan 92a — Guest hardening [auto-split of #37]"


@pytest.mark.parametrize(("label", "tracker", "forge", "card_id", "repo_name", "owned", "title"),
                         _PAIRINGS, ids=_IDS)
def test_the_cards_own_text_reaches_the_forge_only_in_its_words(
        repo, tmp_path, label, tracker, forge, card_id, repo_name, owned, title) -> None:
    ticket = _split_child(card_id, repo_name)
    opened, message = _run(repo, tmp_path, tracker(tmp_path), forge(tmp_path), ticket)
    subject = message.strip().partition("\n")[0]
    body = opened["body"]

    if owned:
        # the forge's own items: `#37` IS the parent, so it stays a link, byte for byte
        mention = title.split(":", 1)[0]
        assert opened["title"] == f"{mention}: Plan 92a — Guest hardening [auto-split of #37]"
        assert subject == opened["title"]
        assert "Finish what #37 left open. Fixes #36 on the way." in body.splitlines()
        return

    # nothing of the card's text that the forge could read as one of its items …
    for text in (opened["title"], message, body):
        assert not _MENTION.search(text), text
    # … and so nothing the merge could close
    assert not _CLOSES_AN_ITEM.search(body), body
    assert not _CLOSES_AN_ITEM.search(message), message
    # but the reference is still there to read, and to trace
    assert opened["title"] == "Plan 92a — Guest hardening [auto-split of card 37]"
    assert subject == opened["title"]
    assert "Finish what card 37 left open. Fixes card 36 on the way." in body.splitlines()


@pytest.mark.parametrize(("text", "expected"), [
    ("[auto-split of #37]", "[auto-split of card 37]"),
    ("#37 first", "card 37 first"),
    ("see (#37)", "see (card 37)"),
    ('the "#37" card', 'the "card 37" card'),
    ("acme/issues#37", "acme/issues card 37"),
    ("Fixes #36, #37", "Fixes card 36, card 37"),
    # not a mention: no number after the sign, or no sign at all
    ("C# and F#", "C# and F#"),
    ("issue # 4", "issue # 4"),
    ("PROJ-12 and GH-less", "PROJ-12 and GH-less"),
    ("", ""),
])
def test_what_counts_as_a_mention(text, expected) -> None:
    """The same test the card's own id is held to (`#` and a number), wherever it stands in a
    sentence — including the tail of a qualified `owner/name#37`."""
    from openfactory.orchestrator.machine import without_mentions

    assert without_mentions(text) == expected
    assert not _MENTION.search(without_mentions(text))


def test_a_body_built_without_a_verdict_carries_no_mention_of_the_cards_text() -> None:
    """A stub holder with no tracker and no forge takes the neutral side for the objective too."""
    import types

    from openfactory.contracts import Manifest, RunResult
    from openfactory.orchestrator.machine import JobRunner

    body = JobRunner._pr_body(types.SimpleNamespace(manifest=Manifest()),
                              _split_child("#38", "shop"),
                              RunResult(ticket_id="#38", state="pr_open"))
    assert not _MENTION.search(body), body
    assert "Finish what card 37 left open. Fixes card 36 on the way." in body.splitlines()
