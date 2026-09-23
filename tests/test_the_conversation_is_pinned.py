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
explains away. Two were found while writing this and no slice names them, so they are pinned as
found and flagged for a decision of their own: a typed "não" is recorded in the durable store as
an approval, and a refused "funcionou" on a release closes the release loop anyway.

THE HARNESS IS TRANSPORT-NEUTRAL, and it is the only thing slice 2 should have to touch:

  - `_Conversation.say` is the ONE place a message enters. It hands the handler what any transport
    hands it — the text, who said it, the conversation it belongs to — and records the two
    callbacks a chat surface supplies (`notify`, the receipt; `confirm`, the buttons) instead of
    rendering them. Pointed at the engine, every test below should read the same.
  - Only what leaves the process is replaced: the model, the writes, the board. `_Module` answers
    from a script and records every verb it is asked for, so an assertion is about the act (which
    verb, with what) and never about a sentence the double made up. The three verbs that keep the
    ledger — `settle_acceptance`, `record_decisions`, `close_decisions_answered` — are
    `ProductModule`'s own, run against the ledger as a list: the seam `test_decision_loop` and
    `test_acceptance_loop` already use.
  - The transcript and the durable staging mirror (`memory.messages`) land in one in-memory
    telemetry table, patched at the two seams production resolves — the sink door
    (`tests/the_sink_door.py`) and the query — so a turn's record is read back, not assumed.
  - A sentence the voice composes is compared with its composer (`product/voice.py`,
    `product/followup.py`), not with a copy of its wording: what is pinned is which sentence the
    conversation says and how the pieces are put together, while the wording stays the voice's.
    The few the handler writes itself — the admins' note under a staged proposal, the release —
    are compared with their text.

Each flow has at least one row in `tools/mutations/266_the_conversation_is_pinned.py` that cuts
the line it depends on; 62 rows, every one red against this file (2026-09-24).
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

import openfactory.memory.store as loop_store
from openfactory.contracts.product import ProductConfig
from openfactory.contracts.project import Project
from openfactory.memory import messages
from openfactory.memory.ledger import ACCEPTANCE, DECISION, DELIVERY, fold, open_loop, waiting
from openfactory.memory.transcript import TRANSCRIPT_KIND
from openfactory.product import channel as pc
from openfactory.product import followup, staging, voice
from openfactory.product.authoring import WriteResult
from openfactory.product.config import ProductLink
from openfactory.product.corpus import Corpus, Requirement
from openfactory.product.loader import ProductContext
from openfactory.product.module import ProductModule, unauthorized_message
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


class _Module:
    """The product module with what leaves the process replaced — the model, the writes, the
    board — and the ledger's own verbs left real.

    `replies` maps a phrase to the answer the role gives any message containing it; anything else
    gets `PLAIN`. Every verb the conversation reaches is recorded in `calls`, in order. NOT a
    subclass: a verb this double does not declare raises, the handler answers "algo quebrou", and
    the test says so — rather than a real `ProductModule` method quietly reaching a forge."""

    def __init__(self, project, *, available: bool = True, replies: dict | None = None,
                 drafted: ProductAnswer | None = None, verdict: str = "neither") -> None:
        self.project = project
        self.calls: list[tuple[str, dict]] = []
        self.replies = replies or {}
        self.drafted = drafted
        #: what the judge says of a reply the word list cannot read (`confirmed`)
        self.verdict = verdict
        self._board_tickets: list = []
        self._ctx = ProductContext(
            link=ProductLink(active=available, docs_repo="a/b",
                             reason="" if available else "o repositório a/b não respondeu"),
            corpus=Corpus(requirements=[Requirement(number=4, slug="pro-labore",
                                                    path="requirements/0004-pro-labore.md",
                                                    title="Pró-labore")]))

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

    def record_decisions(self, labels, *, channel=""):
        self._record("record_decisions", labels=list(labels), channel=channel)
        return ProductModule.record_decisions(self, labels, channel=channel)

    def close_decisions_answered(self, *, channel=""):
        self._record("close_decisions_answered", channel=channel)
        return ProductModule.close_decisions_answered(self, channel=channel)

    # ── the model ────────────────────────────────────────────────────────────────────────────────
    def context(self, **_kw):
        return self._ctx

    def _judge_acceptance(self, text):
        self._record("judge_acceptance", text=text)
        return ""

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

    # ── the writes: recorded, never performed ───────────────────────────────────────────────────
    def propose(self, answer, *, actor, asked_by="", date="", source=""):
        self._record("propose", answer=answer, actor=actor, asked_by=asked_by, date=date,
                     source=source)
        return WriteResult(ok=True, url="https://forge.example/pull/5", number=5)

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

    # ── the board reads ─────────────────────────────────────────────────────────────────────────
    def triage_board(self, **_kw):
        self._record("triage_board")
        return TriageReport(), ""

    def propose_queue(self, **_kw):
        self._record("propose_queue")
        return Readiness(), QueueProposal(items=[Proposed(ticket="12")]), ""


