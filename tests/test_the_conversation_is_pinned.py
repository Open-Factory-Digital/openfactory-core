"""The product conversation as it behaves on `main`, pinned flow by flow — #266 slice 1.

WHY THIS FILE EXISTS. `product/channel.py::handle` is the only complete conversation the product
role has: it settles what the role asked last (a staged proposal, a delivery, an expired
proposal), reads the typed intents, answers, and turns what the model read into a gesture or a
draft staged for one yes. #266 slice 2 extracts a turn engine out of it and deletes the paths the
engine replaces, in the same pull request — two live paths is how the three doors drifted apart.
What is deleted has to be shown not lost, and that showing has to exist BEFORE the extraction,
written against the code being replaced. This file is it.

CHARACTERISATION, NOT DESIGN. Every test pins what the handler DOES today. Where that looks wrong
the test pins it anyway and its docstring says so, naming the slice of #266 that changes it on
purpose — so the day it flips, the red is a decision somebody reads, not a regression somebody
explains away. Three were found while writing this and no slice names them, so they are pinned
as found and flagged for a decision of their own: a typed "não" is recorded as an approval — in
the durable store AND in the requester's intake case, which moves to `confirmed` and stays there;
a refused "funcionou" on a release closes the release loop anyway; and an expired proposal's
durable row is never cleared, so the expiry notice owed to one late "sim" is said to every later
yes or no in that conversation.

FIXED SINCE, each by its own issue, and each flipped test says so in its docstring: a refused
"funcionou" on a release leaves the release question open for somebody who may answer it (#273).

THE HARNESS IS TRANSPORT-NEUTRAL, and it was the only thing slice 2 had to touch:

  - `_Conversation.say` is the ONE place a message enters. Since #266 slice 2 it hands the TURN
    ENGINE (`product/engine.py::turn`) the neutral `Message` any transport builds — the text, who
    said it, the conversation it belongs to, where it came from (`source`) and what a click
    already verified (`fingerprint`) — and renders the `Reply`s that come back through the chat
    adapter's own renderer (`channel.deliver`), recording the two callbacks a chat surface
    supplies (`notify`, the receipt; `confirm`, the buttons) instead of rendering them. Written
    against `channel.handle` first and pointed at the engine after: every test below reads the
    same, which is what showed the extraction lost nothing.
  - Only what leaves the process is replaced: the model, the writes, the board. `_Module` answers
    from a script and records every verb it is asked for, so an assertion is about the act (which
    verb, with what) and never about a sentence the double made up. The verbs that keep the
    ledger — `settle_acceptance`, `record_decisions`, `close_decisions_answered`, and the
    acceptance judge's own ledger read — are `ProductModule`'s own, run against the ledger as a
    list: the seam `test_decision_loop` and `test_acceptance_loop` already use. Only the model
    call under the judge (`_role().judge_acceptance`) is scripted, so a turn that costs no model
    call records none.
  - The transcript and the durable staging mirror (`memory.messages`) land in one in-memory
    telemetry table, patched at the two seams production resolves — the sink door
    (`tests/the_sink_door.py`) and the query — so a turn's record is read back, not assumed.
  - A sentence the voice composes is compared with its composer (`product/voice.py`,
    `product/followup.py`), not with a copy of its wording: what is pinned is which sentence the
    conversation says and how the pieces are put together, while the wording stays the voice's.
    The few the handler writes itself — the admins' note under a staged proposal, the release,
    the refusals the intents word in place, the breakdown's count — are compared with their text.

WHICH CONVERSATION A MESSAGE BELONGS TO IS THE TRANSPORT'S, NOT THIS FILE'S. `conversation_key`
reads a Slack event's shape (`thread_ts`), which #266 §2 moves to the transport; its contract —
a bare message belongs to the room, a reply to its thread — is pinned where the listener's is,
`tests/test_transcript_memory.py::test_a_bare_message_keys_to_the_channel_not_to_itself`, and the
flows here take the key as given (`thread=`).

Each flow has at least one row in `tools/mutations/266_the_conversation_is_pinned.py` that cuts
the line it depends on; 151 rows, every one red against this file (2026-09-24, after #273).
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

import openfactory.memory.store as loop_store
from openfactory.contracts.product import ProductConfig
from openfactory.contracts.project import Project
from openfactory.memory import messages
from openfactory.memory.ledger import ACCEPTANCE, DECISION, DELIVERY, fold, open_loop, waiting
from openfactory.memory.transcript import TRANSCRIPT_KIND
from openfactory.product import case as intake
from openfactory.product import channel as pc
from openfactory.product import engine, followup, staging, voice
from openfactory.product.authoring import WriteResult
from openfactory.product.config import ProductLink
from openfactory.product.corpus import ACCEPTED, DROPPED, SUPERSEDED, Corpus, Requirement
from openfactory.product.loader import ProductContext
from openfactory.product.module import ProductModule, _not_a_promise, unauthorized_message
from openfactory.product.queue import Proposed, QueueProposal, Readiness
from openfactory.product.role import ProductAnswer, RequirementDraft
from openfactory.product.triage import TriageReport
from tests.the_sink_door import SINK_DOOR

#: The product room. A bare message's conversation IS the room (`conversation_key`), which is how
#: a 1:1 client channel is actually used.
ROOM = "C0PROD"
#: A real thread inside that room — the shape a threaded reply carries.
THREAD = "1726000000.000100"
ADMIN, CLIENT, OTHER = "U0ADMIN", "U0CLIENT", "U0OTHER"
LANG, AGENT, PROJECT = "pt-BR", "Nina", "books"


def _project() -> Project:
    return Project(name=PROJECT, repo_path="/t", language=LANG, channel_id="C0OPS",
                   product=ProductConfig(docs_repo="a/b", channel_id=ROOM, admins=[ADMIN],
                                         agent_name=AGENT))


def _req(number: int, title: str, **kw) -> Requirement:
    return Requirement(number=number, slug=f"r{number}", title=title,
                       path=f"requirements/{number:04d}-r{number}.md", **kw)


#: The base every flow that does not name a requirement reads: one text, still a proposal.
PRO_LABORE = _req(4, "Pró-labore")

#: One requirement in each state a gesture that NAMES one can meet — the corpus the accept, drop,
#: decision and align rows are read against.
BASE = [
    PRO_LABORE,                                                       # proposed
    _req(5, "Extrato conciliado", status=ACCEPTED),                   # a promise
    _req(6, "Relatório antigo", status=DROPPED),                      # off the table
    _req(7, "Fechamento velho", status=SUPERSEDED, superseded_by=5),  # replaced by a promise
    _req(8, "Rascunho antigo", status=SUPERSEDED, superseded_by=4),   # …by a proposal
    _req(9, "Órfão", status=SUPERSEDED, superseded_by=99),            # …by nothing readable
    _req(10, "Cancelado", status=SUPERSEDED, superseded_by=6),        # …by a dropped text
]


# ── the harness ─────────────────────────────────────────────────────────────────────────────────

class _Table:
    """The append-only telemetry table, in memory, behind the write AND the read.

    What `transcript.record` and the staging mirror (`messages.ask`/`answer`) write lands here, and
    what `transcript.recent` and `messages.pending`/`answer_of` read comes back out — so the
    conversation's memory and the panel's view of what is staged are the production code's own."""

    def __init__(self) -> None:
        self.rows: list[dict] = []

    def record(self, rec) -> bool:
        self.rows.append({"project": rec.project, "kind": rec.kind, "ticket": rec.ticket,
                          "role": rec.role, "ts": rec.ts, "extra": dict(rec.extra)})
        return True

    def of_kind(self, project, kind, limit=500, **_kw) -> list[dict]:
        rows = [r for r in self.rows if r["project"] == project and r["kind"] == kind]
        return sorted(rows, key=lambda r: str(r["ts"]))[-limit:]

    def turns(self, thread: str) -> list[tuple[str, str, str]]:
        """`(role, text, actor)` for every transcript turn recorded under `thread`, in order."""
        return [(r["role"], r["extra"]["text"], r["extra"]["actor"])
                for r in self.of_kind(PROJECT, TRANSCRIPT_KIND) if r["ticket"] == thread]


@pytest.fixture()
def table(monkeypatch) -> _Table:
    t = _Table()
    monkeypatch.setattr(SINK_DOOR, lambda *a, **k: t)
    monkeypatch.setattr("openfactory.observability.query.records_of_kind", t.of_kind)
    return t


@pytest.fixture()
def ledger(monkeypatch) -> list:
    """The loop ledger as a list, append-only like the real one."""
    rows: list = []
    monkeypatch.setattr(loop_store, "read", lambda project: list(rows))
    monkeypatch.setattr(loop_store, "write", lambda project, loops: rows.extend(loops))
    return rows


#: What the role says when the script has nothing more specific: a plain answer, no gesture.
PLAIN = ProductAnswer(ok=True, text="Hoje o extrato conciliado não muda — é o requisito 4.")
#: What the module composes when asked to introduce itself; the handler only passes it on.
INTRODUCED = "Nina: oi — eu cuido do produto de vocês. Hoje a base tem 1 requisito."


