"""On Jira, a backlog order stated in the conversation is staged, confirmed and written (#515).

THE ORDER MARKER READ DIGITS ONLY. The role ends a reply that gave the backlog an order with
`[[ORDEM: …]]`, and `role._ORDER_RE` accepted `[#\\d]` and nothing else — so on Jira, where no card
has a number, `[[ORDEM: DAR-11, DAR-9]]` matched nothing: no order was read, nothing was staged,
the reorder never reached `ProductModule.reorder`, and the marker was left to the safety net. The
verb itself had worked on Jira since #45 and reached the watched board since #511 — whose own test
had to drive GitHub Projects, because a Jira order could not be said.

NOW THE MARKER READS THE CARDS AS THE TRACKER SPELLS THEM, through `contracts.refs`
(`REF_AS_WRITTEN`, `refs_written`): `#12`, `CONT-412`, `acme/web#1`, in the order written, each once.

WHAT IS DRIVEN HERE. The conversation itself, `engine.turn` through `chat_turn`: the role's reading
is the real one — the model's text read by the role's own parser — and the verb behind the yes is
the product role's real pen over the Jira row, with the transport faked at `urllib.request.urlopen`
by a site that ranks as Jira does (`test_a_queue_on_jira_says_what_it_queued._Site`). The person
says the order, reads it back, says yes, and the site's backlog is in it.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import openfactory.product.channel as pc
from openfactory.contracts.refs import refs_written
from openfactory.product.role import _ORDER_RE
from openfactory.product.voice import reordered
from tests.test_a_queue_on_jira_says_what_it_queued import BACKLOG, QUEUE, _memory, _pen, _Site
from tests.the_chat_turn import chat_turn

ADMIN, KEY = "U1", "C0PROD"
SAID = "Fica assim: o DAR-11 primeiro, depois o DAR-9.\n[[ORDEM: DAR-11, DAR-9]]"


@pytest.fixture(autouse=True)
def _clean():
    pc._PENDING.clear()
    yield
    pc._PENDING.clear()


@pytest.fixture
def jira(monkeypatch, tmp_path):
    """A Jira project as the registry holds one, DAR-9, DAR-10 and DAR-11 in its Backlog, ranked in
    that order — and the pen holding the row's real tracker and board."""
    from openfactory.adapters.board import build_board
    from openfactory.adapters.tracker.registry import build_tracker
    from openfactory.contracts.product import ProductConfig
    from openfactory.contracts.project import Project, ProviderRef

    _memory(monkeypatch, tmp_path)
    site = _Site("DAR-9", "DAR-10", "DAR-11")
    monkeypatch.setattr("urllib.request.urlopen", site.urlopen)
    options = {"site": "https://acme-team.atlassian.net", "email": "alice@acme.ai",
               "status_map": json.dumps({"todo": QUEUE, "in_progress": "Em andamento",
                                         "done": "Concluído"})}
    project = Project(name="acme", repo_path=str(tmp_path), language="pt-BR",
                      tracker=ProviderRef(kind="jira", repo="DAR", options=options),
                      product=ProductConfig(docs_repo="acme/acme-docs", channel_id=KEY,
                                            admins=[ADMIN], agent_name="Nina"))
    tracker, board = build_tracker(project, token="t"), build_board(project, token="t")
    return project, site, board, _pen(project, tmp_path, tracker=tracker, board=board)


class _Conversation:
    """The role in the conversation: its answer is the REAL role's reading of what the model wrote
    (`ProductModule.answer` over a harness that answers `SAID`), and the verb behind the yes is the
    real pen's."""

    def __init__(self, reader, pen) -> None:
        self._reader = reader
        self.reorder = pen.reorder

    def settle_acceptance(self, text, **_):
        return None

    def close_decisions_answered(self, **_):
        return 0

    def confirmed(self, reply, *, proposal):
        return "neither"

    def context(self):
        return SimpleNamespace(available=True, reason="")

    def answer(self, question, **_):
        return self._reader.answer(question)

    def promote(self, numbers, *, actor, board=None):
        raise AssertionError(f"an order started work: {numbers}")


def test_an_order_of_keys_said_in_the_conversation_is_staged_confirmed_and_written(jira,
                                                                                   tmp_path):
    from tests.test_product_module import _module as _answering_module

    project, site, board, pen = jira
    talk = _Conversation(_answering_module(tmp_path, answer=SAID)[0], pen)

    asked = str(chat_turn(project, text="coloca nessa ordem: DAR-11, DAR-9", user=ADMIN,
                          thread=KEY, module=talk))

    staged = pc.find_waiting(KEY, KEY)[1]
    assert staged and staged["kind"] == "reorder", (staged, asked)
    assert staged["numbers"] == ["DAR-11", "DAR-9"], staged
    # READ BACK AS JIRA SPELLS THEM, the marker never reaching the person, and nothing written yet
    assert "DAR-11, DAR-9" in asked and "[[ORDEM" not in asked and "#DAR" not in asked, asked
    assert site.rank == ["DAR-9", "DAR-10", "DAR-11"], "the order was written before the yes"

    done = str(chat_turn(project, text="sim", user=ADMIN, thread=KEY, module=talk))

    assert board.items_in_status(BACKLOG) == ["DAR-11", "DAR-9", "DAR-10"]
    assert reordered(["DAR-11", "DAR-9"], language="pt-BR", agent_name="Nina") in done, done
    assert pc.find_waiting(KEY, KEY)[1] is None, "the order is still waiting after the yes"


# ── the marker ───────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("said", "order"), [
    ("[[ORDEM: DAR-7, DAR-3]]", ["DAR-7", "DAR-3"]),
    ("[[ORDEM: CONT-412; #12 acme/web#1]]", ["CONT-412", "12", "acme/web#1"]),
    ("[[ORDEM: 9, #3, 7, 3]]", ["9", "3", "7"]),
    ("[[ORDEM: #9,#3]]", ["9", "3"]),
])
def test_the_marker_reads_each_card_as_its_tracker_spells_it_in_the_order_given(said, order):
    found = _ORDER_RE.search(f"Fica assim.\n{said}")
    assert found is not None, said
    assert refs_written(found.group("numbers")) == order


@pytest.mark.parametrize("said", ["[[ORDEM]]", "[[ORDEM: ]]", "[[ORDEM: primeiro o 7]]",
                                  "[[ORDEM: DAR-7 e depois DAR-3]]"])
def test_prose_in_the_marker_is_not_an_order(said):
    """A list of cards and nothing else: what the brackets say in words is not read as an order —
    the net strips it, loudly, rather than staging a guess."""
    assert _ORDER_RE.search(said) is None, said


def test_the_marker_is_read_and_stripped_by_the_role_itself(tmp_path):
    from tests.test_product_module import _module as _answering_module

    module, _harness = _answering_module(tmp_path, answer=SAID)

    answer = module.answer("coloca nessa ordem: DAR-11, DAR-9")

    assert answer.is_reorder and answer.order == ["DAR-11", "DAR-9"], answer.order
    assert answer.text == "Fica assim: o DAR-11 primeiro, depois o DAR-9.", answer.text
