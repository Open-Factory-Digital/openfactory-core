"""A card that was SPLIT was closed as delivered, and the client was told its requirement was ready.

THE PORT SAYS *CLOSED IS NOT DELIVERED* and every close chooses its word — except the one the
pre-flight splitter makes. `_do_split` called `tracker.close_ticket(parent, note)` with no
`delivered=`, so the port's default applied, on every tracker: a card that shipped NOTHING, whose
work had just been moved into children that had not started, read downstream as work the client
got. The delivery sweep holds the card a requirement BECAME — the parent — so it announced the
requirement the moment the card was split. Measured 2026-09-19, the sentence a client would have
read: "what was asked for in requirement 7 is ready — all the work that came out of it is
finished", with both children open in Backlog.

WHAT IS DRIVEN HERE IS THE REAL `_do_split` AGAINST THE REAL `LocalTracker` on a board file of its
own, read back through the function the board sweep uses (`product/board.py::_ticket`) and judged
by the functions the delivery sweep calls (`activities._closed_issue_numbers`,
`followup.delivered`). The Azure Boards row is the real `AzureBoardsTracker` built by the real
registry row, over the recorded client `test_the_ado_tracker.py` already uses.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from openfactory.adapters.tracker import base as port
from openfactory.adapters.tracker.local import LocalTracker
from openfactory.contracts.project import Project, ProviderRef
from openfactory.product import followup
from openfactory.product.board import _ticket
from openfactory.product.triage import Ticket
from openfactory.runtime.temporal import activities as acts
from openfactory.runtime.temporal.io import SplitInput

ROOT = Path(__file__).resolve().parent.parent
CHILDREN = [{"title": "harden the guest surface", "objective": "o", "criteria": ["c1"]},
            {"title": "rate limits", "objective": "o2", "criteria": ["c2"]}]


@pytest.fixture
def board(tmp_path, monkeypatch):
    """One project on the local row, with the split's three outside reads pointed at it."""
    def _open(*, language: str = "en", to_todo: bool = False):
        tracker = LocalTracker("acme", db_path=tmp_path / "board.db")
        monkeypatch.setattr(acts, "_tracker_for", lambda project: tracker)
        monkeypatch.setattr(acts.ProjectRegistry, "get",
                            lambda self, name: SimpleNamespace(name="acme", language=language))
        import openfactory.loader
        monkeypatch.setattr(openfactory.loader, "load_manifest",
                            lambda project: SimpleNamespace(split_to_todo=to_todo))
        return tracker
    return _open


def _split(tracker, *, reasons: str = "two features in one card") -> str:
    parent = tracker.create_ticket(title="Plan 92 — Guest hardening",
                                   body="## Objective\no\n\n## Acceptance criteria\n- c")
    acts._do_split(SplitInput(project="acme", issue=parent.lstrip("#"), reasons=reasons,
                              children=CHILDREN))
    return parent


def _cards(tracker) -> dict[str, Ticket]:
    return {t.number: t for t in (_ticket(s, {}) for s in tracker.list_tickets(state="all"))}


def _the_sweep_says(tracker, *issues: str) -> dict:
    """What the delivery sweep decides for a requirement filed as `issues`, by its own two calls."""
    module = SimpleNamespace(_board_tickets=list(_cards(tracker).values()))
    loop = followup.open_loop(followup.DELIVERY, "7", owner=followup.OWNER,
                              ts="2026-09-19T10:00:00Z", context={"issues": ",".join(issues)})
    return followup.delivered([loop], acts._closed_issue_numbers(module))


# ── the word the split closes its parent with ───────────────────────────────────────────────────

def test_the_parent_of_a_split_is_closed_as_NOT_delivered(board):
    tracker = board()

    parent = _split(tracker)

    card = _cards(tracker)[parent.lstrip("#")]
    assert (card.state, card.state_reason, card.delivered) == ("closed", "not_planned", False)


def test_the_client_is_NOT_told_the_requirement_is_ready_at_the_split(board):
    """The measured defect. The loop holds the parent; both children are open in Backlog."""
    tracker = board()
    parent = _split(tracker)

    assert _the_sweep_says(tracker, parent.lstrip("#")) == {}


def test_it_IS_told_once_every_card_split_from_it_is_delivered(board):
    """The other half, and the reason flipping the word alone would not do: the parent never reads
    as delivered by itself again, so the sweep has to follow the split or stay silent for ever."""
    tracker = board()
    parent = _split(tracker).lstrip("#")
    first, second = (n for n in sorted(_cards(tracker)) if n != parent)

    tracker.close_ticket(first, "shipped in !4")
    assert _the_sweep_says(tracker, parent) == {}, "ALL, not some"

    tracker.close_ticket(second, "shipped in !5")
    assert list(_the_sweep_says(tracker, parent).values()) == ["delivered"]