class _Module:
    """The product module with what leaves the process replaced — the model, the writes, the
    board — and the ledger's own verbs left real.

    `replies` maps a phrase to the answer the role gives any message containing it; anything else
    gets `PLAIN`. Every verb the conversation reaches is recorded in `calls`, in order. NOT a
    subclass: a verb this double does not declare raises, the handler answers "algo quebrou", and
    the test says so — rather than a real `ProductModule` method quietly reaching a forge."""

    def __init__(self, project, *, available: bool = True, replies: dict | None = None,
                 drafted: ProductAnswer | None = None, verdict: str = "neither",
                 acceptance: str = "neither", merged: bool = False, cards: tuple = (),
                 requirements: list | None = None, queue: tuple = ("12",)) -> None:
        self.project = project
        self.calls: list[tuple[str, dict]] = []
        self.replies = replies or {}
        self.drafted = drafted
        #: what the judge says of a reply to a PROPOSAL the word list cannot read (`confirmed`)
        self.verdict = verdict
        #: what the model says of a reply to "did it work?" the word list cannot read
        self.acceptance = acceptance
        #: whether a confirmed draft lands in the base (ADR-0047's first yes opens its cards)
        self.merged = merged
        #: the official cards `open_cards_for` opens for a draft that landed
        self.cards = list(cards)
        #: what `propose_queue` proposes to start
        self.queue = list(queue)
        self._board_tickets: list = []
        # an unreadable base carries an EMPTY corpus, exactly as `ProductContext` does in
        # production — which is what `_named_requirement` exists to tell from "no such number"
        reqs = list(requirements if requirements is not None else [PRO_LABORE])
        self._ctx = ProductContext(
            link=ProductLink(active=available, docs_repo="a/b",
                             reason="" if available else "o repositório a/b não respondeu"),
            corpus=Corpus(requirements=reqs) if available else Corpus())

    def _record(self, verb: str, **kw) -> None:
        self.calls.append((verb, kw))

    def verbs(self) -> list[str]:
        return [verb for verb, _ in self.calls]

    def asked(self, verb: str) -> list[dict]:
        return [kw for v, kw in self.calls if v == verb]

    # ── the ledger: ProductModule's own verbs, recorded on the way in ───────────────────────────
    def settle_acceptance(self, text):
        self._record("settle_acceptance", text=text)
        return ProductModule.settle_acceptance(self, text)

    def _judge_acceptance(self, text):
        # the module's own: it reads the ledger FIRST and asks the model only with a delivery open
        return ProductModule._judge_acceptance(self, text)

    def record_decisions(self, labels, *, channel=""):
        self._record("record_decisions", labels=list(labels), channel=channel)
        return ProductModule.record_decisions(self, labels, channel=channel)

    def close_decisions_answered(self, *, channel=""):
        self._record("close_decisions_answered", channel=channel)
        return ProductModule.close_decisions_answered(self, channel=channel)

    # ── the model ────────────────────────────────────────────────────────────────────────────────
    def context(self, **_kw):
        return self._ctx

    def _workspace(self):
        return None, None

    def _role(self):
        return SimpleNamespace(judge_acceptance=self._judged)

    def _judged(self, *, sandbox, workspace, reply, delivered):
        self._record("judge_acceptance", reply=reply, delivered=delivered)
        return self.acceptance

    def confirmed(self, reply, *, proposal):
        self._record("confirmed", reply=reply, proposal=proposal)
        return self.verdict

    def answer(self, question, *, context="", conversation="", pending="", intake=None):
        self._record("answer", question=question, conversation=conversation, pending=pending,
                     intake=intake)
        for phrase, said in self.replies.items():
            if phrase in question:
                return said
        return PLAIN

    def draft(self, request, *, asked_by=""):
        self._record("draft", request=request, asked_by=asked_by)
        return self.drafted or ProductAnswer(ok=False, error="nada testável")

    def introduce(self, **_kw):
        self._record("introduce")
        return INTRODUCED

    # ── the writes: recorded, never performed ───────────────────────────────────────────────────
    def propose(self, answer, *, actor, asked_by="", date="", source=""):
        self._record("propose", answer=answer, actor=actor, asked_by=asked_by, date=date,
                     source=source)
        return WriteResult(ok=True, url="https://forge.example/pull/5", number=5,
                           merged=self.merged)

    def open_cards_for(self, number, *, actor, **_kw):
        self._record("open_cards_for", number=number, actor=actor)
        return [WriteResult(ok=True, ref=c) for c in self.cards]

    def stamp_acceptance(self, number, cards, *, actor, requester="", where="", **_kw):
        self._record("stamp_acceptance", number=number, cards=list(cards), actor=actor,
                     requester=requester, where=where)
        return [WriteResult(ok=True, ref=c) for c in cards]

    def file_defect(self, *, restated, reported_by, violates, severity="", source=""):
        self._record("file_defect", restated=restated, reported_by=reported_by,
                     violates=violates, severity=severity, source=source)
        return WriteResult(ok=True, ref="#88")

    def file_ticket(self, *, title, described, reported_by, source=""):
        self._record("file_ticket", title=title, described=described, reported_by=reported_by,
                     source=source)
        return WriteResult(ok=True, ref="#89", url="https://board.example/89")

    def record_decision(self, number, *, decision, actor, where=""):
        self._record("record_decision", number=number, decision=decision, actor=actor,
                     where=where)
        return WriteResult(ok=True)

    def note_fact(self, *, term, body, said_by, where=""):
        self._record("note_fact", term=term, body=body, said_by=said_by, where=where)
        return WriteResult(ok=True, ref="domain/fechamento.md")

    def reorder(self, numbers, *, actor, board=None):
        self._record("reorder", numbers=list(numbers), actor=actor)
        return [WriteResult(ok=True, ref=f"#{n}") for n in numbers]

    def promote(self, numbers, *, actor, board=None):
        self._record("promote", numbers=list(numbers), actor=actor)
        return [WriteResult(ok=True, ref=f"#{n}") for n in numbers]

    def accept(self, number, *, actor):
        self._record("accept", number=number, actor=actor)
        return WriteResult(ok=True)

    def drop(self, number, *, actor, reason=""):
        self._record("drop", number=number, actor=actor, reason=reason)
        return WriteResult(ok=True)

    def close_card(self, number, *, actor, in_favour_of=None, reason=""):
        self._record("close_card", number=number, actor=actor, in_favour_of=in_favour_of,
                     reason=reason)
        return WriteResult(ok=True)

    def correct_card(self, number, *, actor, text="", title=""):
        self._record("correct_card", number=number, actor=actor, text=text, title=title)
        return WriteResult(ok=True)

    def align_card(self, number, *, requirement, actor):
        self._record("align_card", number=number, requirement=requirement, actor=actor)
        return WriteResult(ok=True)

    def break_down(self, number, *, actor, asked_for, board=None):
        self._record("break_down", number=number, actor=actor, asked_for=asked_for)
        return [WriteResult(ok=True, ref="#40")]

    def refine(self, number, *, actor, tracker=None):
        self._record("refine", number=number, actor=actor)
        return WriteResult(ok=True)

    def baseline(self, **_kw):
        self._record("baseline")
        return WriteResult(ok=True, url="https://forge.example/pull/9")

    # ── the board reads ─────────────────────────────────────────────────────────────────────────
    def triage_board(self, **_kw):
        self._record("triage_board")
        return TriageReport(), ""

    def review_needs_action(self, **_kw):
        self._record("review_needs_action")
        return SimpleNamespace(decisions=[]), ""

    def propose_queue(self, **_kw):
        self._record("propose_queue")
        return Readiness(), QueueProposal(items=[Proposed(ticket=t) for t in self.queue]), ""


#: The verbs that change something outside the conversation. None of them may run on a turn that
#: was not a confirmed yes — except `break_down` and `refine`, the two that write on the match
#: alone (the declared exception in `product/intents.py`), and only for an approver.
WRITES = ("propose", "file_defect", "file_ticket", "record_decision", "note_fact", "reorder",
          "promote", "accept", "drop", "close_card", "correct_card", "align_card", "break_down",
          "refine", "baseline", "open_cards_for", "stamp_acceptance")


class _Conversation:
    """One product conversation, driven the way a transport drives it.

    `receipts` is every sentence handed to `notify`; `offers` is every `(text, token, approve,
    reject)` handed to `confirm`. `posts_buttons` is whether the transport managed to post them —
    False is a surface without interactive buttons, which gets the proposal back as prose."""

    def __init__(self, project, module, *, posts_buttons: bool = False) -> None:
        self.project, self.module = project, module
        self.posts_buttons = posts_buttons
        self.receipts: list[str] = []
        self.offers: list[tuple[str, str, str, str]] = []

    def _offer(self, text, token, approve, reject):
        self.offers.append((text, token, approve, reject))
        return self.posts_buttons

    def say(self, text: str, *, user: str, thread: str = ROOM, channel: str = ROOM,
            source: str = "", fingerprint: str = ""):
        """THE ONE PLACE THIS SUITE REACHES THE CONVERSATION: the turn engine, through the neutral
        `Message` (#266 slice 2) — the thread is the conversation, the room the one it lives in,
        the user the speaker. `source` is where the message came from (a permalink);
        `fingerprint` is what a click already verified. What comes back is rendered by the chat
        adapter's `deliver`, the one production renderer of a surface with two callbacks: the
        receipts to `notify`, a reply with options to `confirm`, and None when the buttons were
        posted."""
        replies = engine.turn(self.project,
                              engine.Message(project=self.project.name, conversation=thread,
                                             room=channel, speaker=user, text=text,
                                             source=source, fingerprint=fingerprint),
                              module=self.module)
        return pc.deliver(replies, notify=self.receipts.append, confirm=self._offer)


def _receipt(text: str) -> str:
    """The receipt a message seeds — what `notify` is handed before the slow part."""
    return voice.on_it(language=LANG, agent_name=AGENT, seed=text)


REQUEST = "preciso exportar o extrato em PDF"
DRAFTED = ProductAnswer(ok=True, draft=RequirementDraft(
    title="Exportar o extrato em PDF",
    must_be_true=["o extrato exportado mostra o mesmo saldo da tela"]))
ASKED_FOR = ProductAnswer(ok=True, text="Hoje não exportamos em PDF.", is_request=True)
#: What `staging.remember` puts in front of a proposal that displaced another in the same
#: conversation — the handler's own words, not the voice's.
DISPLACED = ("(Deixei de lado o que estava aguardando confirmação nesta conversa — se ainda "
             "quiser aquilo, me peça de novo depois.)\n\n")


def _asking(project, **kw) -> _Module:
    """A module whose role hears REQUEST as a request and drafts it."""
    return _Module(project, replies={"PDF": ASKED_FOR}, drafted=DRAFTED, **kw)


def _confirmation() -> str:
    return voice.confirmation_request(title=DRAFTED.draft.title,
                                      must_be_true=DRAFTED.draft.must_be_true, conflicts=[],
                                      language=LANG)


def _offered_draft() -> str:
    return f"{ASKED_FOR.text}\n\n" + _confirmation()


def _admins_note(what: str) -> str:
    """The line naming who can confirm, under a proposal somebody off the admin list made."""
    return f"\n\n(<@{ADMIN}>: {what} precisa da sua confirmação.)"


def _writes(module: _Module) -> list[str]:
    return [v for v in module.verbs() if v in WRITES]


# ── 1. a question ───────────────────────────────────────────────────────────────────────────────

def test_a_question_is_answered_with_the_role_s_words_and_both_turns_are_recorded(table,
                                                                                   ledger):
    """A plain question: the person's turn recorded on arrival with who said it, ONE receipt
    before the model, the role's text returned untouched, the agent's turn recorded after — and
    nothing staged, nothing written. The order of the verbs is the stage order: settle (the
    acceptance check, which reads the ledger before it asks the model — with no delivery open it
    costs no model call), then the decisions she asked for are closed, then the answer."""
    project = _project()
    module = _Module(project)
    talk = _Conversation(project, module)
    question = "o extrato conciliado pode ser editado?"

    reply = talk.say(question, user=CLIENT)

    assert reply == PLAIN.text
    assert table.turns(ROOM) == [("person", question, CLIENT), ("agent", PLAIN.text, "")]
    assert talk.receipts == [_receipt(question)]
    assert module.verbs() == ["settle_acceptance", "close_decisions_answered", "answer"]
    assert module.asked("answer") == [{"question": question, "conversation": "", "pending": "",
                                       "intake": None}]
    assert staging.pending_for(ROOM) is None
    assert talk.offers == []


# ── 2. a request becomes a draft, staged, with the confirmation question ───────────────────────

def test_a_request_is_drafted_staged_and_asked_about_in_one_message(table, ledger):
    """A request: the role's answer stays in front, the draft follows it in the client's words,
    and the draft is staged under the conversation with who asked, the channel and the number it
    would get. The transport is offered buttons carrying the proposal's token and the typed way
    out; this one declined, so the proposal comes back as prose. The receipt is still ONE — the
    draft's own call to it is the same receipt, already sent."""
    project = _project()
    module = _asking(project)
    talk = _Conversation(project, module)

    reply = talk.say(REQUEST, user=CLIENT)

    assert reply == _offered_draft()
    staged = staging.pending_for(ROOM)
    assert staged is not None and staged["answer"] is DRAFTED
    assert {k: staged[k] for k in ("kind", "asked_by", "date", "source", "channel", "number")} \
        == {"kind": "draft", "asked_by": f"<@{CLIENT}>", "date": "", "source": "",
            "channel": ROOM, "number": 5}
    assert module.asked("draft") == [{"request": REQUEST, "asked_by": f"<@{CLIENT}>"}]
    token = staging.proposal_token(ROOM, staged)
    approve, reject = voice.confirm_labels(language=LANG)
    assert talk.offers == [(f"{reply}\n\n{voice.or_just_reply(language=LANG)}", token,
                            approve, reject)]
    assert talk.receipts == [_receipt(REQUEST)]
    assert table.turns(ROOM)[-1] == ("agent", reply, "")
    # the durable mirror: another process (the panel) can find it by the same token
    assert [p.token for p in messages.pending(PROJECT)] == [token]
    assert not _writes(module)


def test_a_transport_that_posted_the_buttons_is_told_to_say_nothing_more(table, ledger):
    """`Posted`: when the transport posted the proposal with its buttons, the handler returns
    None so the text is not shown twice — and the agent's turn is recorded all the same, because
    her memory must hold the proposal she made however it reached the person."""
    project = _project()
    talk = _Conversation(project, _asking(project), posts_buttons=True)

    reply = talk.say(REQUEST, user=CLIENT)

    assert reply is None
    assert len(talk.offers) == 1
    assert table.turns(ROOM)[-1] == ("agent", _offered_draft(), "")
    assert staging.pending_for(ROOM) is not None


def test_a_request_the_role_could_not_draft_is_answered_with_its_words_alone(table, ledger):
    """The role heard a request and the draft came back with nothing testable: nothing is staged
    and the person gets the role's answer — never silence. `offer_draft` returns None for "nothing
    to confirm", and None out of the handler would be a quiet nothing."""
    project = _project()
    module = _Module(project, replies={"PDF": ASKED_FOR}, drafted=None)
    talk = _Conversation(project, module)

    reply = talk.say(REQUEST, user=CLIENT)

    assert reply == ASKED_FOR.text
    assert len(module.asked("draft")) == 1
    assert staging.pending_for(ROOM) is None
    assert talk.offers == []


# ── 3. a typed yes confirms the staged draft, once ──────────────────────────────────────────────

def test_the_requester_s_yes_writes_the_draft_exactly_once(table, ledger):
    """A typed "sim" from the person who asked — an admin here — performs the draft staged in
    this conversation: `propose` runs once with that person as the actor and the requester as
    provenance, the reply is the written-up sentence for what the write returned, the model is not
    consulted, and the proposal is gone from the stage and recorded as approved in the durable
    store. A second "sim" finds nothing to confirm and writes nothing."""
    project = _project()
    module = _asking(project)
    talk = _Conversation(project, module)
    talk.say(REQUEST, user=ADMIN)
    staged = staging.pending_for(ROOM)
    token = staging.proposal_token(ROOM, staged)

    reply = talk.say("sim", user=ADMIN)

    assert reply == voice.written_up(title=DRAFTED.draft.title, url="https://forge.example/pull/5",
                                     number=5, merged=False, language=LANG)
    [proposed] = module.asked("propose")
    assert proposed == {"answer": DRAFTED, "actor": ADMIN, "asked_by": f"<@{ADMIN}>", "date": "",
                        "source": ""}
    assert len(module.asked("answer")) == 1, "the yes went to the model"
    assert "confirmed" not in module.verbs(), "a word-list yes was sent to the judge"
    assert talk.receipts == [_receipt(REQUEST), _receipt("sim")], "one receipt per message"
    assert staging.pending_for(ROOM, project=project) is None
    decided = messages.answer_of(PROJECT, token)
    assert decided is not None and (decided.answer, decided.by) == ("approve", ADMIN)

    talk.say("sim", user=ADMIN)

    assert len(module.asked("propose")) == 1, "a second yes wrote the draft again"


