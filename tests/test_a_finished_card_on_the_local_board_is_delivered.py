"""A card the factory finished on the local board is delivered, and its requester is told (#500).

THE JOB WRITES DONE THROUGH `set_state`, AND ON THIS ROW THAT ONLY MOVED A COLUMN. Every job that
finishes ends at `settle_ticket(DONE)` (`JobWorkflow._finish_at_the_merge`, the promotion tail's
last stage) and then at `record_outcome`, which asks `events.card_finished` whether a delivery is
complete. The board decides that (`triage.delivered_numbers`), and `Ticket.delivered` is "closed,
and not as `not_planned`". `LocalTracker.set_state` moved `column_key` to `done` and left the card
`open`, so the card the factory had just finished was never delivered: the requester heard nothing
from the job's exit, and nothing from the sweep's catch-all either — both read the same board.

THE HOSTED ROWS CLOSE THERE. GitHub closes the issue as completed on DONE (#180); Jira and Azure
DevOps close by moving the card, because a status in the done category IS closed, and a card moved
out of it is open again. The local row now does what they do, with the word `close_ticket` writes.

WHY NOTHING HERE STANDS IN FOR `_delivered_now`. The case that announces a delivery in
`test_events_and_the_agenda.py` replaces it with `{"500"}`, and the plain card's case in
`test_a_plain_card_reaches_the_person_who_asked.py` closes the card with `close_ticket` — a write no
job makes. Both are green on a board where no finished card was ever delivered. Here the card is
settled by the workflow's own activity over the real local row, the job's one exit asks, and the
real board read answers. The door to the conversation is the one seam faked: it leaves the machine,
and what reached it is recorded.
"""

from __future__ import annotations

import asyncio

import pytest
from temporalio.testing import ActivityEnvironment

from openfactory.contracts import JobState
from openfactory.memory import store as loop_store
from openfactory.memory.ledger import DELIVERY, waiting
from openfactory.product import events, followup
from openfactory.runtime.temporal import activities as acts
from openfactory.runtime.temporal.io import HoldSyncInput

LANG, AGENT, ROOM = "pt-BR", "Nina", "acme"
ANA = "ana-requester-500"
ANAS = f"person:{ANA}"
TITLE = "Exportar o relatório mensal em CSV"


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A registered project on the local row, its board created, its product role on, and its
    memory on SQLite — the ledger the delivery loop lives in."""
    from openfactory.adapters.board_setup.local import LocalBoardSetup
    from openfactory.contracts.product import ProductConfig
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.registry import ProjectRegistry

    monkeypatch.setenv("OPENFACTORY_BOARD_DB", str(tmp_path / "board.db"))
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "sqlite")
    monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(tmp_path / "metrics.db"))
    registry = ProjectRegistry()
    registry.add(Project(name=ROOM, repo_path=str(tmp_path), language=LANG,
                         tracker=ProviderRef(kind="local", repo=ROOM, options={}),
                         product=ProductConfig(docs_repo="acme/acme-docs", admins=[ANA],
                                               agent_name=AGENT)))
    found = registry.get(ROOM)
    LocalBoardSetup().create(project=found, owner="", title=ROOM, token=None)
    return found


@pytest.fixture
def tracker(project):
    from openfactory.adapters.tracker.registry import build_tracker

    return build_tracker(project)


@pytest.fixture
def told(project, monkeypatch) -> list[dict]:
    """What reached the door to the conversation."""
    said: list[dict] = []
    monkeypatch.setattr(events, "_tell", lambda project, **kw: said.append(kw) or True)
    return said


def _asked_for(project, tracker) -> str:
    """A card Ana asked for in her conversation, on the board with its delivery loop open — the
    loop opened by the product role's own helper, as `file_ticket` opens it (#481)."""
    from openfactory.product.module import _follow_card

    ref = tracker.create_ticket(title=TITLE, body="## Objective\n\nExport it\n",
                                author=ANA, requester=ANA)
    card = ref.lstrip("#")
    _follow_card(project, f"cartao-{card}", card, {"ticket": "1", "title": TITLE},
                 conversation=ANAS, requester=ANA)
    assert [x.subject for x in _deliveries(project)] == [f"cartao-{card}"]
    return card


