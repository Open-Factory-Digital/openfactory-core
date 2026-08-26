"""The conversation actually reaches the model — ADR-0024, layers 0 and 1.

THE DEFECT THIS GUARDS IS THE ONE THIS REPOSITORY KEEPS SHIPPING. A transcript module with perfect
unit tests, called by nothing, is indistinguishable from the amnesia it replaces: every test green,
every reply polite, and the agent still answering "e o segundo?" as if it were the first message.
`people.mention` shipped exactly that way and addressed every question to an empty room for weeks.

So the assertions here are about REACH, in order of how easy each is to fake:

  1. production code calls record() and recent() at all;
  2. a real message through `handle()` lands two rows — what was said AND what was answered;
  3. the SECOND message carries the first in the text that goes to the model;
  4. and it sits in the right place in that text, because prompt caching is prefix-based.

The fakes are boundary-only — the telemetry sink and the query. Everything between them is
production code.
"""

from __future__ import annotations

import ast
from pathlib import Path

import add_ons
import pytest

import openfactory.observability.query as query_mod
import openfactory.runtime.temporal.activities as activities_mod
from openfactory.contracts.product import ProductConfig
from openfactory.contracts.project import Project, ProviderRef
from openfactory.memory import transcript


class _Sink:
    def __init__(self):
        self.rows: list = []

    def record(self, rec):
        self.rows.append(rec)


def _project():
    return Project(name="books", repo_path="/t", language="pt-BR",
                   tracker=ProviderRef(kind="github", repo="a/b"),
                   forge=ProviderRef(kind="github", repo="a/b"),
                   product=ProductConfig(docs_repo="a/docs", channel_id="C0",
                                         agent_name="Nina"))


@pytest.fixture()
def store(monkeypatch):
    """The append-only table as a list, wired at both ends so writes are readable."""
    import openfactory.product.authoring as authoring

    sink = _Sink()
    monkeypatch.setattr(activities_mod, "_metrics_sink", lambda *a, **k: sink)
    # never a live forge from a unit test — same seam fake as test_acceptance_loop's fixture.
    # It used to be `authoring._gh`, one layer down; the proposal sweep speaks to the port now
    # (#95), so `land_open_proposals` is where production and this fake meet.
    monkeypatch.setattr(authoring, "land_open_proposals", lambda **kw: [])

    def _read(project, kind, *, limit=500, **kw):
        return [{"ticket": r.ticket, "role": r.role, "ts": r.ts, "extra": r.extra}
                for r in sink.rows if r.project == project and r.kind == kind][-limit:]

    monkeypatch.setattr(query_mod, "records_of_kind", _read)
    return sink


# ── 1. reach ───────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("fn", ["record", "recent", "render"])
def test_production_code_calls_it(fn):
    """Not "a test calls it" — production. The whole module is worthless otherwise."""
    callers = []
    for path in Path("openfactory").rglob("*.py"):
        if path.name == "transcript.py" or "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == fn:
                callers.append(str(path))
    assert callers, f"transcript.{fn}() is called by no production code — it is decoration"


# ── 2. the raw log ─────────────────────────────────────────────────────────────────────────────
def test_a_message_and_its_reply_are_both_recorded(store, monkeypatch):
    """Layer 0 is written at the BOUNDARY, so a path that never reaches the model is still in the
    record. `status` is exactly such a path — it answers from the board without an agent run."""
    import openfactory.product.channel as pc

    class _Module:
        def settle_acceptance(self, text):
            return None

        def status_line(self):
            return "3 em andamento"

    monkeypatch.setattr(pc, "_waiting_line", lambda project: "")
    reply = pc.handle(_project(), text="como estamos?", user="U1", thread="T1",
                      module=_Module(), source="")

    assert reply, "the shortcut answered nothing"
    kinds = [(r.role, r.extra["text"]) for r in store.rows if r.kind == "message"]
    assert ("person", "como estamos?") in kinds, kinds
    assert any(role == "agent" for role, _ in kinds), f"her own words were not recorded: {kinds}"