#: The verbs that change something outside the conversation. None of them may run on a turn that
#: was not a confirmed yes.
WRITES = ("propose", "file_defect", "file_ticket", "record_decision", "note_fact", "reorder",
          "promote")


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

    def say(self, text: str, *, user: str, thread: str = ROOM, channel: str = ROOM):
        """THE ONE PLACE THIS SUITE REACHES THE HANDLER. #266 slice 2 points it at the turn
        engine; nothing else in this file names `handle`."""
        return pc.handle(self.project, text=text, user=user, thread=thread, module=self.module,
                         channel=channel, notify=self.receipts.append, confirm=self._offer)


def _receipt(text: str) -> str:
    """The receipt a message seeds — what `notify` is handed before the slow part."""
    return voice.on_it(language=LANG, agent_name=AGENT, seed=text)


REQUEST = "preciso exportar o extrato em PDF"
DRAFTED = ProductAnswer(ok=True, draft=RequirementDraft(
    title="Exportar o extrato em PDF",
    must_be_true=["o extrato exportado mostra o mesmo saldo da tela"]))
ASKED_FOR = ProductAnswer(ok=True, text="Hoje não exportamos em PDF.", is_request=True)


def _asking(project, **kw) -> _Module:
    """A module whose role hears REQUEST as a request and drafts it."""
    return _Module(project, replies={"PDF": ASKED_FOR}, drafted=DRAFTED, **kw)


def _offered_draft() -> str:
    return (f"{ASKED_FOR.text}\n\n" + voice.confirmation_request(
        title=DRAFTED.draft.title, must_be_true=DRAFTED.draft.must_be_true, conflicts=[],
        language=LANG))


# ── 1. a question ───────────────────────────────────────────────────────────────────────────────