def _deliveries(project) -> list:
    return [x for x in waiting(loop_store.read(project.name)) if x.kind == DELIVERY]


def _activity(fn, card: str, state: JobState, note: str = ""):
    return asyncio.run(ActivityEnvironment().run(
        fn, HoldSyncInput(project=ROOM, issue=card, state=state.value, note=note)))


def _the_job_finishes(project, tracker, card: str) -> None:
    """What a card's job does at its end: the box leaves the card in review with its pull request
    open (`JobRunner._set_state`), `_finish_at_the_merge` settles it Done through the workflow's
    own activity, and the job leaves by its one exit."""
    assert tracker.set_state(card, JobState.PR_OPEN) is True
    assert _record(project, card) == ("open", "", "in_review")
    assert _activity(acts.settle_ticket, card, JobState.DONE,
                     "Merged. Nothing follows the merge for this project.") == "done"
    assert _activity(acts.record_outcome, card, JobState.MERGED) == "merged"


def _record(project, card: str) -> tuple[str, str, str]:
    """`(state, closed_reason, column_key)` as the board's own table holds them."""
    from openfactory.adapters.board_db import connect

    with connect() as conn:
        row = conn.execute(
            "SELECT state, closed_reason, column_key FROM cards WHERE project = ? AND ref = ?",
            (project.name, int(card))).fetchone()
    return row["state"], row["closed_reason"] or "", row["column_key"]


def _delivered(project) -> set[str]:
    """What the board says was delivered — the real read both announcers make."""
    found = events._delivered_now(project)
    assert found is not None, "the board could not be read"
    return found


# ── 1. the job finishes the card, and its requester hears it ────────────────────────────────────

def test_a_card_the_factory_finished_is_announced_to_its_requester_ONCE(project, tracker, told):
    card = _asked_for(project, tracker)

    _the_job_finishes(project, tracker, card)

    assert [t["conversation"] for t in told] == [ANAS], told
    assert f"o #{card} ({TITLE}) já entrou no produto" in told[0]["text"], told[0]["text"]
    assert _deliveries(project) == [], "the delivery stays open after it was told"

    # THE CATCH-ALL READS THE SAME BOARD, AND FINDS IT TOLD: the sweep, and a job's exit again
    events.deliver(project, delivered=_delivered(project))
    _activity(acts.record_outcome, card, JobState.DONE)
    assert len(told) == 1, "the delivery was announced twice"


def test_the_sweep_alone_announces_it_when_the_exit_could_not(project, tracker, told,
                                                              monkeypatch):
    """The weekly catch-all is the other reader of the board: a job whose exit could not ask (a
    board that did not answer in time) is announced by the sweep — which also found nothing on
    this row before #500."""
    card = _asked_for(project, tracker)
    monkeypatch.setattr(events, "card_finished", lambda project, **kw: [])
    _the_job_finishes(project, tracker, card)
    assert told == []

    events.deliver(project, delivered=_delivered(project))

    assert [t["conversation"] for t in told] == [ANAS]


def test_the_finished_card_reads_as_the_hosted_rows_read_it(project, tracker):
    """Closed as delivered, in Done — what `close_ticket(delivered=True)` writes, so a card finished
    by its job and one a person closed from Done are one kind of card everywhere downstream."""
    card = _asked_for(project, tracker)

    _the_job_finishes(project, tracker, card)

    assert _record(project, card) == ("closed", "completed", "done")
    assert tracker.get_ticket(card).state == "closed"
    assert card in _delivered(project)
    [summary] = tracker.list_tickets(state="closed")
    assert (summary.ref, summary.state_reason) == (card, "completed")