def test_a_child_that_was_WITHDRAWN_delivers_nothing_for_its_parent(board):
    tracker = board()
    parent = _split(tracker).lstrip("#")
    first, second = (n for n in sorted(_cards(tracker)) if n != parent)

    tracker.close_ticket(first, "shipped in !4")
    tracker.close_ticket(second, "the client dropped it", delivered=False)

    assert _the_sweep_says(tracker, parent) == {}


def _card(number: str, title: str, state: str = "closed", reason: str = "completed") -> Ticket:
    return Ticket(number=number, title=title, state=state, state_reason=reason)


def delivered_numbers(tickets: list[Ticket]) -> set[str]:
    # imported where it is used, so that against a tree that has no such function these cases
    # fail one by one and say so, instead of the whole file failing to collect
    import importlib

    return importlib.import_module("openfactory.product.triage").delivered_numbers(tickets)


def test_a_parent_closed_as_DELIVERED_by_an_older_split_stops_counting_early_too():
    """Every board that ever split a card carries one. The word is ignored in both directions."""
    legacy = [_card("37", "Plan 92 — Guest hardening"),
              _card("101", "Plan 92a — Guest hardening [auto-split of #37]", "open", ""),
              _card("102", "Plan 92b — Guest hardening [auto-split of #37]")]

    assert delivered_numbers(legacy) == {"102"}

    legacy[1] = _card("101", "Plan 92a — Guest hardening [auto-split of #37]")
    assert delivered_numbers(legacy) == {"37", "101", "102"}


def test_a_parent_still_OPEN_is_a_split_that_did_not_finish():
    half_made = [_card("37", "Plan 92 — Guest hardening", "open", ""),
                 _card("101", "Plan 92a — Guest hardening [auto-split of #37]")]

    assert delivered_numbers(half_made) == {"101"}


def test_a_card_nobody_split_is_judged_exactly_as_it_was():
    plain = [_card("1", "a"), _card("2", "b", "closed", "not_planned"), _card("3", "c", "open", ""),
             _card("4", "d", "closed", ""), _card("CONT-9", "e [auto-split of #CONT-4]")]

    assert delivered_numbers(plain) == {"1", "4", "CONT-9"}
    assert delivered_numbers([]) == set()


def test_the_splitter_and_the_sweep_read_ONE_spelling_of_the_mark():
    from openfactory.contracts.refs import SPLIT_CHILD_MARK, split_parent_of

    title = acts._child_title("Plan 92 — Guest hardening", 0, "#37")

    assert acts._SPLIT_CHILD_MARK is SPLIT_CHILD_MARK and SPLIT_CHILD_MARK in title
    assert split_parent_of(title) == "37"
    assert split_parent_of(acts._child_title("Fix the widget", 1, "#CONT-412")) == "CONT-412"
    assert split_parent_of("Plan 92 — Guest hardening") == "" and split_parent_of(None) == ""


# ── what a person reads on the parent ───────────────────────────────────────────────────────────

def test_the_note_says_SPLIT_INTO_first_and_that_nothing_was_rejected(board):
    """The vendor's label for this close is "not planned". The note beside it is what stops a
    person reading that as "somebody turned this down"."""
    tracker = board()
    parent = _split(tracker)
    kids = ", ".join(f"#{n}" for n in sorted(_cards(tracker)) if n != parent.lstrip("#"))

    (note,) = [c.body for c in tracker.comments(parent)]

    assert note.startswith(f"✂️ Split into {kids}"), note
    assert "not rejected" in note and "continues in those cards" in note
    assert "two features in one card" in note and "in Backlog" in note


def test_and_it_is_written_in_the_PROJECTS_language(board):
    tracker = board(language="pt-BR")
    parent = _split(tracker, reasons="duas funcionalidades num cartão só")

    (note,) = [c.body for c in tracker.comments(parent)]

    assert note.startswith("✂️ Dividido em #") and "não foi rejeitado" in note
    assert "no Backlog" in note and "duas funcionalidades num cartão só" in note
    assert "Split into" not in note and "drag" not in note and "Pre-flight" not in note


@pytest.mark.parametrize("key", ["split.parent.closed", "split.parent.in-backlog",
                                 "split.parent.in-todo", "split.parent.straggler-one",
                                 "split.parent.stragglers"])
@pytest.mark.parametrize("language", ["en", "pt-BR"])
def test_every_sentence_of_that_note_exists_in_both_languages(key, language):
    from openfactory.techlead import voice

    said = voice.say(voice.NARRATION, key, language, children="#2, #3", where="…", why="big",
                     stuck="#3")

    assert said != key and "{" not in said
    assert voice.NARRATION[key]["en"] != voice.NARRATION[key]["pt-BR"]