def test_a_crash_answers_honestly_and_still_records(store, monkeypatch, caplog):
    """The handler swallows exceptions so the socket survives — but SILENCE IS THE WORST ANSWER.
    Returning None meant the person wrote to their PO and got nothing, indistinguishable from
    being ignored and invisible until they complained. Three things must happen: an honest reply,
    a marker one alarm can page on, and the verbatim record of the message that broke her."""
    import openfactory.product.channel as pc

    monkeypatch.setattr(pc, "_handle", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with caplog.at_level("ERROR"):
        reply = pc.handle(_project(), text="isto quebra", user="U1", thread="T9", module=None)

    assert reply, "the client was left in silence"
    assert "quebrou do meu lado" in reply, reply
    assert "requisitos" not in reply, "a crash must not be reported as an unreadable corpus"
    assert any("OPENFACTORY_PRODUCT_MUTE" in r.getMessage() for r in caplog.records), \
        "nothing an alarm can see"

    said = [r.extra["text"] for r in store.rows if r.kind == "message"]
    assert "isto quebra" in said, f"the message that broke her was lost: {said}"


# ── 3. working memory reaches the model ────────────────────────────────────────────────────────
def test_the_second_message_carries_the_first_INTO_THE_PROMPT(store, monkeypatch):
    """The assertion that matters: not that `recent()` returns rows, but that the prior turn is in
    the string handed to the agent. Everything upstream can be right and this still be empty."""
    import openfactory.product.channel as pc

    seen: dict = {}

    class _Module:
        def settle_acceptance(self, text):
            return None  # nothing awaiting a "did it work?" in these cases

        def context(self):
            from types import SimpleNamespace
            return SimpleNamespace(available=True, reason="")

        def answer(self, question, *, context="", conversation="", **_):
            seen["question"], seen["conversation"] = question, conversation
            from types import SimpleNamespace
            return SimpleNamespace(ok=True, text="sim, o requisito 4 cobre isso",
                                   is_defect=False, asked_for_something=False)

    monkeypatch.setattr(pc, "_reply_of", lambda answer, **kw: answer.text, raising=False)

    project = _project()
    transcript.record(project.name, thread="T2", role="person",
                      text="o fechamento contábil já roda sozinho?", actor="U1")
    transcript.record(project.name, thread="T2", role="agent",
                      text="hoje não — está no requisito 4, ainda não aceito")

    pc.handle(project, text="e o segundo?", user="U1", thread="T2", module=_Module())

    convo = seen.get("conversation", "")
    assert "fechamento contábil" in convo, f"the prior question never reached the model: {convo!r}"
    assert "requisito 4" in convo, f"her own prior answer never reached the model: {convo!r}"
    assert "e o segundo?" not in convo, "the current message must not be duplicated into history"


def test_threads_do_not_bleed_into_each_other(store):
    """A channel is a room; a thread is an exchange. Keying on the room would answer one person
    with another person's context, confidently."""
    transcript.record("books", thread="A", role="person", text="pergunta sobre folha")
    transcript.record("books", thread="B", role="person", text="pergunta sobre estoque")

    only_a = transcript.render(transcript.recent("books", thread="A"))
    assert "folha" in only_a and "estoque" not in only_a, only_a


def test_the_budget_keeps_the_RECENT_end(store):
    """Dropping the newest turns to fit would keep the opening of a long conversation and lose what
    was just said — the half that actually carries the thread."""
    for i in range(40):
        transcript.record("books", thread="T3", role="person", text=f"turno {i} " + "x" * 300)

    turns = transcript.recent("books", thread="T3", budget=1000)

    assert turns, "the budget dropped everything"
    assert "turno 39" in turns[-1].text, f"the newest turn was dropped: {turns[-1].text[:40]}"
    assert sum(len(t.text) for t in turns) <= 1000 + 400, "the budget was not honoured"


def test_an_unreadable_store_answers_like_an_empty_one_but_says_so(monkeypatch, caplog):
    """Both return []. The caller MUST reply either way — but "could not read" and "nothing said"
    are opposite facts, and the log is where that difference survives."""
    def _boom(*a, **k):
        raise RuntimeError("dynamo down")

    monkeypatch.setattr(query_mod, "records_of_kind", _boom)
    with caplog.at_level("WARNING"):
        assert transcript.recent("books", thread="T4") == []
    assert any("could not read the transcript" in r.getMessage()
               for r in caplog.records), caplog.text


# ── 4. position in the prompt ──────────────────────────────────────────────────────────────────
def test_the_conversation_sits_after_the_stable_blocks_and_before_the_question():
    """Prompt caching is prefix-based: whatever changes every turn invalidates everything after it.
    Today there is no cache to lose; the order has to be right before there is."""
    from openfactory.product.role import ProductRole

    captured: dict = {}

    class _Role(ProductRole):
        def _prompt(self, instruction, body, **kw):
            captured["body"] = body
            return body

        def _ask(self, *a, **kw):
            from types import SimpleNamespace
            return SimpleNamespace(ok=False, raw_output="", summary="")

    _Role(agent=None).answer(  # type: ignore[arg-type]
        sandbox=None, workspace=None, question="e agora?",
        context="corpus com 2 problemas", conversation="## Conversa até aqui\npessoa: oi")

    body = captured["body"]
    assert body.index("Current state") < body.index("Conversa até aqui") < body.index("## Question"), \
        f"volatile blocks are out of order:\n{body}"


# ── 5. the turn is measured ────────────────────────────────────────────────────────────────────
def test_a_product_turn_writes_an_agent_run_row(store):
    """ADR-0024 §5. A scan of the live table found `executor` and `repair` and ZERO product rows —
    so the cost of talking to her was, literally, unknown while the product is sold on token
    efficiency. Injecting history makes each turn bigger; the claim that it also makes it cheaper
    is only checkable against rows that exist."""
    from openfactory.product.role import ProductRole

    class _Agent:
        name = "claude_code"

        def ask(self, **kw):
            from types import SimpleNamespace
            return SimpleNamespace(ok=True, raw_output="", summary="tudo certo",
                                   cost_usd=0.42, num_turns=3)

    ProductRole(_Agent(), project_name="books").answer(
        sandbox=None, workspace=None, question="e aí?")

    runs = [r for r in store.rows if r.kind == "agent_run"]
    assert runs, "a conversation with her still costs nothing measurable"
    assert runs[0].project == "books", f"a row nobody can attribute: {runs[0].project!r}"
    assert runs[0].cost_usd == 0.42, runs[0].cost_usd
    assert runs[0].role == "product_answer", runs[0].role


# ── 6. the REAL usage pattern: bare messages in the channel ────────────────────────────────────
# The first ten tests in this file all passed while the feature was DEAD in production use. They
# drove handle() with a fixed thread id — and the listener's key for a bare channel message was
# the message's OWN ts, so real usage produced a fresh "thread" every message and recent() always
# returned []. Built, tested, reached by nothing: the 14th instance, this time in MY OWN tests.
# Every test below keys messages the way the LISTENER does, via conversation_key.


def test_a_bare_message_keys_to_the_channel_not_to_itself():
    """The decision the whole feature hangs on. `thread_ts or ts` was memory that never fired."""
    from openfactory.product.channel import conversation_key

    bare = {"ts": "111.222"}
    threaded = {"ts": "333.444", "thread_ts": "111.222"}

    assert conversation_key(bare, "C0PROD") == "C0PROD", "a bare message IS the channel exchange"
    assert conversation_key(threaded, "C0PROD") == "111.222", "an in-thread reply stays threaded"


def test_the_listener_actually_uses_the_conversation_key():
    """Reach: the correct helper existing while bot.py still keys on `thread_ts or ts` is exactly
    the defect this file documents. The listener must call it."""
    import ast

    tree = ast.parse(add_ons.source("openfactory/runtime/slack/bot.py").read_text())
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "conversation_key"]
    assert calls, "bot.py no longer derives the product conversation via conversation_key"


