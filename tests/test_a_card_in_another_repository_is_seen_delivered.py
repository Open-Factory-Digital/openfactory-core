"""A card the product filed in another of its repositories is seen delivered, so the requirement it
belongs to is announced (#492).

THE DELIVERED SET WAS ONE REPOSITORY'S. Since #485 a requirement's delivery loop names every card
its breakdown filed, qualified when the card lives in another repository of the product
(`acme/web#1`, C-18). What is delivered is read from the board — `events._delivered_now`, and the
weekly sweep's `_closed_issue_numbers` — and the board is `list_tickets` of the tracker's own
repository. Measured on the #485 branch (ba1c3bf), on the product below:

    the forge says                          what the requester heard
    ─────────────────────────────────────   ────────────────────────────────────────────────────
    api#1 closed, web#1 closed              nothing — `acme/web#1` is in no delivered set, ever

NOW EACH QUALIFIED REF A WAITING DELIVERY NAMES IS ASKED OF THE TRACKER BY ITSELF
(`events._delivered_elsewhere` → `board.read_cards` → `GitHubIssuesTracker.ticket_summary`), and
only for a loop whose every other card is already delivered. A read that fails is not delivered,
said once, and never raised into the round.

WHAT IS DRIVEN HERE. A GitHub product of `acme/api` (the tracker's own) and `acme/web`, its loop
the promise a breakdown hands its cards' doors (`_track_requirement`), opened by the door's own
effect (`loops.owe`, #414), and `gh` faked at its one transport (`subprocess.run`) for BOTH reads:
the board's `gh issue list` of `acme/api`, and a card read by itself, `gh issue view` in
`acme/web`. Between them everything is the production path — a card's `delivered` through its door
→ `loops.announce_what_it_completes` → `_delivered_now` → `read_board` → `loops.announce` → the
per-ref read → `followup.delivered`; and the door's converge, the second chance where the weekly
sweep's catch-all was (`loops.announce` with the board's set, `Ports.deliver_what_remains`).
The one seam stood in for is the door (`events._tell`), which records what it was handed; and the
impediment reporter a board read pings (`module._tell_the_factory`), which is not this test's.
"""

from __future__ import annotations

import json
import logging
import subprocess

import pytest

from openfactory.lifecycle import loops
from openfactory.memory import store as loop_store
from openfactory.memory.ledger import ACCEPTANCE, CLOSED, DELIVERY, waiting
from openfactory.product import events
from tests.test_a_requirements_delivery_keys_on_the_trackers_refs import (
    ANA,
    ANAS,
    _memory,
    _the_door_delivers,
)

API, WEB = "acme/api", "acme/web"


class _Forge:
    """`gh` over two repositories: each issue's state as GitHub answers it (SHOUTING), every call
    it was asked, and a repository whose reads fail."""

    def __init__(self) -> None:
        self.issues: dict[tuple[str, str], tuple[str, str]] = {}
        self.calls: list[list[str]] = []
        self.down: set[str] = set()

    def has(self, repo: str, number: int, state: str = "OPEN", reason: str = "") -> None:
        self.issues[(repo, str(number))] = (state, reason)

    def _row(self, number: str, state: str, reason: str) -> dict:
        return {"number": int(number), "title": f"card {number}", "body": "", "state": state,
                "stateReason": reason, "labels": [], "assignees": [],
                "updatedAt": "2026-10-04T09:00:00Z"}

    def __call__(self, argv, **_kw):
        args = list(argv)[1:]
        self.calls.append(args)
        repo = args[args.index("--repo") + 1]
        if repo in self.down:
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="HTTP 502: Bad Gateway")
        if args[:2] == ["issue", "list"]:
            rows = [self._row(n, *s) for (r, n), s in self.issues.items() if r == repo]
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(rows), stderr="")
        if args[:2] == ["issue", "view"]:
            found = self.issues.get((repo, args[2]))
            if found is None:
                return subprocess.CompletedProcess(argv, 1, stdout="",
                                                   stderr="Could not resolve to an issue")
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(self._row(args[2],
                                                                                    *found)),
                                               stderr="")
        raise AssertionError(f"the tracker ran `gh {' '.join(args)}`, a call this forge never had")

    def asked_of(self, repo: str) -> list[list[str]]:
        return [c for c in self.calls if repo in c]