def test_a_question_is_answered_with_the_role_s_words_and_both_turns_are_recorded(table,
                                                                                   ledger):
    """A plain question: the person's turn recorded on arrival with who said it, ONE receipt
    before the model, the role's text returned untouched, the agent's turn recorded after — and
    nothing staged, nothing written. The order of the verbs is the stage order: settle (the
    acceptance check, which asks the judge because the word list reads nothing here), then the
    decisions she asked for are closed, then the answer."""
    project = _project()
    module = _Module(project)
    talk = _Conversation(project, module)
    question = "o extrato conciliado pode ser editado?"

    reply = talk.say(question, user=CLIENT)

    assert reply == PLAIN.text
    assert table.turns(ROOM) == [("person", question, CLIENT), ("agent", PLAIN.text, "")]
    assert talk.receipts == [_receipt(question)]
    assert module.verbs() == ["settle_acceptance", "judge_acceptance",
                              "close_decisions_answered", "answer"]
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
    assert not [v for v in module.verbs() if v in WRITES]


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
    would have."""
    project = _project()
    module = _asking(project, verdict="approve")
    talk = _Conversation(project, module)
    talk.say(REQUEST, user=ADMIN)
    summary = staging._proposal_summary(staging.pending_for(ROOM))

    talk.say("manda ver com esse título mesmo", user=ADMIN)

    assert module.asked("confirmed") == [{"reply": "manda ver com esse título mesmo",
                                          "proposal": summary}]
    assert [p["actor"] for p in module.asked("propose")] == [ADMIN]


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


# ── 4. a typed no rejects it ────────────────────────────────────────────────────────────────────

def test_the_requester_s_no_destroys_the_draft_and_is_answered_as_the_correction(table, ledger):
    """The person whose request it is may take it back — no admin needed for that — and what they
    wrote is answered as the correction it usually is: the model receives it with the discarded
    proposal gone from the prompt. An admin's later "sim" finds nothing and writes nothing.

    THE DURABLE RECORD OF THIS "NÃO" READS `approve`, and that looks wrong: the rejection calls
    `consume` with `approved=True` (the approval's compare-and-swap, reused), so the panel's
    store records the requester's typed no under the approvals' word. No slice of #266 names it;
    pinned as found, so changing it is a decision taken on its own."""
    project = _project()
    module = _asking(project)
    talk = _Conversation(project, module)
    talk.say(REQUEST, user=CLIENT)
    token = staging.proposal_token(ROOM, staging.pending_for(ROOM))

    reply = talk.say("não, não é isso", user=CLIENT)

    assert reply == PLAIN.text
    last = module.asked("answer")[-1]
    assert (last["question"], last["pending"]) == ("não, não é isso", "")
    assert staging.pending_for(ROOM, project=project) is None
    decided = messages.answer_of(PROJECT, token)
    assert decided is not None and (decided.answer, decided.by) == ("approve", CLIENT)

    talk.say("sim", user=ADMIN)

    assert not module.asked("propose"), "a yes resurrected a draft its requester had refused"


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


# ── 6. an expired proposal ──────────────────────────────────────────────────────────────────────

def test_a_yes_after_the_proposal_aged_out_hears_so_and_writes_nothing(table, ledger,
                                                                      monkeypatch):
    """Past the staging TTL, a "sim" is told the proposal expired — not answered by the model as
    if nothing had been staged, and never performed."""
    project = _project()
    module = _asking(project)
    talk = _Conversation(project, module)
    talk.say(REQUEST, user=CLIENT)
    later = time.time() + staging.PROPOSAL_TTL_SECONDS + 60
    monkeypatch.setattr(staging, "time", SimpleNamespace(time=lambda: later))

    reply = talk.say("sim", user=ADMIN)

    assert reply == voice.proposal_expired(language=LANG)
    assert not module.asked("propose")
    assert len(module.asked("answer")) == 1, "the late yes was answered by the model"


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
        f"\n\n(<@{ADMIN}>: a decisão precisa da sua confirmação.)")
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
    who SAID it; the admin's yes writes it, and nothing is written before."""
    project = _project()
    module = _Module(project)
    talk = _Conversation(project, module)
    fact = "o fechamento roda sempre no quinto dia útil"

    reply = talk.say(f"anota que {fact}", user=CLIENT)

    term = pc._term_of(fact)
    assert reply == voice.fact_confirmation(term=term, body=fact, language=LANG) + (
        f"\n\n(<@{ADMIN}>: a anotação precisa da sua confirmação.)")
    assert not module.asked("note_fact")

    done = talk.say("sim", user=ADMIN)

    assert module.asked("note_fact") == [{"term": term, "body": fact, "said_by": f"<@{CLIENT}>",
                                          "where": ""}]
    assert done == voice.fact_noted(term=term, language=LANG)


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
                     + f"\n\n(<@{ADMIN}>: o registro precisa da sua confirmação.)")
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
                     + f"\n\n(<@{ADMIN}>: abrir o cartão precisa da sua confirmação.)")
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
                     + f"\n\n(<@{ADMIN}>: gravar a ordem precisa da sua confirmação.)")
    assert staging.pending_for(ROOM)["numbers"] == ["12", "7"]

    done = talk.say("sim", user=ADMIN)

    assert module.asked("reorder") == [{"numbers": ["12", "7"], "actor": ADMIN}]
    assert done == voice.reordered(["12", "7"], language=LANG, agent_name=AGENT)


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


# ── 11. the acceptance loop ─────────────────────────────────────────────────────────────────────

def _awaiting_acceptance(ledger) -> object:
    loop = open_loop(ACCEPTANCE, "7", owner=followup.OWNER, about=ROOM,
                     ts="2026-09-20T10:00:00+00:00", context={"asked_by": CLIENT})
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


@pytest.fixture()
def released(monkeypatch) -> list:
    calls: list = []

    def _release(project, issue, *, approver, comment=""):
        calls.append((str(issue), approver))
        return True, ""

    monkeypatch.setattr("openfactory.product.release.release", _release)
    return calls


def _awaiting_release(ledger) -> None:
    ledger.append(followup.release_of("12", channel=ROOM, ts="2026-09-20T10:00:00+00:00",
                                      requirement="0004", where="https://staging.example"))


def test_it_worked_on_a_RELEASE_puts_it_live_with_the_admin_as_the_approver(table, ledger,
                                                                          released):
    """The one acceptance that spends: an admin's "funcionou o #12" on a release loop releases
    that issue, with that admin recorded as the approver, and says it is going live."""
    project = _project()
    _awaiting_release(ledger)
    talk = _Conversation(project, _Module(project))

    reply = talk.say("funcionou o #12", user=ADMIN)

    assert released == [("12", ADMIN)]
    assert reply == (f"{AGENT}: perfeito — **estou subindo para produção agora**, com o seu "
                     f"\"funcionou\" como aprovação. Fica registrado que foi você quem liberou e "
                     f"quando. Eu volto aqui quando estiver no ar.")