def test_a_reply_the_word_list_cannot_read_is_judged_and_an_approval_writes(table, ledger):
    """A yes in a sentence of its own: neither word list reads it, so the judge is asked about
    it with the staged proposal's summary, and its "approve" performs exactly what a bare "sim"
    would have — the same write, the same sentence, the same durable approval and one receipt."""
    project = _project()
    module = _asking(project, verdict="approve")
    talk = _Conversation(project, module)
    talk.say(REQUEST, user=ADMIN)
    staged = staging.pending_for(ROOM)
    summary = staging._proposal_summary(staged)
    token = staging.proposal_token(ROOM, staged)
    said = "manda ver com esse título mesmo"

    reply = talk.say(said, user=ADMIN)

    assert module.asked("confirmed") == [{"reply": said, "proposal": summary}]
    assert [p["actor"] for p in module.asked("propose")] == [ADMIN]
    assert reply == voice.written_up(title=DRAFTED.draft.title, url="https://forge.example/pull/5",
                                     number=5, merged=False, language=LANG)
    decided = messages.answer_of(PROJECT, token)
    assert decided is not None and (decided.answer, decided.by) == ("approve", ADMIN)
    assert talk.receipts == [_receipt(REQUEST), _receipt(said)]


def test_a_reply_judged_as_a_rejection_destroys_the_draft_and_reaches_the_model_WHOLE(table,
                                                                                      ledger):
    """A conditional yes is a rejection of what is staged AND the most informative message of the
    exchange: the proposal is destroyed, and the model receives the person's own sentence — never
    a bare "não" put in its place — with nothing left pending in its prompt."""
    project = _project()
    module = _asking(project, verdict="reject")
    talk = _Conversation(project, module)
    talk.say(REQUEST, user=CLIENT)
    correction = "pode mandar, mas troca o título para Extrato mensal"

    reply = talk.say(correction, user=CLIENT)

    assert reply == PLAIN.text
    assert module.asked("answer")[-1]["question"] == correction
    assert module.asked("answer")[-1]["pending"] == ""
    assert staging.pending_for(ROOM, project=project) is None
    assert not module.asked("propose")


def test_a_draft_that_landed_opens_its_card_and_stages_the_second_yes_on_it(table, ledger):
    """ADR-0047's two yeses. A draft whose write MERGED is in the base, so its official card is
    opened at once — in the approver's name, in Backlog — and the reply says so after the
    written-up sentence. The acceptance is staged as the next question under the SAME key, with
    the card and who asked. The second "sim" accepts the requirement and stamps the acceptance on
    that card in the requester's name; with a card to carry it, no breakdown runs."""
    project = _project()
    module = _asking(project, merged=True, cards=("#31",))
    talk = _Conversation(project, module)
    talk.say(REQUEST, user=CLIENT)

    first = talk.say("sim", user=ADMIN)

    assert first == voice.written_up(title=DRAFTED.draft.title, url="https://forge.example/pull/5",
                                     number=5, merged=True, language=LANG) + (
        "\n\n" + voice.cards_opened_awaiting(cards=["#31"], number=5, language=LANG))
    assert module.asked("open_cards_for") == [{"number": 5, "actor": ADMIN}]
    staged = staging.pending_for(ROOM)
    assert {k: staged[k] for k in ("kind", "number", "cards", "asked_by", "channel", "title")} \
        == {"kind": "accept", "number": 5, "cards": ["#31"], "asked_by": f"<@{CLIENT}>",
            "channel": ROOM, "title": DRAFTED.draft.title}
    assert not module.asked("accept")

    second = talk.say("sim", user=ADMIN)

    assert module.asked("accept") == [{"number": 5, "actor": ADMIN}]
    assert module.asked("stamp_acceptance") == [{
        "number": 5, "cards": ["#31"], "actor": ADMIN, "requester": CLIENT,
        "where": "conversa com o time de produto"}]
    assert second == voice.accepted(number=5, language=LANG, agent_name=AGENT) + (
        "\n\n" + voice.acceptance_stamped(cards=["#31"], language=LANG))
    assert not module.asked("break_down")
    assert staging.pending_for(ROOM) is None


# ── 4. a typed no rejects it ────────────────────────────────────────────────────────────────────

def test_the_requester_s_no_destroys_the_draft_and_is_answered_as_the_correction(table, ledger):
    """The person whose request it is may take it back — no admin needed for that — and what they
    wrote is answered as the correction it usually is: the model receives it with the discarded
    proposal gone from the prompt. The judge is not asked: the word list already read a "não". An
    admin's later "sim" finds nothing and writes nothing.

    THIS "NÃO" IS RECORDED AS AN APPROVAL, TWICE, and that looks wrong. The rejection calls
    `consume` with `approved=True` (the approval's compare-and-swap, reused), and that flag drives
    two records: the panel's durable store writes the requester's typed no under the approvals'
    word, `approve`, and the intake case hook fires `confirmed` — so the requester's case goes
    `proposed → confirmed` with no note, where a rejection moves it to `dropped` ("rejected"), and
    it stays `confirmed` with nothing ever filed. No slice of #266 names it; pinned as found, both
    halves, so changing it is a decision taken on its own."""
    project = _project()
    module = _asking(project)
    talk = _Conversation(project, module)
    talk.say(REQUEST, user=CLIENT)
    token = staging.proposal_token(ROOM, staging.pending_for(ROOM))

    reply = talk.say("não, não é isso", user=CLIENT)

    assert reply == PLAIN.text
    last = module.asked("answer")[-1]
    assert (last["question"], last["pending"]) == ("não, não é isso", "")
    assert "confirmed" not in module.verbs(), "a typed no was sent to the judge"
    assert staging.pending_for(ROOM, project=project) is None
    decided = messages.answer_of(PROJECT, token)
    assert decided is not None and (decided.answer, decided.by) == ("approve", CLIENT)
    assert [(c.state, c.note, c.draft.get("kind")) for c in intake.open_cases(project, ROOM)] \
        == [("confirmed", "", "draft")]

    talk.say("sim", user=ADMIN)

    assert not module.asked("propose"), "a yes resurrected a draft its requester had refused"


def test_an_admin_may_reject_a_draft_somebody_else_asked_for(table, ledger):
    """Refusing is gated by "an admin, or the requester" — so an admin who did not ask for the
    draft may still throw it away, and what they wrote is answered as conversation."""
    project = _project()
    module = _asking(project)
    talk = _Conversation(project, module)
    talk.say(REQUEST, user=CLIENT)

    reply = talk.say("não", user=ADMIN)

    assert reply == PLAIN.text
    assert staging.pending_for(ROOM, project=project) is None
    assert module.asked("answer")[-1]["question"] == "não"


def test_a_no_from_someone_who_is_neither_the_requester_nor_an_admin_destroys_nothing(table,
                                                                                    ledger):
    """Refusing is an act too: a third party's "não" is answered with the refusal and the
    proposal stays staged for the people who may decide it."""
    project = _project()
    module = _asking(project)
    talk = _Conversation(project, module)
    talk.say(REQUEST, user=CLIENT)

    reply = talk.say("não", user=OTHER)

    assert reply == unauthorized_message(project)
    assert staging.pending_for(ROOM) is not None
    assert len(module.asked("answer")) == 1, "the refusal went on to the model"


# ── 5. a yes from someone who may not write ─────────────────────────────────────────────────────

def test_a_yes_from_someone_who_may_not_write_is_refused_out_loud_and_consumes_nothing(table,
                                                                                    ledger):
    """Neither the requester nor an admin: the refusal is SAID (a request that vanishes reads as a
    broken bot), nothing is written, and the proposal stays staged — the admin's later yes still
    finds it. The receipt goes out before the authorisation, so even the refused yes got one."""
    project = _project()
    module = _asking(project)
    talk = _Conversation(project, module)
    talk.say(REQUEST, user=CLIENT)

    reply = talk.say("sim", user=OTHER)

    assert reply == unauthorized_message(project)
    assert not module.asked("propose")
    assert staging.pending_for(ROOM) is not None
    # COUNTED, NOT COMPARED: the receipts come from a small catalogue picked by the message, and
    # this request and a bare "sim" pick the same one — so the last receipt reads the same whether
    # or not the refused yes got one. One per message is what tells them apart.
    assert talk.receipts == [_receipt(REQUEST), _receipt("sim")]

    talk.say("sim", user=ADMIN)

    assert [p["actor"] for p in module.asked("propose")] == [ADMIN]


def test_a_yes_is_gated_by_the_admin_list_and_NOT_by_who_asked(table, ledger):
    """TODAY: the requester who is not an admin cannot confirm their own draft, and an admin who
    did not ask for it can. #266 slice 4 binds the confirmation to the requester (ADR-0047 §4):
    another admin's yes stops confirming unless `accept_on_behalf` is set — this test flips then,
    on purpose."""
    project = _project()
    module = _asking(project)
    talk = _Conversation(project, module)
    talk.say(REQUEST, user=CLIENT)

    refused = talk.say("sim", user=CLIENT)

    assert refused == unauthorized_message(project)
    assert not module.asked("propose")

    talk.say("sim", user=ADMIN)

    assert [p["actor"] for p in module.asked("propose")] == [ADMIN]
    assert module.asked("propose")[0]["asked_by"] == f"<@{CLIENT}>"


def test_a_yes_carrying_a_fingerprint_that_no_longer_matches_writes_nothing(table, ledger):
    """What a click verified travels to the pop: a yes carrying a fingerprint that is not the
    staged proposal's — the button was posted for something since replaced — performs nothing,
    says the proposal was already handled, and leaves what IS staged where it was."""
    project = _project()
    module = _asking(project)
    talk = _Conversation(project, module)
    talk.say(REQUEST, user=CLIENT)
    staged = staging.pending_for(ROOM)

    reply = talk.say("sim", user=ADMIN, fingerprint="000000000000")

    assert reply == voice.proposal_already_handled(language=LANG)
    assert not module.asked("propose")
    assert staging.pending_for(ROOM) is staged


# ── 6. an expired proposal ──────────────────────────────────────────────────────────────────────

def _age_out(monkeypatch) -> None:
    later = time.time() + staging.PROPOSAL_TTL_SECONDS + 60
    monkeypatch.setattr(staging, "time", SimpleNamespace(time=lambda: later))


def test_a_yes_after_the_proposal_aged_out_hears_so_and_writes_nothing_AND_AGAIN_NEXT_TIME(
        table, ledger, monkeypatch):
    """Past the staging TTL, a "sim" is told the proposal expired — not answered by the model as
    if nothing had been staged, and never performed.

    AND THE NEXT "SIM" HEARS IT AGAIN, which looks wrong. `_expired_recently` consumes the notice
    so it is owed to one late confirmation, but the expired proposal's row in the durable mirror
    is never answered or cleared: the next read (`pending_for` falls back to the store when this
    process holds nothing) thaws it, finds it expired and lays a fresh tombstone. So every later
    yes or no in the conversation hears the notice, until something new is staged there. No slice
    of #266 names it; pinned as found, so changing it is a decision taken on its own."""
    project = _project()
    module = _asking(project)
    talk = _Conversation(project, module)
    talk.say(REQUEST, user=CLIENT)
    _age_out(monkeypatch)

    reply = talk.say("sim", user=ADMIN)

    assert reply == voice.proposal_expired(language=LANG)
    assert not module.asked("propose")
    assert len(module.asked("answer")) == 1, "the late yes was answered by the model"

    again = talk.say("sim", user=ADMIN)

    assert again == voice.proposal_expired(language=LANG)
    assert len(module.asked("answer")) == 1
    assert not module.asked("propose")


def test_with_no_durable_row_to_bring_it_back_the_expiry_notice_is_said_once(table, ledger,
                                                                            monkeypatch):
    """The rule the notice was written with, where nothing resurrects the proposal: its durable
    mirror could not be written (the mirror is best-effort), so once the first late "sim" has
    heard that it expired, the notice is spent and the next "sim" is an ordinary message that
    reaches the model."""
    project = _project()
    monkeypatch.setattr(messages, "ask", _raises)
    module = _asking(project)
    talk = _Conversation(project, module)
    talk.say(REQUEST, user=CLIENT)
    _age_out(monkeypatch)

    assert talk.say("sim", user=ADMIN) == voice.proposal_expired(language=LANG)

    again = talk.say("sim", user=ADMIN)

    assert again == PLAIN.text
    assert len(module.asked("answer")) == 2
    assert not module.asked("propose")