# ── every generic close goes through the seam, and says its word ────────────────────────────────

class _RowFromBeforeTheKeyword(LocalTracker):
    def close_ticket(self, ref, reason):  # noqa: D102 — an add-on as one was written before #203
        raise AssertionError("closed with the word dropped: a split parent recorded as delivered")


def test_a_row_that_cannot_say_NOT_delivered_refuses_the_parents_close_BY_NAME(board, monkeypatch):
    board()
    old = _RowFromBeforeTheKeyword("acme", db_path=None)
    old._db = acts._tracker_for(None)._db
    monkeypatch.setattr(acts, "_tracker_for", lambda project: old)

    with pytest.raises(port.CannotSayUndelivered, match="`delivered`"):
        _split(old)


def test_a_resolved_impediment_is_closed_as_DELIVERED_and_through_the_seam(tmp_path):
    from openfactory.ops import impediment

    tracker = LocalTracker("acme", db_path=tmp_path / "board.db")
    project = SimpleNamespace(name="acme", language="en")
    ref = tracker.create_ticket(title=impediment.title_for("acme", "forge-auth"), body="broken")
    impediment._LAST.pop("acme|forge-auth", None)

    assert impediment.resolved(project, "forge-auth", tracker=tracker) is True

    card = _cards(tracker)[ref.lstrip("#")]
    assert (card.state, card.state_reason, card.delivered) == ("closed", "completed", True)


def test_no_generic_caller_closes_a_card_on_the_row_directly():
    """#203's guard looks for a direct call that PASSES `delivered=`. The split's call passed
    nothing, so that guard could not see the one caller that never chose a word. Outside the
    tracker rows a close is `adapters.tracker.base.close_ticket(tracker, …, delivered=…)`, whose
    keyword has no default."""
    rows = ROOT / "openfactory" / "adapters" / "tracker"
    around = []
    for path in sorted((ROOT / "openfactory").rglob("*.py")):
        if rows in path.parents:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "close_ticket"):
                around.append(f"{path.relative_to(ROOT)}:{node.lineno}")

    assert around == [], f"close through `adapters.tracker.base.close_ticket`: {around}"

    import inspect

    word = inspect.signature(port.close_ticket).parameters["delivered"]
    assert word.kind is inspect.Parameter.KEYWORD_ONLY and word.default is inspect.Parameter.empty


# ── the Azure Boards row's own sentence ─────────────────────────────────────────────────────────

def _azure(language: str | None, states=None):
    from openfactory.adapters.tracker.registry import build_tracker
    from tests.test_the_ado_tracker import COMMENT_MADE, ISSUE_STATES, PATCHED, _Recorded

    project = Project(name="factory", repo_path="/t", language=language or "en",
                      tracker=ProviderRef(kind="azure_devops", repo="factory",
                                          options={"organization": "acme-ai",
                                                   "project": "factory"}),
                      forge=ProviderRef(kind="github", repo="a/b"))
    tracker = build_tracker(project, token="t")
    tracker.ado = _Recorded({("GET", "wit/workitemtypes/Issue/states"): states or ISSUE_STATES,
                             ("POST", "wit/workItems/1/comments"): COMMENT_MADE,
                             ("PATCH", "wit/workitems/1"): PATCHED})
    return tracker


def _azure_said(tracker) -> str:
    (posted,) = [c for c in tracker.ado.writes() if c["method"] == "POST"]
    return posted["body"]["text"]


def test_the_azure_row_says_NOT_delivered_in_the_projects_language():
    tracker = _azure("pt-BR")

    tracker.close_ticket("1", "duplicado do 4", delivered=False)

    said = _azure_said(tracker)
    assert "duplicado do 4" in said and "NÃO entregue" in said and "**Done**" in said
    assert "NOT delivered" not in said and "Removed state" not in said


def test_and_in_english_for_a_project_that_speaks_it():
    tracker = _azure("en")

    tracker.close_ticket("1", "duplicate of 4", delivered=False)

    assert "NOT delivered" in _azure_said(tracker) and "**Done**" in _azure_said(tracker)


def test_the_registry_row_is_what_tells_the_azure_row_the_language():
    assert _azure("pt-BR").language == "pt-BR"


def test_the_sentence_is_the_catalogues_not_the_rows(caplog):
    """The same entry the Jira row uses (#203), which names no vendor so that both can."""
    from openfactory.product.voice import closed_not_delivered_note

    tracker = _azure("pt-BR")
    with caplog.at_level(logging.WARNING):
        tracker.close_ticket("1", "", delivered=False)

    assert _azure_said(tracker) == (
        "_" + closed_not_delivered_note(status="**Done**", language="pt-BR") + "_")