@pytest.fixture
def product(monkeypatch, tmp_path):
    """The product, its forge faked, the door recording, and requirement 7 waiting on `#1` in the
    tracker's own repository and `acme/web#1` — as the breakdown leaves it (#485)."""
    from openfactory.contracts.product import ProductConfig
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.product import board, module

    _memory(monkeypatch, tmp_path)
    forge = _Forge()
    forge.has(API, 1)
    forge.has(WEB, 1)
    monkeypatch.setattr(subprocess, "run", forge)
    monkeypatch.setattr(module, "_tell_the_factory", lambda *a, **k: None)
    project = Project(name="shop", repo_path=str(tmp_path), language="pt-BR",
                      tracker=ProviderRef(kind="github", repo=API),
                      product=ProductConfig(docs_repo="acme/acme-docs", admins=[ANA],
                                            agent_name="Nina"))
    _promised(project, 7, ["#1", f"{WEB}#1"])
    said: list[dict] = []
    monkeypatch.setattr(events, "_tell", lambda project, **kw: said.append(kw) or True)
    board.forget_board()
    yield project, forge, said
    board.forget_board()


def _promised(project, requirement: int, landed: list[str]) -> None:
    """The promise a breakdown over `landed` hands each of its cards' doors, opened by the first
    (`loops.owe`, #414) — as `_open_delivery` builds it."""
    from types import SimpleNamespace

    from openfactory.contracts.refs import canonical_refs
    from openfactory.product.module import ProductModule

    cards = canonical_refs(landed)
    owed = ProductModule._track_requirement(SimpleNamespace(project=project), requirement, cards,
                                            conversation=ANAS, requester=ANA)
    for card in cards:
        loops.owe(project, card, owed)


def _deliveries(project) -> list:
    return [x for x in waiting(loop_store.read(project.name)) if x.kind == DELIVERY]


def _delivered(project, card: str) -> list:
    """`card` reached Done through its door — the rows its announcement wrote."""
    return _the_door_delivers(project, card)


def _converged(project, *, delivered: set[str]) -> list:
    """The door's second chance, with the board's set (`Ports.deliver_what_remains`)."""
    return loops.announce(project, delivered=delivered)[0]


def test_one_card_in_each_repository_is_announced_once_when_both_are_delivered_and_not_before(
        product):
    project, forge, said = product
    [loop] = _deliveries(project)
    assert loop.context["issues"] == f"1,{WEB}#1"

    # THE API'S CARD SHIPPED; THE WEB'S IS STILL OPEN — read by itself, and nothing is said
    forge.has(API, 1, "CLOSED", "COMPLETED")
    assert _delivered(project, "1") == []
    assert said == [] and _deliveries(project) == [loop]
    # the board is the tracker's own repository's list, read fresh — and the web card is on no list
    assert [c[:2] for c in forge.asked_of(API)] == [["issue", "list"]]
    assert forge.asked_of(WEB) == [["issue", "view", "1", "--repo", WEB, "--json",
                                    "number,title,body,state,stateReason,labels,assignees,"
                                    "updatedAt"]]

    # THE WEB'S CARD SHIPPED: its job ends, and the requirement is announced — to Ana, once
    forge.has(WEB, 1, "CLOSED", "COMPLETED")
    written = _delivered(project, f"{WEB}#1")

    assert [t["conversation"] for t in said] == [ANAS]
    assert "requisito 7" in said[0]["text"]
    assert [(x.kind, x.subject, x.state) for x in written if x.kind == DELIVERY] == [
        (DELIVERY, "7", CLOSED)]
    assert [x.kind for x in written if x.kind == ACCEPTANCE] == [ACCEPTANCE]
    assert _deliveries(project) == []

    # …AND NEVER TWICE: the card's door again, and the door's converge (the weekly sweep's since
    # #414)
    assert _delivered(project, f"{WEB}#1") == []
    assert _converged(project, delivered={"1"}) == []
    assert len(said) == 1
    # THE OTHER REPOSITORY WAS NEVER LISTED — only the card the loop names was read
    assert not [c for c in forge.calls if c[:2] == ["issue", "list"] and WEB in c]