def test_the_close_writes_no_comment_of_its_own(project, tracker):
    """The job's note is not written on this row (ADR-0055 D6: the door's comment is its own), and
    the close that `set_state` now makes adds none — nothing on the card is said twice."""
    card = _asked_for(project, tracker)

    _the_job_finishes(project, tracker, card)
    _activity(acts.settle_ticket, card, JobState.DONE, "settled again by a replay")

    assert tracker.comments(card) == []
    assert _record(project, card) == ("closed", "completed", "done")


# ── 2. leaving Done, and a card that was never delivered ────────────────────────────────────────

def test_a_card_moved_back_out_of_Done_is_open_work_again_and_NOT_delivered(project, tracker):
    """Leaving Done reopens, as on Jira and Azure DevOps, where the status IS the state: a card the
    factory queues again is on the board and in the pickup column, not a closed card in a column
    nobody reads."""
    from openfactory.adapters.board import build_board

    card = _asked_for(project, tracker)
    _the_job_finishes(project, tracker, card)

    assert tracker.set_state(card, JobState.TODO) is True

    assert _record(project, card) == ("open", "", "todo")
    assert card not in _delivered(project)
    assert build_board(project).items_in_status("TO-DO") == [card]


def test_a_card_the_door_reopens_is_not_delivered(project, tracker, told):
    """A person's way back: the door's reopen. It was refused on every card the factory finished
    here — the card was open, and a reopen is of a closed card only."""
    from openfactory.lifecycle.card import transition

    card = _asked_for(project, tracker)
    _the_job_finishes(project, tracker, card)

    done = transition(project, card, "reopened", by="ana", why="it does not export the totals",
                      tracker=tracker)

    assert done.ok, done.refused
    assert _record(project, card)[:2] == ("open", "")
    assert card not in _delivered(project)


def test_a_card_closed_as_NOT_delivered_stays_not_delivered(project, tracker, told):
    """Done never turns a withdrawn card into shipped work, and a move never brings it back: the
    eleven duplicates that came back downstream as completed work are why the word exists."""
    card = _asked_for(project, tracker)
    tracker.close_ticket(card, "asked for by mistake", delivered=False)

    _activity(acts.settle_ticket, card, JobState.DONE)
    assert _record(project, card)[:2] == ("closed", "not_planned")
    tracker.set_state(card, JobState.TODO)
    assert _record(project, card)[:2] == ("closed", "not_planned")

    _activity(acts.record_outcome, card, JobState.DONE)
    assert card not in _delivered(project)
    assert told == []


def test_a_card_left_in_Done_is_closed_once(project, tracker):
    """One writer per close, GitHub's rule (`_close_as_delivered`): a card already closed as
    delivered is not closed again, and a card a person closed from Done keeps its own record."""
    card = _asked_for(project, tracker)
    tracker.close_ticket(card, "shipped last week", delivered=True)
    before = tracker.comments(card)

    _activity(acts.settle_ticket, card, JobState.DONE)

    assert _record(project, card) == ("closed", "completed", "done")
    assert tracker.comments(card) == before


def test_a_card_this_board_does_not_hold_is_not_reported_moved(project, tracker):
    """The row now reads the card before it writes; a card that is not there is still the
    `False` the port promises, never a move that happened to nothing."""
    assert tracker.set_state("41", JobState.DONE) is False
    assert tracker.set_state("41", JobState.TODO) is False


def test_the_announcement_is_the_delivery_the_sweep_says(project, tracker, told):
    """The sentence and the question are the delivery's own (`followup`), nothing composed here."""
    card = _asked_for(project, tracker)
    [loop] = _deliveries(project)

    _the_job_finishes(project, tracker, card)

    assert told[0]["text"] == (followup.delivered_text(loop, agent_name=AGENT, language=LANG)
                               + followup.acceptance_question(loop, agent_name=AGENT,
                                                              language=LANG))