def test_it_worked_on_a_RELEASE_from_someone_who_may_not_approve_releases_nothing_and_CLOSES_it(
        table, ledger, released):
    """Anyone off the admin list is refused out loud and nothing is released.

    AND THE LOOP IS CLOSED ANYWAY, which looks wrong. `settle_acceptance` writes the verdict to the
    ledger BEFORE `_maybe_release` asks who is speaking, so the refused "funcionou" closes the
    release loop as `worked`; an admin's "funcionou o #12" afterwards finds nothing awaiting an
    answer, is read as conversation, and releases nothing. No slice of #266 names this; it is
    pinned as found, so changing it is a decision taken on its own."""
    project = _project()
    _awaiting_release(ledger)
    module = _Module(project)
    talk = _Conversation(project, module)

    refused = talk.say("funcionou o #12", user=CLIENT)

    assert refused == unauthorized_message(project)
    assert released == []
    [loop] = [x for x in fold(ledger) if x.kind == ACCEPTANCE]
    assert (loop.state, loop.outcome) == ("closed", "worked")

    talk.say("funcionou o #12", user=ADMIN)

    assert released == [], "the admin's answer reached a loop the refusal had already closed"
    assert "answer" in module.verbs()


# ── 12. one conversation per room, one per thread ──────────────────────────────────────────────

def test_a_bare_message_belongs_to_the_room_s_rolling_conversation_and_a_reply_to_its_thread():
    """The key everything else is staged and remembered under: a message outside any thread
    belongs to the ROOM — never to its own timestamp, which made every bare message a new
    conversation — and a message inside a thread belongs to that thread."""
    assert pc.conversation_key({"ts": "1726000000.000200"}, ROOM) == ROOM
    assert pc.conversation_key({"ts": "1726000000.000300", "thread_ts": THREAD},
                                    ROOM) == THREAD


def test_the_second_bare_message_carries_the_first_exchange_into_the_prompt(table, ledger):
    """Two bare messages are one conversation: the second one's prompt holds the first message
    and her answer to it, and not the second message itself, which is the question."""
    project = _project()
    module = _Module(project)
    talk = _Conversation(project, module)
    first = "o extrato conciliado pode ser editado?"
    talk.say(first, user=CLIENT,
             thread=pc.conversation_key({"ts": "1726000000.000200"}, ROOM))

    talk.say("e o de ontem?", user=CLIENT,
             thread=pc.conversation_key({"ts": "1726000000.000300"}, ROOM))

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

    with caplog.at_level("ERROR", logger="openfactory.product.channel"):
        reply = talk.say("isto quebra", user=CLIENT)

    assert reply == voice.broke(language=LANG)
    assert any("OPENFACTORY_PRODUCT_MUTE" in r.getMessage() for r in caplog.records)
    assert table.turns(ROOM) == [("person", "isto quebra", CLIENT), ("agent", reply, "")]


# ── 14. a reply that claims a write ─────────────────────────────────────────────────────────────

def test_a_reply_claiming_a_write_is_logged_and_sent_unchanged(table, ledger, caplog):
    """The turn wrote nothing and the role's reply says it did: that is OBSERVED — a warning with
    the claim, which production has only ever seen fire on correct sentences — and the reply goes
    out exactly as the role wrote it, with nothing staged and nothing written."""
    project = _project()
    claimed = ProductAnswer(ok=True, text="Registrei o requisito 5 na base.")
    module = _Module(project, replies={"registrou": claimed})
    talk = _Conversation(project, module)

    with caplog.at_level("WARNING", logger="openfactory.product.channel"):
        reply = talk.say("você registrou aquilo?", user=CLIENT)

    assert reply == claimed.text
    flagged = [r.getMessage() for r in caplog.records
               if "OPENFACTORY_PRODUCT_FALSE_CLAIM" in r.getMessage()]
    assert len(flagged) == 1 and "claim='Registrei'" in flagged[0], flagged
    assert staging.pending_for(ROOM) is None
    assert not [v for v in module.verbs() if v in WRITES]


# ── what she asks a person, and what closes it ─────────────────────────────────────────────────

def test_what_she_asks_a_person_to_decide_becomes_a_loop_about_this_conversation(table,
                                                                                ledger):
    """A decision the role asks for in its reply is opened as a DECISION loop, about the
    conversation it was asked in, with the question kept to chase it by; the marker never reaches
    the person (the reply is the role's text)."""
    project = _project()
    asks = ProductAnswer(ok=True, text="Preciso que vocês decidam isso.",
                         decisions=["fechar ou não os cards em Review"])
    module = _Module(project, replies={"backlog": asks})
    talk = _Conversation(project, module)

    reply = talk.say("organiza o backlog", user=CLIENT)

    assert reply == asks.text
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