def test_the_web_card_delivered_first_is_not_the_requirement_delivered(product):
    """The other order: the card in the other repository ships while the tracker's own is open."""
    project, forge, said = product
    forge.has(WEB, 1, "CLOSED", "COMPLETED")

    assert _delivered(project, f"{WEB}#1") == []
    assert said == [] and len(_deliveries(project)) == 1
    # A LOOP WITH WORK STILL OPEN IN ITS OWN REPOSITORY CANNOT CLOSE, so the other one is not read
    assert forge.asked_of(WEB) == []


def test_the_sweep_sees_a_card_in_another_repository_delivered_too(product):
    """The second chance's own call (the door's converge → `loops.announce` with the board's set,
    where the weekly sweep's `deliver` was until #414): an effect that failed, a delivery a
    cancellation narrowed — it announces it the same way."""
    project, forge, said = product
    forge.has(WEB, 1, "CLOSED", "COMPLETED")

    written = _converged(project, delivered={"1"})

    assert [t["conversation"] for t in said] == [ANAS]
    assert [(x.subject, x.state) for x in written if x.kind == DELIVERY] == [("7", CLOSED)]


def test_a_card_in_another_repository_closed_as_NOT_PLANNED_is_not_delivered(product):
    project, forge, said = product
    forge.has(API, 1, "CLOSED", "COMPLETED")
    forge.has(WEB, 1, "CLOSED", "NOT_PLANNED")

    assert _delivered(project, f"{WEB}#1") == []
    assert said == [] and len(_deliveries(project)) == 1


def test_a_failed_read_of_the_other_repository_announces_nothing_and_raises_nothing(
        product, caplog):
    project, forge, said = product
    forge.has(API, 1, "CLOSED", "COMPLETED")
    forge.has(WEB, 1, "CLOSED", "COMPLETED")
    forge.down.add(WEB)

    with caplog.at_level(logging.WARNING, logger="openfactory.product.events"):
        assert _delivered(project, f"{WEB}#1") == []
        assert _converged(project, delivered={"1"}) == []

    assert said == [] and len(_deliveries(project)) == 1
    unread = [r.getMessage() for r in caplog.records if "OPENFACTORY_DELIVERY_UNREAD" in
              r.getMessage()]
    # ONCE PER TELLING, naming the card — two tellings, two lines, never a traceback
    assert len(unread) == 2 and all(f"refs={WEB}#1 " in m for m in unread), unread
    assert not [r for r in caplog.records if r.exc_info]

    # THE FORGE ANSWERS AGAIN: the next telling asks again, and says it
    forge.down.clear()
    assert [x.subject for x in _converged(project, delivered={"1"})
            if x.kind == DELIVERY] == ["7"]
    assert [t["conversation"] for t in said] == [ANAS]


def test_a_card_the_other_repository_does_not_have_is_not_delivered(product):
    """Deleted, transferred, or never there: `gh` says it cannot resolve it — unreadable, never
    closed."""
    project, forge, said = product
    forge.has(API, 1, "CLOSED", "COMPLETED")
    del forge.issues[(WEB, "1")]

    assert _converged(project, delivered={"1"}) == []
    assert said == []


def test_a_tracker_that_raises_reading_the_card_is_not_delivered(product, monkeypatch):
    """The read side's belt: a row that raises instead of answering `None` is read as unreadable
    by `tracker.base.summary_of`, and the round goes on."""
    from openfactory.adapters.tracker.github import GitHubIssuesTracker

    project, forge, said = product
    forge.has(API, 1, "CLOSED", "COMPLETED")
    forge.has(WEB, 1, "CLOSED", "COMPLETED")

    def boom(self, ref):
        raise RuntimeError("the `gh` CLI is not installed")

    monkeypatch.setattr(GitHubIssuesTracker, "ticket_summary", boom)
    assert _converged(project, delivered={"1"}) == []
    assert said == [] and len(_deliveries(project)) == 1