def test_a_no_after_the_proposal_aged_out_hears_so_too(table, ledger, monkeypatch):
    """A late "não" is a late answer to the same question: it hears that the proposal expired,
    not a conversational reply."""
    project = _project()
    module = _asking(project)
    talk = _Conversation(project, module)
    talk.say(REQUEST, user=CLIENT)
    _age_out(monkeypatch)

    reply = talk.say("não", user=CLIENT)

    assert reply == voice.proposal_expired(language=LANG)
    assert len(module.asked("answer")) == 1


def test_with_a_delivery_open_a_late_yes_answers_the_delivery_not_the_expiry(table, ledger,
                                                                            monkeypatch):
    """The order `settle` calls load-bearing: the acceptance is read BEFORE the expiry, so with a
    delivery waiting a bare "sim" answers "did it work?" — the delivery closes as `worked` and the
    person does not hear about a proposal that expired."""
    project = _project()
    module = _asking(project)
    talk = _Conversation(project, module)
    talk.say(REQUEST, user=CLIENT)
    loop = _awaiting_acceptance(ledger)
    _age_out(monkeypatch)

    reply = talk.say("sim", user=CLIENT)

    assert reply == followup.accepted_text(loop, agent_name=AGENT)
    [closed] = [x for x in fold(ledger) if x.kind == ACCEPTANCE]
    assert (closed.state, closed.outcome) == ("closed", "worked")
    assert not module.asked("propose")


# ── 7. the read-only intents ────────────────────────────────────────────────────────────────────

def test_status_is_answered_from_data_in_hand_without_the_model_and_closes_nothing(table,
                                                                                  ledger):
    """"status" is answered from the corpus and the ledger: the corpus' state plus what she is
    still waiting on, with no receipt and no model call. And because the model never READS the
    message, the decisions she asked a person for stay open — a status is not an answer to
    them."""
    project = _project()
    module = _Module(project)
    ledger.append(open_loop(DELIVERY, "4", owner=followup.OWNER, about=ROOM,
                            ts="2026-09-20T10:00:00+00:00", context={"issues": "12"}))
    module.record_decisions(["fechar ou não os cards em Review"], channel=ROOM)
    talk = _Conversation(project, module)

    reply = talk.say("status", user=CLIENT)

    assert reply == voice.corpus_state(available=True, requirements=1, promises=0,
                                       language=LANG) + "\n" + voice.still_waiting(
        questions=[], deliveries=1, language=LANG)
    assert "answer" not in module.verbs()
    assert "close_decisions_answered" not in module.verbs()
    assert talk.receipts == []
    assert [x.kind for x in waiting(fold(ledger), owner=followup.OWNER)
            if x.kind == DECISION] == [DECISION]
    assert table.turns(ROOM) == [("person", "status", CLIENT), ("agent", reply, "")]


def test_status_answers_even_when_the_base_cannot_be_read(table, ledger):
    """The intents are read BEFORE the base is checked: "how are we doing" must answer exactly
    when the requirements cannot be read, which is when somebody asks. The status says the base
    is unreadable — never the generic unavailable sentence, and never a model call."""
    project = _project()
    module = _Module(project, available=False)
    talk = _Conversation(project, module)

    reply = talk.say("status", user=CLIENT)

    assert reply == voice.corpus_state(available=False, requirements=0, promises=0,
                                       language=LANG)
    assert "answer" not in module.verbs() and talk.receipts == []


def test_triage_reads_the_board_and_reports_without_the_model(table, ledger):
    """"faz a triagem" reads the board and says what it found, with a receipt first (a board read
    is slow) and no model turn."""
    project = _project()
    module = _Module(project)
    talk = _Conversation(project, module)

    reply = talk.say("faz a triagem", user=CLIENT)

    assert reply == voice.triage_report(TriageReport(), language=LANG, agent_name=AGENT)
    assert "triage_board" in module.verbs() and "answer" not in module.verbs()
    assert talk.receipts == [_receipt("faz a triagem")]


def test_who_are_you_is_the_module_s_introduction_passed_on(table, ledger):
    """"se apresenta" is answered with what the module composes — no receipt, no model turn, and
    the handler adds nothing to it."""
    project = _project()
    module = _Module(project)
    talk = _Conversation(project, module)

    reply = talk.say("se apresenta", user=CLIENT)

    assert reply == INTRODUCED
    assert module.verbs() == ["settle_acceptance", "introduce"]
    assert talk.receipts == []


def test_what_is_parked_reads_the_diagnoses_and_reports_without_the_model(table, ledger):
    """"olha o que está parado" classifies what is parked from the diagnoses already on each
    ticket, with a receipt first (a board read) and no model turn of the conversation."""
    project = _project()
    module = _Module(project)
    talk = _Conversation(project, module)
    said = "olha o que está parado"

    reply = talk.say(said, user=CLIENT)

    assert reply == voice.needs_action_report(SimpleNamespace(decisions=[]), language=LANG,
                                              agent_name=AGENT)
    assert "review_needs_action" in module.verbs() and "answer" not in module.verbs()
    assert talk.receipts == [_receipt(said)]


# ── 8. the write intents ────────────────────────────────────────────────────────────────────────

DICTATED = "registra no requisito 4 que o pró-labore entra como despesa fixa"
DECIDED = "o pró-labore entra como despesa fixa"


def test_a_decision_dictated_on_a_requirement_is_staged_verbatim_and_written_on_a_yes(table,
                                                                                    ledger):
    """The typed intent stages the decision, shown back in the person's own words, with the
    admins named when the person cannot write it themselves — no model call. An admin's "sim"
    records it on that requirement, attributed and with where it was said."""
    project = _project()
    module = _Module(project)
    talk = _Conversation(project, module)

    reply = talk.say(DICTATED, user=CLIENT)

    assert reply == voice.decision_confirmation(number=4, decision=DECIDED, language=LANG) + (
        _admins_note("a decisão"))
    staged = staging.pending_for(ROOM)
    assert {k: staged[k] for k in ("kind", "number", "decision", "channel", "asked_by")} == {
        "kind": "decision", "number": 4, "decision": DECIDED, "channel": ROOM,
        "asked_by": f"<@{CLIENT}>"}
    assert "answer" not in module.verbs() and "record_decision" not in module.verbs()

    done = talk.say("sim", user=ADMIN)

    assert module.asked("record_decision") == [{"number": 4, "decision": DECIDED, "actor": ADMIN,
                                                "where": "conversa com o time de produto"}]
    assert done == voice.decision_recorded(number=4, existed=False, language=LANG,
                                           agent_name=AGENT)


def test_a_dictated_fact_is_read_back_and_written_only_on_a_yes(table, ledger):
    """"anota que …" stages the fact with a findable term and the words as said, attributed to
    who SAID it; the admin's yes writes it, and nothing is written before. The term is the fact
    with its leading article dropped and cut at five words — a literal here, because the rule
    that makes it is what is pinned."""
    project = _project()
    module = _Module(project)
    talk = _Conversation(project, module)
    fact = "o fechamento roda sempre no quinto dia útil"
    term = "fechamento roda sempre no quinto"

    reply = talk.say(f"anota que {fact}", user=CLIENT)

    assert reply == voice.fact_confirmation(term=term, body=fact, language=LANG) + (
        _admins_note("a anotação"))
    assert not module.asked("note_fact")

    done = talk.say("sim", user=ADMIN)

    assert module.asked("note_fact") == [{"term": term, "body": fact, "said_by": f"<@{CLIENT}>",
                                          "where": ""}]
    assert done == voice.fact_noted(term=term, language=LANG)


def test_a_dictation_that_ends_in_a_question_mark_is_a_question_and_reaches_the_model(table,
                                                                                     ledger):
    """"anota que semana passada o sistema caiu?" matches the dictation and is a rhetorical
    QUESTION: the intent gives the message back, nothing is staged, and the conversation answers
    it — a recognised intent that cannot be carried out must not swallow the message."""
    project = _project()
    module = _Module(project)
    talk = _Conversation(project, module)
    said = "anota que semana passada o sistema caiu?"

    reply = talk.say(said, user=CLIENT)

    assert reply == PLAIN.text
    assert module.asked("answer")[-1]["question"] == said
    assert staging.pending_for(ROOM) is None


def test_accept_is_staged_with_the_title_and_agreed_on_a_yes_then_broken_down(table, ledger):
    """"aceita o requisito 4" — the act that turns a written text into a promise — stages the
    acceptance with the requirement's title shown, and it is the one staged gesture that names no
    admins under it. The admin's yes accepts it; with no card waiting on it, the acceptance's own
    second act breaks it down (`asked_for=False`: nobody typed that request)."""
    project = _project()
    module = _Module(project, requirements=BASE)
    talk = _Conversation(project, module)

    reply = talk.say("aceita o requisito 4", user=CLIENT)

    assert reply == voice.accept_confirmation(number=4, title="Pró-labore", language=LANG)
    staged = staging.pending_for(ROOM)
    assert {k: staged[k] for k in ("kind", "number", "channel", "asked_by")} == {
        "kind": "accept", "number": 4, "channel": ROOM, "asked_by": f"<@{CLIENT}>"}
    assert not _writes(module) and "answer" not in module.verbs()

    done = talk.say("sim", user=ADMIN)

    assert module.asked("accept") == [{"number": 4, "actor": ADMIN}]
    assert module.asked("break_down") == [{"number": 4, "actor": ADMIN, "asked_for": False}]
    assert done == voice.accepted(number=4, language=LANG, agent_name=AGENT) + (
        "\n\nO requisito 4 virou **1** tarefa: #40.\n\nEstá no Backlog — começar a trabalhar "
        "nela continua sendo decisão de uma pessoa.")


def test_drop_is_staged_with_its_reason_and_taken_off_the_table_on_a_yes(table, ledger):
    """"cancela o requisito 5 porque …" stages the drop with the reason as said and whether the
    text was a promise (it is here, and the confirmation says so), names the admins, and the
    admin's yes drops it with that reason."""
    project = _project()
    module = _Module(project, requirements=BASE)
    talk = _Conversation(project, module)

    reply = talk.say("cancela o requisito 5 porque o cliente desistiu", user=CLIENT)

    assert reply == voice.drop_confirmation(number=5, title="Extrato conciliado",
                                            was_a_promise=True, language=LANG) + (
        _admins_note("a decisão"))
    staged = staging.pending_for(ROOM)
    assert {k: staged[k] for k in ("kind", "number", "reason", "was_a_promise", "channel",
                                   "asked_by")} == {
        "kind": "drop", "number": 5, "reason": "porque o cliente desistiu", "was_a_promise": True,
        "channel": ROOM, "asked_by": f"<@{CLIENT}>"}
    assert not _writes(module)

    done = talk.say("sim", user=ADMIN)

    assert module.asked("drop") == [{"number": 5, "actor": ADMIN,
                                     "reason": "porque o cliente desistiu"}]
    assert done == voice.dropped(number=5, was_a_promise=True, language=LANG, agent_name=AGENT)


def test_close_in_favour_of_a_named_card_is_staged_and_closed_on_a_yes(table, ledger):
    """"fecha o #12 como duplicado do #7" stages the close with the card that survives it, names
    the admins, and reads nothing from the board first; the admin's yes closes it in favour of
    that card."""
    project = _project()
    module = _Module(project)
    talk = _Conversation(project, module)

    reply = talk.say("fecha o #12 como duplicado do #7", user=CLIENT)

    assert reply == voice.close_confirmation(number="12", in_favour_of="7", reason="",
                                             language=LANG) + _admins_note("o encerramento")
    staged = staging.pending_for(ROOM)
    assert {k: staged[k] for k in ("kind", "number", "in_favour_of", "reason", "channel",
                                   "asked_by")} == {
        "kind": "close", "number": "12", "in_favour_of": "7", "reason": "", "channel": ROOM,
        "asked_by": f"<@{CLIENT}>"}
    assert not _writes(module)

    done = talk.say("sim", user=ADMIN)

    assert module.asked("close_card") == [{"number": "12", "actor": ADMIN, "in_favour_of": "7",
                                           "reason": ""}]
    assert done == voice.card_closed(number="12", in_favour_of="7", linked=True, reasoned=False,
                                     language=LANG, agent_name=AGENT)