def test_two_bare_channel_messages_are_ONE_conversation(store, monkeypatch):
    """The product owner's actual pattern, from the screenshots: bare message, bare follow-up.
    Keyed the way
    the listener keys them, the second must carry the first."""
    import openfactory.product.channel as pc
    from openfactory.product.channel import conversation_key

    seen: dict = {}

    class _Module:
        def settle_acceptance(self, text):
            return None  # nothing awaiting a "did it work?" in these cases

        def context(self):
            from types import SimpleNamespace
            return SimpleNamespace(available=True, reason="")

        def answer(self, question, *, context="", conversation="", **_):
            seen["conversation"] = conversation
            from types import SimpleNamespace
            return SimpleNamespace(ok=True, text="a conciliação cobre os dois bancos",
                                   is_defect=False, asked_for_something=False)

    monkeypatch.setattr(pc, "_reply_of", lambda answer, **kw: answer.text, raising=False)

    project, channel = _project(), "C0PROD"
    for text, ev in [("a conciliação já funciona?", {"ts": "1.0"}),
                     ("e para dois bancos?", {"ts": "2.0"})]:
        pc.handle(project, text=text, user="U1", module=_Module(),
                  thread=conversation_key(ev, channel), channel=channel)

    convo = seen.get("conversation", "")
    assert "a conciliação já funciona?" in convo, \
        f"bare message #2 forgot bare message #1 — the exact production failure: {convo!r}"