def test_a_requirement_whose_cards_are_all_in_another_repository_is_announced(
        product, monkeypatch, tmp_path):
    """Nothing of it on the tracker's own board — so the board's set says nothing about it at all,
    and is not what decides whether it is asked."""
    project, forge, said = product
    _promised(project, 9, [f"{WEB}#2", f"{WEB}#3"])
    forge.has(WEB, 2, "CLOSED", "COMPLETED")
    forge.has(WEB, 3, "OPEN")

    assert _delivered(project, f"{WEB}#2") == []
    forge.has(WEB, 3, "CLOSED", "COMPLETED")
    written = _delivered(project, f"{WEB}#3")

    assert [(x.subject, x.state) for x in written if x.kind == DELIVERY] == [("9", CLOSED)]
    assert len(said) == 1


def test_a_failure_anywhere_in_the_other_repositorys_read_never_reaches_the_round(
        product, monkeypatch):
    """The converge calls `loops.announce` bare: whatever goes wrong asking the other repository,
    the board's answer stands and the round goes on."""
    from openfactory.product import board

    project, forge, said = product
    forge.has(WEB, 1, "CLOSED", "COMPLETED")

    def boom(*_a, **_k):
        raise OSError("the deployment's credential store is unreadable")

    monkeypatch.setattr(board, "read_cards", boom)
    assert _converged(project, delivered={"1"}) == []
    assert said == [] and len(_deliveries(project)) == 1


# ── the read by ref, at the port and on the GitHub row ───────────────────────────────────────────

def test_a_row_with_no_read_by_ref_answers_unreadable_never_delivered():
    """`summary_of` off the port: a row without `ticket_summary`, a double that answers anything
    with a `MagicMock`, and a row that raises are all `None` — never an exception."""
    from unittest.mock import MagicMock

    from openfactory.adapters.tracker.base import summary_of

    class _Bare:
        pass

    class _Raises:
        def ticket_summary(self, ref):
            raise RuntimeError("the `gh` CLI is not installed")

    assert summary_of(_Bare(), "acme/web#1") is None
    assert summary_of(MagicMock(), "acme/web#1") is None
    assert summary_of(_Raises(), "acme/web#1") is None


def test_the_github_row_reads_a_card_in_the_repository_its_ref_names(monkeypatch):
    from openfactory.adapters.tracker.github import GitHubIssuesTracker

    forge = _Forge()
    forge.has(API, 1, "OPEN")
    forge.has(WEB, 1, "CLOSED", "NOT_PLANNED")
    monkeypatch.setattr(subprocess, "run", forge)
    tracker = GitHubIssuesTracker(API)

    web = tracker.ticket_summary(f"#{WEB}#1")
    api = tracker.ticket_summary("#1")

    assert (web.ref, web.state, web.state_reason) == (f"{WEB}#1", "closed", "not_planned")
    assert (api.ref, api.state, api.state_reason) == ("1", "open", "")
    assert [c[2:5] for c in forge.calls] == [["1", "--repo", WEB], ["1", "--repo", API]]
    forge.down.add(WEB)
    assert tracker.ticket_summary(f"{WEB}#1") is None


def test_a_card_read_by_its_ref_keeps_the_ref_it_was_asked_by():
    """A row that answers a bare ref for a card of another repository must not make `acme/web#1`
    read as the tracker's own `#1` — the collision #485 took out of the loop."""
    from openfactory.adapters.tracker.base import TicketSummary
    from openfactory.product.board import read_cards

    class _Bare:
        def ticket_summary(self, ref):
            return TicketSummary(ref="1", state="closed", state_reason="completed")

    read, unread = read_cards(None, [f"#{WEB}#1"], tracker=_Bare())
    assert ([t.number for t in read], unread) == ([f"{WEB}#1"], [])