def test_a_survivor_named_without_a_hash_is_asked_about_and_displaces_nothing(table, ledger):
    """"fecha o #12 como duplicado do 7" names the survivor without a `#`: that is ambiguity, and
    it costs a question — nothing is staged, and the draft already waiting in the conversation is
    still the one a "sim" would confirm."""
    project = _project()
    module = _asking(project)
    talk = _Conversation(project, module)
    talk.say(REQUEST, user=CLIENT)
    staged = staging.pending_for(ROOM)

    reply = talk.say("fecha o #12 como duplicado do 7", user=ADMIN)

    assert reply == f"{AGENT}: " + voice.survivor_unclear(number="12", other="7", language=LANG)
    assert staging.pending_for(ROOM) is staged
    assert not _writes(module)


def test_a_correction_of_a_card_is_shown_back_and_written_on_a_yes(table, ledger):
    """"corrige o #12: …" stages the new text as said, names the admins, and the admin's yes
    corrects the card with exactly that text."""
    project = _project()
    module = _Module(project)
    talk = _Conversation(project, module)
    text = "o relatório é semanal, não mensal"

    reply = talk.say(f"corrige o #12: {text}", user=CLIENT)

    assert reply == voice.correct_confirmation(number="12", text=text, title="",
                                               language=LANG) + _admins_note("a correção")
    staged = staging.pending_for(ROOM)
    assert {k: staged[k] for k in ("kind", "number", "text", "new_title", "channel",
                                   "asked_by")} == {
        "kind": "correct", "number": "12", "text": text, "new_title": "", "channel": ROOM,
        "asked_by": f"<@{CLIENT}>"}
    assert not _writes(module)

    done = talk.say("sim", user=ADMIN)

    assert module.asked("correct_card") == [{"number": "12", "actor": ADMIN, "text": text,
                                             "title": ""}]
    assert done == voice.card_corrected(number="12", existed=False, noted=True,
                                        criteria_removed=False, language=LANG, agent_name=AGENT)


def test_aligning_a_card_to_a_promise_is_staged_and_written_on_a_yes(table, ledger):
    """"alinha o #12 ao requisito 5" — 5 is a promise — stages the alignment with the requirement's
    title, names the admins, and the admin's yes rewrites the card from that requirement."""
    project = _project()
    module = _Module(project, requirements=BASE)
    talk = _Conversation(project, module)

    reply = talk.say("alinha o #12 ao requisito 5", user=CLIENT)

    assert reply == voice.align_confirmation(number="12", requirement=5,
                                             title="Extrato conciliado", language=LANG) + (
        _admins_note("a mudança"))
    staged = staging.pending_for(ROOM)
    assert {k: staged[k] for k in ("kind", "number", "requirement", "channel", "asked_by")} == {
        "kind": "align", "number": "12", "requirement": 5, "channel": ROOM,
        "asked_by": f"<@{CLIENT}>"}
    assert not _writes(module)

    done = talk.say("sim", user=ADMIN)

    assert module.asked("align_card") == [{"number": "12", "requirement": 5, "actor": ADMIN}]
    assert done == voice.card_aligned(number="12", requirement=5, noted=True, language=LANG,
                                      agent_name=AGENT)


_BY_NUMBER = {r.number: r for r in BASE}


@pytest.mark.parametrize("requirement, refusal", [
    (4, _not_a_promise(4, _BY_NUMBER[4])),
    (7, voice.align_refused(number="12", requirement=7, successor=5, language=LANG)),
    (6, voice.align_refused(number="12", requirement=6, language=LANG)),
    (8, voice.align_to_unagreed(number="12", requirement=8, successor=4, language=LANG)),
    (9, voice.align_refused(number="12", requirement=9, replaced=True, language=LANG)),
    (10, voice.align_to_dropped_replacement(number="12", requirement=10, successor=6,
                                            language=LANG)),
], ids=["a-proposal", "replaced-by-a-promise", "dropped", "replaced-by-a-proposal",
        "a-chain-that-dangles", "replaced-by-a-dropped-text"])
def test_aligning_to_what_is_not_a_promise_is_refused_before_anybody_is_asked(requirement,
                                                                             refusal, table,
                                                                             ledger):
    """`align_card` writes only from a PROMISE, so the channel refuses anything else HERE —
    nothing staged, nobody asked to authorise an act that cannot happen — and the refusal names
    what would work, read to the end of the supersession chain."""
    project = _project()
    module = _Module(project, requirements=BASE)
    talk = _Conversation(project, module)

    reply = talk.say(f"alinha o #12 ao requisito {requirement}", user=ADMIN)

    assert reply == f"{AGENT}: {refusal}"
    assert staging.pending_for(ROOM) is None
    assert not _writes(module) and "answer" not in module.verbs()


@pytest.mark.parametrize("said, refused", [
    ("aceita o requisito 5", f"{AGENT}: o requisito 5 já estava acordado."),
    ("aceita o requisito 6",
     f"{AGENT}: o requisito 6 já não vale, então acordá-lo agora seria trazer de volta um texto "
     "que vocês já tinham tirado da mesa. Se isso voltou a fazer sentido, me digam e eu proponho "
     "de novo para vocês confirmarem."),
    ("cancela o requisito 6", f"{AGENT}: o requisito 6 já não estava valendo."),
    ("registra no requisito 6 que o pró-labore entra como despesa fixa",
     f"{AGENT}: o requisito 6 já não vale, então uma decisão registrada nele ficaria guardada "
     "onde ninguém vai procurar. Em qual requisito isso deve entrar?"),
], ids=["accept-a-promise", "accept-a-dropped-text", "drop-a-dropped-text",
        "decide-on-a-dropped-text"])
def test_a_gesture_on_a_requirement_it_cannot_apply_to_is_refused_in_its_own_words(said, refused,
                                                                                  table, ledger):
    """Agreeing to what is already agreed, reviving a retired text as a promise, dropping what is
    already off the table, recording a decision where nobody will look: each is refused by the
    gesture's own sentence, before anything is staged or anybody is asked."""
    project = _project()
    module = _Module(project, requirements=BASE)
    talk = _Conversation(project, module)

    reply = talk.say(said, user=ADMIN)

    assert reply == refused
    assert staging.pending_for(ROOM) is None
    assert not _writes(module) and "answer" not in module.verbs()


#: The four gestures that name a requirement by number, each with the number left open.
NAMING = {
    "accept": "aceita o requisito {n}",
    "drop": "cancela o requisito {n}",
    "decision": "registra no requisito {n} que o pró-labore entra como despesa fixa",
    "align": "alinha o #12 ao requisito {n}",
}


@pytest.mark.parametrize("gesture", sorted(NAMING))
def test_a_gesture_naming_a_requirement_the_base_does_not_have_is_told_so(gesture, table,
                                                                         ledger):
    """A number the base does not have is said to be missing — one sentence for every gesture —
    and nothing is staged."""
    project = _project()
    module = _Module(project, requirements=BASE)
    talk = _Conversation(project, module)

    reply = talk.say(NAMING[gesture].format(n=42), user=ADMIN)

    assert reply == f"{AGENT}: " + voice.requirement_not_found(number=42, language=LANG)
    assert staging.pending_for(ROOM) is None
    assert not _writes(module) and "answer" not in module.verbs()


@pytest.mark.parametrize("gesture", sorted(NAMING))
def test_a_gesture_naming_a_requirement_while_the_base_cannot_be_read_says_THAT(gesture, table,
                                                                               ledger):
    """"I could not read the base" is not "that requirement does not exist": with the base
    unreadable every number would look missing, so each gesture says the base is unavailable
    instead of telling a client a text they wrote does not exist."""
    project = _project()
    module = _Module(project, available=False, requirements=BASE)
    talk = _Conversation(project, module)

    reply = talk.say(NAMING[gesture].format(n=4), user=ADMIN)

    assert reply == voice.unavailable(language=LANG)
    assert staging.pending_for(ROOM) is None
    assert not _writes(module) and "answer" not in module.verbs()


BREAK = "quebra o requisito 5 em tarefas"


def test_a_breakdown_asked_for_by_somebody_off_the_admin_list_is_refused_before_anything(
        table, ledger):
    """One of the two gestures that write on the match alone: the gate is checked in the channel
    BEFORE anything is called — no receipt bought, nothing filed, the refusal said."""
    project = _project()
    module = _Module(project, requirements=BASE)
    talk = _Conversation(project, module)

    reply = talk.say(BREAK, user=CLIENT)

    assert reply == unauthorized_message(project)
    assert talk.receipts == []
    assert not _writes(module)


def test_a_breakdown_an_admin_types_files_the_work_as_ASKED_FOR(table, ledger):
    """An admin's "quebra o requisito 5 em tarefas" files the work at once, with a receipt first,
    in that admin's name and marked `asked_for=True` — a PERSON typed it, which is what tells it
    apart from an acceptance's automatic second act — and says what was filed."""
    project = _project()
    module = _Module(project, requirements=BASE)
    talk = _Conversation(project, module)

    reply = talk.say(BREAK, user=ADMIN)

    assert module.asked("break_down") == [{"number": 5, "actor": ADMIN, "asked_for": True}]
    assert reply == (f"{AGENT}: O requisito 5 virou **1** tarefa: #40.\n\nEstá no Backlog — "
                     f"começar a trabalhar nela continua sendo decisão de uma pessoa.")
    assert talk.receipts == [_receipt(BREAK)]
    assert staging.pending_for(ROOM) is None


def test_a_refine_asked_for_by_somebody_off_the_admin_list_is_refused_before_anything(table,
                                                                                    ledger):
    """The other gesture that writes on the match alone, gated the same way: no receipt,
    nothing written, the refusal said."""
    project = _project()
    module = _Module(project)
    talk = _Conversation(project, module)

    reply = talk.say("refina o #12", user=CLIENT)

    assert reply == unauthorized_message(project)
    assert talk.receipts == []
    assert not _writes(module)


def test_a_refine_an_admin_types_writes_the_criteria_at_once(table, ledger):
    """An admin's "refina o #12" writes criteria where there were none, with a receipt first and
    in that admin's name, and says so."""
    project = _project()
    module = _Module(project)
    talk = _Conversation(project, module)

    reply = talk.say("refina o #12", user=ADMIN)

    assert module.asked("refine") == [{"number": "12", "actor": ADMIN}]
    assert reply == f"{AGENT}: " + voice.criteria_written(number="12", noted=True, measure="",
                                                          language=LANG)
    assert talk.receipts == [_receipt("refina o #12")]


BASELINE = "documenta o que já existe no código"


class _Room:
    """The channel the baseline announces its outcome on, off the listener thread."""

    def __init__(self) -> None:
        self.said: list[str] = []

    def say(self, *, project, channel, text) -> bool:
        self.said.append(text)
        return True


def _baseline_finished() -> None:
    for worker in [t for t in threading.enumerate() if t.name == "product-baseline"]:
        worker.join(timeout=5)


def test_the_first_pass_asked_for_by_somebody_off_the_admin_list_is_refused(table, ledger,
                                                                           monkeypatch):
    """The brownfield pass writes a pull request, so it is gated: refused out loud, and nothing
    starts."""
    project = _project()
    module = _Module(project)
    room = _Room()
    monkeypatch.setattr("openfactory.adapters.channel.build_channel", lambda _p: room)
    talk = _Conversation(project, module)

    reply = talk.say(BASELINE, user=CLIENT)
    _baseline_finished()

    assert reply == unauthorized_message(project)
    assert not module.asked("baseline") and room.said == []


def test_the_first_pass_an_admin_asks_for_is_announced_run_off_the_thread_and_reported(
        table, ledger, monkeypatch):
    """An admin's "documenta o que já existe no código" is answered at once with "started" and
    runs off the listener thread: the receipt, the pass, and its outcome said on the product
    room when it finishes."""
    project = _project()
    module = _Module(project)
    room = _Room()
    monkeypatch.setattr("openfactory.adapters.channel.build_channel", lambda _p: room)
    talk = _Conversation(project, module)

    reply = talk.say(BASELINE, user=ADMIN)
    _baseline_finished()

    assert reply == voice.baseline_started(language=LANG, agent_name=AGENT)
    assert module.asked("baseline") == [{}]
    assert room.said == [voice.baseline_done(ok=True, url="https://forge.example/pull/9",
                                             detail="", existed=False, language=LANG,
                                             agent_name=AGENT)]
    assert talk.receipts == [_receipt(BASELINE)]


# ── 9. the defect gesture ───────────────────────────────────────────────────────────────────────

BROKEN = "a conciliação está duplicando lançamentos"
READ_AS_DEFECT = ProductAnswer(ok=True, text="Isso contradiz o requisito 4.", is_defect=True,
                               violates=4)