def test_a_reply_in_a_fresh_thread_still_sees_her_channel_level_question(store):
    """She asks at channel level (the sweep posts bare); the person replies INSIDE the thread of
    her question — a thread id the transcript has never seen. The union with the channel's rolling
    exchange is what lets her remember what she asked."""
    transcript.record("books", thread="C0PROD", role="agent",
                      text="sobre o Fechamento mensal: qual o prazo-limite?", channel="C0PROD")

    turns = transcript.recent("books", thread="9999.1", channel="C0PROD")

    assert any("prazo-limite" in t.text for t in turns), \
        "her own question is the one turn she cannot remember"


def test_the_sweep_records_what_she_posts(store, monkeypatch):
    """The proactive path: _product_followup's delivery notice must land in the transcript keyed by
    the channel. Driven through the production orchestration, not the helper in isolation."""
    import openfactory.adapters.channel as channel_pkg
    import openfactory.memory.store as loop_store
    from openfactory.memory.ledger import DELIVERY, open_loop
    from openfactory.product.triage import Ticket, TriageReport
    from openfactory.runtime.temporal.activities import _product_followup

    class _Channel:
        def say(self, *, project, channel, text):
            return True

        def mention(self, person, **kw):
            return person

        def client(self, project):
            return None

    rows = [open_loop(DELIVERY, "7", owner="product", ts="2026-07-28T10:00:00+00:00",
                      context={"issues": "500"})]
    monkeypatch.setattr(channel_pkg, "build_channel", lambda p=None: _Channel())
    monkeypatch.setattr(loop_store, "read", lambda project: list(rows))
    monkeypatch.setattr(loop_store, "write", lambda project, loops: len(loops))

    class _Module:
        _board_tickets = [Ticket(number=500, title="a", state="closed", column="Done", body="")]
        token = None

    _product_followup(_project(), _Module(), TriageReport(), _project().product)

    slack_channel = _project().product.channel_id
    hers = [r for r in store.rows
            if r.kind == "message" and r.role == "agent" and r.ticket == slack_channel]
    assert hers, "the delivery notice went to the channel and into no memory at all"
    assert "requisito 7" in hers[0].extra["text"], hers[0].extra["text"]


def test_a_bare_sim_finds_a_proposal_staged_two_messages_earlier(store, monkeypatch):
    """The latent twin of the memory hole: staging used the same key. A proposal made in a bare
    message was staged under that message's ts; a bare "sim" arrived under ITS ts; they never met,
    and the confirmation fell through to the conversational model — polite reply, nothing written.
    With both keyed to the channel, they meet. And an in-thread "sim" must find it too."""
    import openfactory.product.channel as pc
    from openfactory.product.channel import conversation_key

    noted: list = []

    class _Module:
        def settle_acceptance(self, text):
            return None  # nothing awaiting a "did it work?" in these cases

        def context(self):
            from types import SimpleNamespace
            return SimpleNamespace(available=True, reason="")

        def note_fact(self, *, term, body, said_by, where=""):
            noted.append(term)
            from types import SimpleNamespace
            return SimpleNamespace(ok=True, existed=False, detail="", ref="")

    project, channel = _project(), "C0PROD"
    project.product.admins = ["U1"]

    # she staged a fact from a bare message → key = channel
    pc.remember(conversation_key({"ts": "5.0"}, channel),
                {"kind": "fact", "term": "erp", "body": "a firma usa Primavera", "said_by": "U1"})
    # the person confirms INSIDE the thread of her reply → a different key
    reply = pc.handle(project, text="sim", user="U1", module=_Module(),
                      thread=conversation_key({"ts": "6.0", "thread_ts": "5.0"}, channel),
                      channel=channel)

    assert noted == ["erp"], f"the confirmation missed the staged fact (reply: {reply!r})"
    assert pc.pending_for(channel) is None, "consumed from the key it was staged under"