def test_a_broken_promise_is_staged_as_a_defect_and_filed_on_an_admin_s_yes(table, ledger):
    """The role read a broken promise: its words stay in front, the person is asked to confirm
    the restatement, the admins are named, and no requirement is drafted. The admin's yes files
    the defect against the promise it breaks, reported by who reported it."""
    project = _project()
    module = _Module(project, replies={"duplicando": READ_AS_DEFECT})
    talk = _Conversation(project, module)

    reply = talk.say(BROKEN, user=CLIENT)

    assert reply == (f"{READ_AS_DEFECT.text}\n\n"
                     + voice.defect_confirmation(violates=4, language=LANG)
                     + _admins_note("o registro"))
    staged = staging.pending_for(ROOM)
    assert {k: staged[k] for k in ("kind", "restated", "reported_by", "violates", "source",
                                   "channel")} == {
        "kind": "defect", "restated": BROKEN, "reported_by": f"<@{CLIENT}>", "violates": 4,
        "source": "", "channel": ROOM}
    assert "draft" not in module.verbs()

    done = talk.say("sim", user=ADMIN)

    assert module.asked("file_defect") == [{"restated": BROKEN, "reported_by": f"<@{CLIENT}>",
                                            "violates": 4, "severity": "", "source": ""}]
    assert done == voice.defect_filed(ref="#88", violates=4, language=LANG, existed=False)
    assert not module.asked("propose"), "a defect became a requirement"


def test_a_defect_an_admin_reports_names_nobody_else_to_confirm_it(table, ledger):
    """The admins' note is for a person who cannot confirm; an admin's own report is asked about
    with the restatement alone."""
    project = _project()
    module = _Module(project, replies={"duplicando": READ_AS_DEFECT})
    talk = _Conversation(project, module)

    reply = talk.say(BROKEN, user=ADMIN)

    assert reply == (f"{READ_AS_DEFECT.text}\n\n"
                     + voice.defect_confirmation(violates=4, language=LANG))


def test_a_long_report_is_restated_in_its_first_four_hundred_characters(table, ledger):
    """What is staged — and filed on the yes — is the report cut at 400 characters."""
    project = _project()
    module = _Module(project, replies={"duplicando": READ_AS_DEFECT})
    talk = _Conversation(project, module)
    long_report = BROKEN + ", " + "e o saldo final também não bate com o extrato " * 12

    talk.say(long_report, user=CLIENT)

    assert staging.pending_for(ROOM)["restated"] == long_report.strip()[:400]


def test_one_answer_stages_one_thing_and_a_defect_outranks_a_ticket_and_a_request(table,
                                                                                 ledger):
    """The stage holds ONE proposal per conversation, so the order the gestures are read in is
    load-bearing: an answer that reads as a defect, a ticket and a request at once stages the
    defect, opens no ticket proposal and drafts nothing."""
    project = _project()
    everything = READ_AS_DEFECT.model_copy(update={"is_ticket": True, "is_request": True,
                                                   "ticket_title": "Duplicação"})
    module = _Module(project, replies={"duplicando": everything}, drafted=DRAFTED)
    talk = _Conversation(project, module)

    talk.say(BROKEN, user=CLIENT)

    assert staging.pending_for(ROOM)["kind"] == "defect"
    assert "draft" not in module.verbs()


def test_a_defect_that_displaces_a_waiting_draft_says_so_first(table, ledger):
    """ONE slot, last wins — and the eviction is admitted: a defect staged over a waiting draft
    opens with the line that says the draft was set aside, and the stage now holds the defect."""
    project = _project()
    module = _Module(project, replies={"PDF": ASKED_FOR, "duplicando": READ_AS_DEFECT},
                     drafted=DRAFTED)
    talk = _Conversation(project, module)
    talk.say(REQUEST, user=CLIENT)

    reply = talk.say(BROKEN, user=CLIENT)

    assert reply == (DISPLACED + f"{READ_AS_DEFECT.text}\n\n"
                     + voice.defect_confirmation(violates=4, language=LANG)
                     + _admins_note("o registro"))
    assert staging.pending_for(ROOM)["kind"] == "defect"


def test_a_draft_that_displaces_a_waiting_defect_says_so_after_the_role_s_answer(table, ledger):
    """The same eviction the other way round: the draft's notice sits between the role's answer
    and the draft itself, and the stage now holds the draft."""
    project = _project()
    module = _Module(project, replies={"PDF": ASKED_FOR, "duplicando": READ_AS_DEFECT},
                     drafted=DRAFTED)
    talk = _Conversation(project, module)
    talk.say(BROKEN, user=CLIENT)

    reply = talk.say(REQUEST, user=CLIENT)

    assert reply == f"{ASKED_FOR.text}\n\n" + DISPLACED + _confirmation()
    assert staging.pending_for(ROOM)["kind"] == "draft"


# ── 10. the ticket gesture ──────────────────────────────────────────────────────────────────────

WANTS_A_CARD = "abre um card para trocar o logo do relatório"
READ_AS_TICKET = ProductAnswer(ok=True, text="Certo, isso é um card.", is_ticket=True,
                               ticket_title="Trocar o logo do relatório")


def test_a_card_asked_for_as_described_is_staged_with_its_title_and_opened_on_a_yes(table,
                                                                                   ledger):
    """The role read a request for a card as described — not a defect, not a new requirement:
    the person confirms the title, the admins are named, and the admin's yes opens it with the
    person's words as its description."""
    project = _project()
    module = _Module(project, replies={"card": READ_AS_TICKET}, drafted=DRAFTED)
    talk = _Conversation(project, module)

    reply = talk.say(WANTS_A_CARD, user=CLIENT)

    title = READ_AS_TICKET.ticket_title
    assert reply == (f"{READ_AS_TICKET.text}\n\n"
                     + voice.ticket_confirmation(title=title, language=LANG)
                     + _admins_note("abrir o cartão"))
    staged = staging.pending_for(ROOM)
    assert {k: staged[k] for k in ("kind", "title", "described", "reported_by", "channel")} == {
        "kind": "ticket", "title": title, "described": WANTS_A_CARD,
        "reported_by": f"<@{CLIENT}>", "channel": ROOM}
    assert "draft" not in module.verbs()

    done = talk.say("sim", user=ADMIN)

    assert module.asked("file_ticket") == [{"title": title, "described": WANTS_A_CARD,
                                            "reported_by": f"<@{CLIENT}>", "source": ""}]
    assert done == voice.ticket_filed(ref="#89", url="https://board.example/89", language=LANG,
                                      existed=False)


def test_a_card_an_admin_asks_for_names_nobody_else_to_confirm_it(table, ledger):
    """As with a defect: an admin's own request for a card carries no admins' note."""
    project = _project()
    module = _Module(project, replies={"card": READ_AS_TICKET})
    talk = _Conversation(project, module)

    reply = talk.say(WANTS_A_CARD, user=ADMIN)

    assert reply == (f"{READ_AS_TICKET.text}\n\n"
                     + voice.ticket_confirmation(title=READ_AS_TICKET.ticket_title,
                                                 language=LANG))


def test_a_card_read_without_a_title_takes_the_person_s_message_as_its_title(table, ledger):
    """The role read a card and gave it no title: the message itself becomes the title, cut at
    80 characters — never an empty card."""
    project = _project()
    untitled = READ_AS_TICKET.model_copy(update={"ticket_title": ""})
    module = _Module(project, replies={"card": untitled})
    talk = _Conversation(project, module)

    talk.say(WANTS_A_CARD, user=CLIENT)

    assert staging.pending_for(ROOM)["title"] == WANTS_A_CARD[:80]


def test_a_card_outranks_a_request_read_in_the_same_answer(table, ledger):
    """A card asked for as described is not a wish to be argued into a requirement: an answer
    read as both stages the card and drafts nothing."""
    project = _project()
    both = READ_AS_TICKET.model_copy(update={"is_request": True})
    module = _Module(project, replies={"card": both}, drafted=DRAFTED)
    talk = _Conversation(project, module)

    talk.say(WANTS_A_CARD, user=CLIENT)

    assert staging.pending_for(ROOM)["kind"] == "ticket"
    assert "draft" not in module.verbs()


def test_an_order_for_the_backlog_is_read_back_top_first_and_written_on_a_yes(table, ledger):
    """The reorder gesture: the order travels untouched — top first, as said, never sorted — and
    the admin's yes writes exactly that order."""
    project = _project()
    ordered = ProductAnswer(ok=True, text="Entendi a ordem.", is_reorder=True, order=["12", "7"])
    module = _Module(project, replies={"ordem": ordered})
    talk = _Conversation(project, module)

    reply = talk.say("a ordem é o 12 e depois o 7", user=CLIENT)

    assert reply == (f"{ordered.text}\n\n"
                     + voice.reorder_confirmation(numbers=["12", "7"], language=LANG)
                     + _admins_note("gravar a ordem"))
    assert staging.pending_for(ROOM)["numbers"] == ["12", "7"]

    done = talk.say("sim", user=ADMIN)

    assert module.asked("reorder") == [{"numbers": ["12", "7"], "actor": ADMIN}]
    assert done == voice.reordered(["12", "7"], language=LANG, agent_name=AGENT)


def test_a_reorder_read_with_no_order_stages_nothing(table, ledger):
    """A reorder the role read without an order to write is not a proposal: nothing is staged
    and the role's answer is the reply."""
    project = _project()
    empty = ProductAnswer(ok=True, text="Qual ordem você quer?", is_reorder=True, order=[])
    module = _Module(project, replies={"ordem": empty})
    talk = _Conversation(project, module)

    reply = talk.say("muda a ordem do backlog", user=CLIENT)

    assert reply == empty.text
    assert staging.pending_for(ROOM) is None


def test_a_start_the_model_recognised_proposes_the_queue_with_its_answer_in_front(table,
                                                                                  ledger):
    """The queue gesture the word list missed and the model read: her answer stays in front of the
    proposal, the proposal is staged, and the admin's yes promotes exactly what was proposed."""
    project = _project()
    start = ProductAnswer(ok=True, text="Dá para começar.", gesture="queue")
    module = _Module(project, replies={"avançar": start})
    talk = _Conversation(project, module)

    reply = talk.say("será que a gente consegue avançar com isso", user=CLIENT)

    assert reply == f"{start.text}\n\n" + voice.queue_proposal(
        Readiness(), QueueProposal(items=[Proposed(ticket="12")]), titles={}, language=LANG,
        agent_name=AGENT)
    assert staging.pending_for(ROOM)["kind"] == "queue"

    done = talk.say("sim", user=ADMIN)

    assert module.asked("promote") == [{"numbers": ["12"], "actor": ADMIN}]
    assert done == voice.queued(["12"], language=LANG, agent_name=AGENT)


def test_a_start_outranks_a_request_read_in_the_same_answer(table, ledger):
    """Asking to START the agreed work is not asking for something new: an answer read as both
    the queue gesture and a request stages the queue proposal and drafts nothing."""
    project = _project()
    both = ProductAnswer(ok=True, text="Dá para começar.", gesture="queue", is_request=True)
    module = _Module(project, replies={"avançar": both}, drafted=DRAFTED)
    talk = _Conversation(project, module)

    talk.say("será que a gente consegue avançar com isso", user=CLIENT)

    assert staging.pending_for(ROOM)["kind"] == "queue"
    assert "draft" not in module.verbs()


def test_a_start_with_nothing_ready_stages_nothing_and_says_so(table, ledger):
    """The gesture read and nothing ready to start: the queue's own sentence for that is the
    reply and nothing is staged — an empty proposal a "sim" could approve would promote nothing
    and still read as a decision. Her answer is not put in front of it: `_queue_reply` adds the
    preamble only to a staged proposal."""
    project = _project()
    start = ProductAnswer(ok=True, text="Dá para começar.", gesture="queue")
    module = _Module(project, replies={"avançar": start}, queue=())
    talk = _Conversation(project, module)

    reply = talk.say("será que a gente consegue avançar com isso", user=CLIENT)

    assert reply == voice.queue_proposal(Readiness(), QueueProposal(items=[]), titles={},
                                         language=LANG, agent_name=AGENT)
    assert staging.pending_for(ROOM) is None


def test_what_comes_next_typed_proposes_the_queue_without_the_model(table, ledger):
    """"o que entra agora?" is the typed queue gesture: the board is read, the proposal staged,
    no model turn — and the admin's yes promotes what was proposed."""
    project = _project()
    module = _Module(project)
    talk = _Conversation(project, module)

    reply = talk.say("o que entra agora?", user=CLIENT)

    assert reply == voice.queue_proposal(
        Readiness(), QueueProposal(items=[Proposed(ticket="12")]), titles={}, language=LANG,
        agent_name=AGENT)
    staged = staging.pending_for(ROOM)
    assert {k: staged[k] for k in ("kind", "numbers", "channel")} == {
        "kind": "queue", "numbers": ["12"], "channel": ROOM}
    assert "answer" not in module.verbs()

    talk.say("sim", user=ADMIN)

    assert module.asked("promote") == [{"numbers": ["12"], "actor": ADMIN}]


# ── 11. the acceptance loop ─────────────────────────────────────────────────────────────────────

def _awaiting_acceptance(ledger, subject: str = "7",
                         ts: str = "2026-09-20T10:00:00+00:00") -> object:
    loop = open_loop(ACCEPTANCE, subject, owner=followup.OWNER, about=ROOM, ts=ts,
                     context={"asked_by": CLIENT})
    ledger.append(loop)
    return loop


def test_it_worked_closes_the_delivery_as_worked_without_the_model(table, ledger):
    """"funcionou" answers "did it work?": the delivery is closed as `worked` in the ledger and
    the acceptance sentence is the reply — no receipt, no model, nothing drafted."""
    project = _project()
    loop = _awaiting_acceptance(ledger)
    module = _Module(project)
    talk = _Conversation(project, module)

    reply = talk.say("funcionou", user=CLIENT)

    assert reply == followup.accepted_text(loop, agent_name=AGENT)
    [closed] = [x for x in fold(ledger) if x.kind == ACCEPTANCE]
    assert (closed.state, closed.outcome) == ("closed", "worked")
    assert "answer" not in module.verbs() and talk.receipts == []


def test_it_did_not_work_closes_the_delivery_as_rejected_and_invites_the_defect(table, ledger):
    """"não funcionou" closes it as `did-not-work` and says so — never counted as delivered."""
    project = _project()
    loop = _awaiting_acceptance(ledger)
    module = _Module(project)
    talk = _Conversation(project, module)

    reply = talk.say("não funcionou", user=CLIENT)

    assert reply == followup.rejected_text(loop, agent_name=AGENT)
    [closed] = [x for x in fold(ledger) if x.kind == ACCEPTANCE]
    assert (closed.state, closed.outcome) == ("closed", "did-not-work")
    assert "answer" not in module.verbs()


def test_an_answer_the_word_list_cannot_read_is_judged_and_a_worked_closes_the_delivery(table,
                                                                                       ledger):
    """ADR-0029: "testei, tá ok" is no word the list trusts, and with a delivery open the model is
    asked whether the person said it works — about the delivery it names. Its "worked" closes the
    delivery exactly as a "funcionou" would."""
    project = _project()
    loop = _awaiting_acceptance(ledger)
    module = _Module(project, acceptance="worked")
    talk = _Conversation(project, module)

    reply = talk.say("testei, tá ok", user=CLIENT)

    assert module.asked("judge_acceptance") == [{"reply": "testei, tá ok",
                                                 "delivered": "requisito 7"}]
    assert reply == followup.accepted_text(loop, agent_name=AGENT)
    [closed] = [x for x in fold(ledger) if x.kind == ACCEPTANCE]
    assert (closed.state, closed.outcome) == ("closed", "worked")
    assert "answer" not in module.verbs()


def test_with_two_deliveries_waiting_the_newest_is_settled_and_NAMED(table, ledger):
    """Two deliveries and a bare "funcionou": the newest is settled and the reply names it, so a
    wrong guess is visible and correctable; the older one stays open."""
    project = _project()
    older = _awaiting_acceptance(ledger, subject="7", ts="2026-09-20T10:00:00+00:00")
    newer = _awaiting_acceptance(ledger, subject="8", ts="2026-09-21T10:00:00+00:00")
    module = _Module(project)
    talk = _Conversation(project, module)

    reply = talk.say("funcionou", user=CLIENT)

    assert reply == followup.accepted_text(newer, agent_name=AGENT, ambiguous=True)
    assert [x.subject for x in waiting(fold(ledger), owner=followup.OWNER)] == [older.subject]


def test_a_staged_proposal_outranks_an_open_delivery(table, ledger):
    """A pending proposal is the question just asked: with both open, "sim" confirms the proposal
    and the delivery stays open, its acceptance never consulted."""
    project = _project()
    _awaiting_acceptance(ledger)
    module = _asking(project)
    talk = _Conversation(project, module)
    talk.say(REQUEST, user=ADMIN)
    settled_before = len(module.asked("settle_acceptance"))

    talk.say("sim", user=ADMIN)

    assert [p["actor"] for p in module.asked("propose")] == [ADMIN]
    assert len(module.asked("settle_acceptance")) == settled_before
    assert [x.kind for x in waiting(fold(ledger), owner=followup.OWNER)] == [ACCEPTANCE]


def test_with_a_proposal_pending_an_answer_about_the_delivery_does_not_close_it(table, ledger):
    """The same rule for a message neither word list reads as a yes or a no: "funcionou" with a
    proposal pending and the judge undecided is conversation — the delivery is NOT settled (its
    acceptance is not even asked), the proposal stays staged, and the model is told what is still
    pending, which is the fact whose absence once let her announce as registered what she had
    only proposed."""
    project = _project()
    _awaiting_acceptance(ledger)
    module = _asking(project)
    talk = _Conversation(project, module)
    talk.say(REQUEST, user=ADMIN)
    staged = staging.pending_for(ROOM)
    settled_before = len(module.asked("settle_acceptance"))

    reply = talk.say("funcionou", user=ADMIN)

    assert reply == PLAIN.text
    assert len(module.asked("settle_acceptance")) == settled_before
    assert [x.kind for x in waiting(fold(ledger), owner=followup.OWNER)] == [ACCEPTANCE]
    assert staging.pending_for(ROOM) is staged
    assert module.asked("answer")[-1]["pending"] == staging._proposal_summary(staged)


@pytest.fixture()
def released(monkeypatch) -> list:
    calls: list = []

    def _release(project, issue, *, approver, comment=""):
        calls.append((str(issue), approver))
        return True, ""

    monkeypatch.setattr("openfactory.product.release.release", _release)
    return calls


def _awaiting_release(ledger, issue: str = "12",
                      ts: str = "2026-09-20T10:00:00+00:00") -> None:
    ledger.append(followup.release_of(issue, channel=ROOM, ts=ts, requirement="0004",
                                      where="https://staging.example"))


def test_it_worked_on_a_RELEASE_puts_it_live_with_the_admin_as_the_approver(table, ledger,
                                                                          released):
    """The one acceptance that spends: an admin's "funcionou o #12" on a release loop releases
    that issue, with that admin recorded as the approver, says it is going live, and leaves the
    loop closed as `worked`."""
    project = _project()
    _awaiting_release(ledger)
    talk = _Conversation(project, _Module(project))

    reply = talk.say("funcionou o #12", user=ADMIN)

    assert released == [("12", ADMIN)]
    assert reply == (f"{AGENT}: perfeito — **estou subindo para produção agora**, com o seu "
                     f"\"funcionou\" como aprovação. Fica registrado que foi você quem liberou e "
                     f"quando. Eu volto aqui quando estiver no ar.")
    [loop] = [x for x in fold(ledger) if x.kind == ACCEPTANCE]
    assert (loop.state, loop.outcome) == ("closed", "worked")


def test_it_did_not_work_on_a_RELEASE_releases_nothing_and_says_so(table, ledger, released):
    """"não funcionou o #12" on a release loop releases NOTHING, even from an admin, and says so
    plainly; the loop is closed as rejected."""
    project = _project()
    _awaiting_release(ledger)
    talk = _Conversation(project, _Module(project))

    reply = talk.say("não funcionou o #12", user=ADMIN)

    assert released == []
    assert reply == (f"{AGENT}: entendi — **não subi nada**. Vou devolver isso ao time com o que "
                     f"você disse, e volto quando estiver corrigido para você conferir de novo.")
    [loop] = [x for x in fold(ledger) if x.kind == ACCEPTANCE]
    assert (loop.state, loop.outcome) == ("closed", "did-not-work")


def test_a_release_the_workflow_refused_is_said_as_refused_never_as_going_live(table, ledger,
                                                                             monkeypatch):
    """The act is observed before it is claimed: when the release comes back refused, the reply is
    the workflow's own reason — never "estou subindo para produção"."""
    project = _project()
    _awaiting_release(ledger)
    why = "o #12 já não está esperando para subir — alguém mexeu nele antes."
    monkeypatch.setattr("openfactory.product.release.release",
                        lambda project, issue, *, approver, comment="": (False, why))
    talk = _Conversation(project, _Module(project))

    reply = talk.say("funcionou o #12", user=ADMIN)

    assert reply == f"{AGENT}: {why}"


def test_with_two_releases_waiting_a_bare_it_worked_releases_NOTHING_and_asks_which(table, ledger,
                                                                                  released):
    """Ambiguity on a release is refused, not named: two releases waiting and a bare "funcionou"
    from an admin releases nothing, lists both, tells the person the exact sentence that picks
    one, and leaves both loops open for that answer."""
    project = _project()
    _awaiting_release(ledger, issue="12", ts="2026-09-20T10:00:00+00:00")
    _awaiting_release(ledger, issue="13", ts="2026-09-21T10:00:00+00:00")
    talk = _Conversation(project, _Module(project))

    reply = talk.say("funcionou", user=ADMIN)

    assert released == []
    assert reply == (f"{AGENT}: tem mais de uma coisa esperando a sua conferida (#12, #13), então "
                     f"**não subi nada** — prefiro não adivinhar qual delas você testou. Responda "
                     f"«funcionou o #número» e eu coloco essa no ar.")
    assert len([x for x in waiting(fold(ledger), owner=followup.OWNER)
                if x.kind == ACCEPTANCE]) == 2


def test_it_worked_on_a_RELEASE_from_someone_who_may_not_approve_releases_nothing_and_leaves_it_OPEN(
        table, ledger, released):
    """Anyone off the admin list is refused out loud, nothing is released, and the question is
    still waiting for somebody who may answer it.

    PINNED AS FOUND THE OTHER WAY, AND FIXED BY #273. `settle_acceptance` wrote the verdict to the
    ledger before `_maybe_release` asked who was speaking, so the refused "funcionou" closed the
    release loop as `worked`: the ledger said the release was accepted, and an admin's answer
    afterwards found nothing awaiting it. The module hands a release loop back open now, and the
    gate closes it only once `may_act` passes."""
    project = _project()
    _awaiting_release(ledger)
    module = _Module(project)
    talk = _Conversation(project, module)

    refused = talk.say("funcionou o #12", user=CLIENT)

    assert refused == unauthorized_message(project)
    assert released == []
    [loop] = [x for x in fold(ledger) if x.kind == ACCEPTANCE]
    assert (loop.state, loop.outcome) == ("open", "")
    assert [x.subject for x in waiting(fold(ledger), owner=followup.OWNER)] == ["release-12"]
    assert "answer" not in module.verbs(), "the refused verdict was read as conversation"


def test_a_refused_it_worked_then_an_admin_s_releases_it_exactly_once(table, ledger, released):
    """#273 end to end: the refused "funcionou" left the question open, so the admin's own
    "funcionou o #12" lands on it — released once, in the admin's name, and the loop closed as
    `worked` by that answer. A second "funcionou" from the admin finds nothing left to release."""
    project = _project()
    _awaiting_release(ledger)
    module = _Module(project)
    talk = _Conversation(project, module)
    talk.say("funcionou o #12", user=CLIENT)

    reply = talk.say("funcionou o #12", user=ADMIN)

    assert released == [("12", ADMIN)]
    assert "estou subindo para produção agora" in reply
    [loop] = [x for x in fold(ledger) if x.kind == ACCEPTANCE]
    assert (loop.state, loop.outcome) == ("closed", "worked")

    talk.say("funcionou o #12", user=ADMIN)

    assert released == [("12", ADMIN)], "one release, answered twice, went live twice"


def test_an_admin_s_it_worked_closes_the_release_even_when_the_workflow_refuses_it(table, ledger,
                                                                                  monkeypatch):
    """The gate closes the loop on an authorised verdict, BEFORE the release and whatever the
    release answers (#273): the loop records what somebody who may act said, and the reply says
    separately that the workflow was no longer there to take it. Left open, the loop would be
    chased about a release nobody can make any more."""
    project = _project()
    _awaiting_release(ledger)
    why = "o #12 já não está esperando para subir — alguém mexeu nele antes."
    monkeypatch.setattr("openfactory.product.release.release",
                        lambda project, issue, *, approver, comment="": (False, why))
    talk = _Conversation(project, _Module(project))

    reply = talk.say("funcionou o #12", user=ADMIN)

    assert reply == f"{AGENT}: {why}"
    [loop] = [x for x in fold(ledger) if x.kind == ACCEPTANCE]
    assert (loop.state, loop.outcome) == ("closed", "worked")


def test_an_ordinary_delivery_is_closed_by_anybody_s_verdict_beside_a_release_that_waits(
        table, ledger, released):
    """The carve-out is the release's alone (#273): with a release and an ordinary delivery both
    waiting, a "funcionou" from somebody off the admin list settles the newer one — the delivery
    — exactly as before, closes it as `worked` and names it; the release is not touched, released
    or closed."""
    project = _project()
    _awaiting_release(ledger, ts="2026-09-20T10:00:00+00:00")
    delivery = _awaiting_acceptance(ledger, subject="7", ts="2026-09-21T10:00:00+00:00")
    talk = _Conversation(project, _Module(project))

    reply = talk.say("funcionou", user=CLIENT)

    assert reply == followup.accepted_text(delivery, agent_name=AGENT, ambiguous=True)
    assert released == []
    closed = {x.subject: (x.state, x.outcome) for x in fold(ledger) if x.kind == ACCEPTANCE}
    assert closed == {"7": ("closed", "worked"), "release-12": ("open", "")}


# ── 12. one conversation per room, one per thread ──────────────────────────────────────────────
#
# WHICH conversation a message belongs to is the transport's to say (`conversation_key`, a Slack
# event parser — pinned in tests/test_transcript_memory.py). What is pinned here is what the
# handler does with the key it is given.

def test_the_second_bare_message_carries_the_first_exchange_into_the_prompt(table, ledger):
    """Two bare messages are one conversation — the room — so the second one's prompt holds the
    first message and her answer to it, and not the second message itself, which is the
    question."""
    project = _project()
    module = _Module(project)
    talk = _Conversation(project, module)
    first = "o extrato conciliado pode ser editado?"
    talk.say(first, user=CLIENT, thread=ROOM)

    talk.say("e o de ontem?", user=CLIENT, thread=ROOM)

    remembered = module.asked("answer")[1]["conversation"]
    assert first in remembered and PLAIN.text in remembered, remembered
    assert "e o de ontem?" not in remembered


def test_a_reply_inside_a_thread_remembers_what_was_said_at_room_level(table, ledger):
    """The conversation of a thread is the thread PLUS the room's rolling exchange, so a reply in a
    fresh thread still sees the question asked at room level a moment before."""
    project = _project()
    module = _Module(project)
    talk = _Conversation(project, module)
    first = "o extrato conciliado pode ser editado?"
    talk.say(first, user=CLIENT)

    talk.say("e o de ontem?", user=CLIENT, thread=THREAD, channel=ROOM)

    assert first in module.asked("answer")[1]["conversation"]


def test_a_bare_yes_at_room_level_confirms_a_proposal_staged_inside_a_thread(table, ledger):
    """A person confirms wherever they happen to type: a proposal made inside a thread is found by
    a bare "sim" at room level and performed from the key it was staged under."""
    project = _project()
    module = _asking(project)
    talk = _Conversation(project, module)
    talk.say(REQUEST, user=CLIENT, thread=THREAD, channel=ROOM)
    assert staging.pending_for(THREAD) is not None and staging.pending_for(ROOM) is None

    talk.say("sim", user=ADMIN)

    assert [p["actor"] for p in module.asked("propose")] == [ADMIN]
    assert staging.pending_for(THREAD, project=project) is None


def test_where_a_message_came_from_travels_onto_what_it_stages_and_what_is_written(table,
                                                                                 ledger):
    """`source` — the permalink a transport hands over — is staged with the draft and the defect
    it produced, and reaches the write on the yes: it is the provenance a requirement or a filed
    problem carries back to the conversation."""
    project = _project()
    module = _Module(project, replies={"PDF": ASKED_FOR, "duplicando": READ_AS_DEFECT},
                     drafted=DRAFTED)
    talk = _Conversation(project, module)
    source = "https://chat.example/archives/C0PROD/p1726000000000200"

    talk.say(REQUEST, user=CLIENT, source=source)
    assert staging.pending_for(ROOM)["source"] == source
    talk.say("sim", user=ADMIN)
    talk.say(BROKEN, user=CLIENT, source=source)
    assert staging.pending_for(ROOM)["source"] == source
    talk.say("sim", user=ADMIN)

    assert [p["source"] for p in module.asked("propose")] == [source]
    assert [d["source"] for d in module.asked("file_defect")] == [source]


# ── 13. when the module cannot answer ───────────────────────────────────────────────────────────

def test_a_base_that_cannot_be_read_is_said_plainly_with_no_receipt_and_no_model(table, ledger):
    """The corpus cannot be read: the reply is the client's sentence for that (the diagnosis stays
    with the team), the model is not asked, and no receipt promised an answer that is not
    coming. Both turns are still recorded."""
    project = _project()
    module = _Module(project, available=False)
    talk = _Conversation(project, module)
    question = "o extrato conciliado pode ser editado?"

    reply = talk.say(question, user=CLIENT)

    assert reply == voice.unavailable(language=LANG)
    assert "answer" not in module.verbs() and talk.receipts == []
    assert table.turns(ROOM) == [("person", question, CLIENT), ("agent", reply, "")]


def test_an_answer_the_model_could_not_give_is_the_same_sentence(table, ledger):
    """The model was asked and did not answer: the same unavailable sentence — the receipt had
    already gone out, before the model was asked."""
    project = _project()
    question = "o extrato conciliado pode ser editado?"
    module = _Module(project, replies={"conciliado": ProductAnswer(ok=False, error="timeout")})
    talk = _Conversation(project, module)

    reply = talk.say(question, user=CLIENT)

    assert reply == voice.unavailable(language=LANG)
    assert talk.receipts == [_receipt(question)]


def test_a_crash_inside_the_turn_is_answered_never_raised(table, ledger, caplog):
    """Anything that raises inside the turn is caught: the person hears the honest "something
    broke on my side", the marker one alarm pages on is logged, and both turns — the message that
    broke it included — are in the transcript."""
    project = _project()

    class _Crashing(_Module):
        def answer(self, question, **_kw):
            raise RuntimeError("the harness died")

    talk = _Conversation(project, _Crashing(project))

    with caplog.at_level("ERROR", logger="openfactory.product.engine"):
        reply = talk.say("isto quebra", user=CLIENT)

    assert reply == voice.broke(language=LANG)
    assert any("OPENFACTORY_PRODUCT_MUTE" in r.getMessage() for r in caplog.records)
    assert table.turns(ROOM) == [("person", "isto quebra", CLIENT), ("agent", reply, "")]


def _raises(*_a, **_kw):
    raise RuntimeError("this seam broke")


def _person_turn_not_recorded(monkeypatch, _module) -> None:
    from openfactory.memory import transcript

    real = transcript.record

    def record(name, *, role, **kw):
        if role == "person":
            raise RuntimeError("the sink refused the person's turn")
        return real(name, role=role, **kw)

    monkeypatch.setattr(transcript, "record", record)


def _decisions_not_closed(monkeypatch, module) -> None:
    monkeypatch.setattr(module, "close_decisions_answered", _raises)


def _decisions_not_recorded(monkeypatch, module) -> None:
    monkeypatch.setattr(module, "record_decisions", _raises)


def _intake_not_noted(monkeypatch, _module) -> None:
    monkeypatch.setattr(intake, "note_turn", _raises)


ASKS = ProductAnswer(ok=True, text="Preciso que vocês decidam isso.",
                     decisions=["fechar ou não os cards em Review"])


@pytest.mark.parametrize("breaks", [_person_turn_not_recorded, _decisions_not_closed,
                                    _decisions_not_recorded, _intake_not_noted],
                         ids=["the-person-s-turn", "closing-the-decisions",
                              "recording-the-decisions", "the-intake-case"])
def test_bookkeeping_that_fails_costs_its_own_record_and_never_the_reply(breaks, table, ledger,
                                                                         monkeypatch, caplog):
    """Each of these is bookkeeping about the turn, and each is caught where it happens: the
    person gets the role's answer, never "algo quebrou do meu lado", and nothing pages."""
    project = _project()
    module = _Module(project, replies={"backlog": ASKS})
    breaks(monkeypatch, module)
    talk = _Conversation(project, module)

    with caplog.at_level("WARNING"):
        reply = talk.say("organiza o backlog", user=CLIENT)

    assert reply == ASKS.text
    assert not any("OPENFACTORY_PRODUCT_MUTE" in r.getMessage() for r in caplog.records)


def test_a_judge_that_raises_leaves_the_proposal_pending_and_the_turn_answered(table, ledger):
    """An unreadable judgment is "neither": the proposal stays staged — nothing approved, nothing
    destroyed — and the sentence is answered as conversation with the proposal still pending."""
    project = _project()
    module = _asking(project)
    module.confirmed = _raises
    talk = _Conversation(project, module)
    talk.say(REQUEST, user=CLIENT)
    staged = staging.pending_for(ROOM)

    reply = talk.say("manda ver com esse título mesmo", user=ADMIN)

    assert reply == PLAIN.text
    assert staging.pending_for(ROOM) is staged
    assert module.asked("answer")[-1]["pending"] == staging._proposal_summary(staged)
    assert not module.asked("propose")


def test_buttons_the_transport_failed_to_post_come_back_as_prose(table, ledger, monkeypatch):
    """The buttons are optional; the proposal is not. A transport whose `confirm` raises gets the
    proposal back as prose, still staged for a typed yes."""
    project = _project()
    talk = _Conversation(project, _asking(project))
    monkeypatch.setattr(talk, "_offer", _raises)

    reply = talk.say(REQUEST, user=CLIENT)

    assert reply == _offered_draft()
    assert staging.pending_for(ROOM) is not None


# ── 14. a reply that claims a write ─────────────────────────────────────────────────────────────

def test_a_reply_claiming_a_write_is_logged_and_sent_unchanged(table, ledger, caplog):
    """The turn wrote nothing and the role's reply says it did: that is OBSERVED — a warning with
    the claim, which production has only ever seen fire on correct sentences — and the reply goes
    out exactly as the role wrote it, with nothing staged and nothing written."""
    project = _project()
    claimed = ProductAnswer(ok=True, text="Registrei o requisito 5 na base.")
    module = _Module(project, replies={"registrou": claimed})
    talk = _Conversation(project, module)

    with caplog.at_level("WARNING", logger="openfactory.product.engine"):
        reply = talk.say("você registrou aquilo?", user=CLIENT)

    assert reply == claimed.text
    flagged = [r.getMessage() for r in caplog.records
               if "OPENFACTORY_PRODUCT_FALSE_CLAIM" in r.getMessage()]
    assert len(flagged) == 1 and "claim='Registrei'" in flagged[0], flagged
    assert staging.pending_for(ROOM) is None
    assert not _writes(module)


# ── what she asks a person, and what closes it ─────────────────────────────────────────────────

def test_what_she_asks_a_person_to_decide_becomes_a_loop_about_this_conversation(table,
                                                                                ledger):
    """A decision the role asks for in its reply is opened as a DECISION loop, about the
    conversation it was asked in, with the question kept to chase it by; the marker never reaches
    the person (the reply is the role's text)."""
    project = _project()
    module = _Module(project, replies={"backlog": ASKS})
    talk = _Conversation(project, module)

    reply = talk.say("organiza o backlog", user=CLIENT)

    assert reply == ASKS.text
    [loop] = [x for x in waiting(fold(ledger), owner=followup.OWNER) if x.kind == DECISION]
    assert loop.about == ROOM
    assert loop.context.get("asked") == "fechar ou não os cards em Review"


def test_any_message_she_reads_closes_EVERY_open_decision_of_the_project(table, ledger):
    """TODAY'S RULE, AND #266 §3 NAMES IT A SCOPING DEFECT. A decision she asked of somebody in
    ANOTHER conversation is closed as `answered` by an unrelated person's message in this one:
    `close_decisions_answered` takes the channel and filters nothing by it. The close happens
    before the model is asked, so her reply cannot open what it closes. #266 slice 4 scopes it to
    the conversation and the person the decision was asked of — this test flips then, on purpose."""
    project = _project()
    module = _Module(project)
    module.record_decisions(["qual banco entra primeiro"], channel="C0ELSEWHERE")
    talk = _Conversation(project, module)

    talk.say("bom dia, tudo certo por aí?", user=OTHER)

    assert not [x for x in waiting(fold(ledger), owner=followup.OWNER) if x.kind == DECISION]
    [closed] = [x for x in fold(ledger) if x.kind == DECISION]
    assert (closed.about, closed.outcome) == ("C0ELSEWHERE", "answered")
    verbs = module.verbs()
    assert verbs.index("close_decisions_answered") < verbs.index("answer")


# ── the intake ──────────────────────────────────────────────────────────────────────────────────

def test_the_second_turn_of_an_intake_carries_the_first_as_typed_facts(table, ledger):
    """Each turn of a person in a conversation joins their intake case, and from the second turn
    on the model is handed that case — what they said so far — so a follow-up is read as a
    continuation. Another person in the same room starts from nothing."""
    project = _project()
    module = _Module(project)
    talk = _Conversation(project, module)
    first = "o relatório de fechamento está saindo errado"

    talk.say(first, user=CLIENT)
    talk.say("é o de março", user=CLIENT)
    talk.say("aqui também", user=OTHER)

    intakes = [kw["intake"] for kw in module.asked("answer")]
    assert intakes[0] is None
    assert intakes[1].startswith("## This intake so far") and f"- {first}" in intakes[1], intakes
    assert intakes[2] is None
