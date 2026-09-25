"""One turn engine — #266 slice 2, ADR-0051 D12 and D13.

WHY THIS FILE EXISTS. The product conversation had four partial copies: the chat handler held the
whole of it and was called only by an external add-on; the panel's box reached a turn that drafted
and never settled; a second worker turn settled and never drafted and was called by nothing; and
the catalogue routed four intents a third way. That is how a typed "sim" came to confirm a draft in
one transport and not in the reference surface. Slice 2 relocated all of it into
`product/engine.py`, and what is pinned here is the SHAPE that relocation has to keep:

  - nothing outside the engine calls `ProductModule.answer` or `ProductRole.answer` — a guard, walked
    over the package, with a planted twin that proves the walker can see (the slice's acceptance);
  - the engine's contract is transport-neutral: a frozen `Message` in, `Reply`s out, no callbacks,
    and the chat adapter in front of it holds no judgement of its own;
  - each stage — settle, intents, converse, gestures, staging — can be called on its own;
  - the turn releases the module's per-turn view of the product when it ends, however it ends;
  - `ProductAskWorkflow`'s activity, kept registered for the workflows already in flight, runs no
    model and answers "ask again".

The behaviour itself — every flow, every incident-bearing branch — is pinned by
`tests/test_the_conversation_is_pinned.py`, which drives this engine through the neutral message.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from openfactory.contracts.product import ProductConfig
from openfactory.contracts.project import Project
from openfactory.product import engine, staging
from openfactory.product.role import ProductAnswer, RequirementDraft

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "openfactory"
ENGINE = PACKAGE / "product" / "engine.py"
CHANNEL = PACKAGE / "product" / "channel.py"
ADMIN, CLIENT = "U0ADMIN", "U0CLIENT"


def _project() -> Project:
    return Project(name="books", repo_path="/t", language="pt-BR", channel_id="C0OPS",
                   product=ProductConfig(docs_repo="a/b", channel_id="C0PROD", admins=[ADMIN],
                                         agent_name="Nina"))


def _message(text: str, *, user: str = CLIENT, conversation: str = "C0PROD") -> engine.Message:
    return engine.Message(project="books", conversation=conversation, room=conversation,
                          speaker=user, text=text)


class _Module:
    """The module with the model replaced; the ledger's verbs answer "nothing waits"."""

    def __init__(self, *, answer=None, drafted=None, available=True):
        self.calls: list[str] = []
        self.reply = answer or ProductAnswer(ok=True, text="uma resposta")
        self.drafted = drafted
        self.available = available
        self.released = 0

    def settle_acceptance(self, text):
        self.calls.append("settle_acceptance")
        return None

    def confirmed(self, reply, *, proposal):
        return "neither"

    def close_decisions_answered(self, *, channel=""):
        self.calls.append("close_decisions_answered")
        return 0

    def context(self, **_kw):
        from openfactory.product.corpus import Corpus

        return SimpleNamespace(available=self.available, reason="o repo sumiu",
                               corpus=Corpus())

    def answer(self, question, *, context="", conversation="", pending=""):
        self.calls.append("answer")
        return self.reply

    def draft(self, request, *, asked_by=""):
        self.calls.append("draft")
        return self.drafted or ProductAnswer(ok=False, error="nada testável")

    def release(self):
        self.released += 1


@pytest.fixture(autouse=True)
def _quiet_memory(monkeypatch):
    """The transcript kept in a list; the project memory reads nothing."""
    from openfactory.memory import transcript

    said: list[tuple[str, str]] = []
    monkeypatch.setattr(transcript, "record",
                        lambda project, *, thread, role, text, **_k: said.append((role, text))
                        or f"ts{len(said)}")
    monkeypatch.setattr(transcript, "recent", lambda *a, **k: [])
    monkeypatch.setattr(engine, "_with_elsewhere", lambda project, conversation, *a, **k:
                        conversation)
    return said


# ── the guard: ONE caller of the model's answer ─────────────────────────────────────────────────

#: Where `ProductModule.answer` / `ProductRole.answer` may be called: the engine, and the module's
#: own `answer`, which IS the call into the role — the definition, not a second caller.
_ALLOWED = {("openfactory/product/engine.py", None),
            ("openfactory/product/module.py", "answer")}

#: The modules whose `answer` this guard is about. A receiver bound to an import of anything else
#: — the messages store (`channel.answer(project, token=…)`), the tech-lead's conversation — is a
#: different verb that happens to share the name.
_PRODUCT = ("openfactory.product.module", "openfactory.product.role")


def _imported(tree: ast.AST) -> dict[str, str]:
    """`local name -> dotted target` for every import in the file, at any depth."""
    bound: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                bound[alias.asname or alias.name] = f"{node.module}.{alias.name}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                bound[alias.asname or alias.name.split(".")[0]] = alias.name
    return bound


def _answer_callers(root: Path, *, rel_to: Path) -> list[str]:
    """`file:line in function` for every `<x>.answer(…)` that may be the product role's, outside
    the allowed places."""
    hits: list[str] = []
    for path in sorted(root.rglob("*.py")):
        rel = str(path.relative_to(rel_to))
        tree = ast.parse(path.read_text())
        bound = _imported(tree)
        spans = [(fn.lineno, fn.end_lineno, fn.name) for fn in ast.walk(tree)
                 if isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef)]
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "answer"):
                continue
            receiver = node.func.value
            if isinstance(receiver, ast.Name) and receiver.id in bound \
                    and not bound[receiver.id].startswith(_PRODUCT):
                continue            # another module's `answer` (the messages store, the tech lead)
            inner = [name for lo, hi, name in spans if lo <= node.lineno <= (hi or lo)]
            where = inner[-1] if inner else None
            if (rel, None) in _ALLOWED or (rel, where) in _ALLOWED:
                continue
            hits.append(f"{rel}:{node.lineno} in {where}() — {ast.unparse(node)[:80]}")
    return hits


def test_NOTHING_outside_the_engine_calls_the_role_s_answer():
    """ADR-0051 D12, #266 slice 2's acceptance: a second caller of the model's answer is a second
    conversation starting over — the shape four partial copies of this one took. The job's own
    question about a card goes through `engine.consult` for exactly this reason."""
    hits = _answer_callers(PACKAGE, rel_to=ROOT)
    assert not hits, (
        "the product role's answer is called outside the turn engine — route it through "
        "`product/engine.py` (a person's message: `turn`; the factory's own question: "
        "`consult`):\n  " + "\n  ".join(hits))


def test_the_guard_can_SEE_a_second_caller(tmp_path):
    """The planted twin: a module building the product module and asking it directly is found,
    and so is a role asked directly; the messages store's `answer` beside them is not."""
    (tmp_path / "rogue.py").write_text(
        "def reply(project, text):\n"
        "    from openfactory.product.module import ProductModule\n"
        "    return ProductModule(project).answer(text)\n"
        "def role_reply(role, text):\n"
        "    return role.answer(sandbox=None, workspace=None, question=text)\n"
        "def store(project):\n"
        "    from openfactory.memory import messages as channel\n"
        "    return channel.answer(project, token='t', answer='approve', by='x')\n")
    hits = _answer_callers(tmp_path, rel_to=tmp_path)
    assert [h.split(" — ")[0] for h in hits] == ["rogue.py:3 in reply()",
                                                 "rogue.py:5 in role_reply()"], hits


# ── the contract: a message in, replies out ─────────────────────────────────────────────────────

def test_a_message_is_FROZEN_and_names_itself():
    """What was said is not rewritten by any stage — the judge's verdict is carried beside the
    text, never written over it — and every message has an id its replies can point back to."""
    one, two = _message("oi"), _message("oi")
    with pytest.raises(ValidationError):
        one.text = "sim"
    assert one.id and one.id != two.id


def test_a_message_for_another_project_is_refused_not_answered():
    with pytest.raises(ValueError):
        engine.turn(_project(), engine.Message(project="other", conversation="C", text="oi"),
                    module=_Module())


def test_the_replies_are_addressed_to_the_speaker_and_answer_THIS_message(_quiet_memory):
    """The receipt first, the answer after — each naming who it is for, which message it answers
    and the conversation it belongs to (ADR-0051 D13); the receipt is not recorded as a turn."""
    message = _message("o extrato pode mudar?")

    replies = engine.turn(_project(), message, module=_Module())

    assert [r.kind for r in replies] == ["receipt", "answer"]
    assert {(r.addressed_to, r.in_reply_to, r.conversation) for r in replies} == {
        (CLIENT, message.id, "C0PROD")}
    assert replies[-1].text == "uma resposta" and replies[-1].options is None
    assert [role for role, _ in _quiet_memory] == ["person", "agent"]


def test_a_staged_proposal_comes_back_as_a_REPLY_WITH_OPTIONS_never_posted():
    """A question with buttons is a Reply carrying its options, rendered by each transport its own
    way (ADR-0038 D2). The engine takes no `confirm` callback and posts nothing."""
    drafted = ProductAnswer(ok=True, draft=RequirementDraft(
        title="Exportar em PDF", must_be_true=["o PDF mostra o mesmo saldo"]))
    module = _Module(answer=ProductAnswer(ok=True, text="Hoje não.", is_request=True),
                     drafted=drafted)

    reply = engine.turn(_project(), _message("preciso exportar em PDF"), module=module)[-1]

    where, staged = staging.find_waiting("C0PROD", "C0PROD")
    assert reply.options is not None and staged is not None
    assert reply.options.token == staging.proposal_token(where, staged)
    assert reply.options.typed and reply.options.approve and reply.options.reject
    assert reply.text.startswith("Hoje não.") and "Exportar em PDF" in reply.text


def test_the_engine_takes_no_callbacks():
    """The notify/confirm seams disappeared from the engine (ADR-0051 D13): no function there
    declares them, so nothing mid-turn can call a channel."""
    tree = ast.parse(ENGINE.read_text())
    params = {a.arg for fn in ast.walk(tree) if isinstance(fn, ast.FunctionDef)
              for a in fn.args.args + fn.args.kwonlyargs}
    assert not params & {"notify", "confirm"}, params & {"notify", "confirm"}


def test_the_chat_adapter_holds_no_judgement():
    """`channel.handle` stays for the external chat add-on, and ONLY as an adapter: it builds the
    message, hands it to the door (`door.say` — #266 slice 3 put every transport through the one
    door, so the adapter no longer takes the turn itself) and renders the replies. A branch of the
    conversation growing back in it is the two-door drift starting over, and so is a call to the
    engine that skips the door."""
    tree = ast.parse(CHANNEL.read_text())
    handle = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                  and n.name == "handle")
    called = {getattr(n.func, "id", None) or getattr(n.func, "attr", None)
              for n in ast.walk(handle) if isinstance(n, ast.Call)}
    # `of_channel` since #266 slice 6: the add-on's own port says who its user is, before the
    # message is built — a lookup the add-on answers, not a decision of the conversation's
    assert called <= {"Message", "say", "deliver", "str", "getattr", "bool", "of_channel"}, called
    assert "say" in called, "the chat adapter no longer goes through the door"
    assert not any(isinstance(n, ast.If) for n in ast.walk(handle)), (
        "`handle` decides something — the conversation's decisions are the engine's")


# ── each stage, on its own ──────────────────────────────────────────────────────────────────────

def _exchange(text: str, module=None, *, user: str = CLIENT) -> engine.Exchange:
    return engine.Exchange(_project(), _message(text, user=user), module or _Module())


def test_SETTLE_alone_performs_a_yes_and_settles_nothing_else():
    project = _project()
    staging.remember("C0PROD", {"kind": "fact", "term": "erp", "body": "usa Primavera",
                                "said_by": ""}, project=project)
    wrote: list = []
    module = _Module()
    module.note_fact = lambda **kw: wrote.append(kw) or SimpleNamespace(
        ok=True, existed=False, detail="", ref="")

    yes = engine.settle(project, text="sim", user=ADMIN, thread="C0PROD", module=module)
    nothing = engine.settle(project, text="bom dia", user=ADMIN, thread="C0PROD", module=module)

    assert yes.reply and wrote and wrote[0]["term"] == "erp"
    assert nothing == engine.Settled(None, None)


def test_INTENTS_alone_carry_out_a_typed_ask_and_hand_anything_else_back(monkeypatch):
    from openfactory.product.voice import corpus_state

    monkeypatch.setattr(engine, "_waiting_line", lambda project: "")
    assert engine.intents(_exchange("status")) == corpus_state(
        available=True, requirements=0, promises=0, language="pt-BR")
    assert engine.intents(_exchange("o extrato pode mudar?")) is None


def test_CONVERSE_alone_answers_or_says_why_it_could_not():
    module = _Module()
    answered = engine.converse(_exchange("o extrato pode mudar?", module), None)
    assert answered.text == "uma resposta" and module.calls[-1] == "answer"

    from openfactory.product.voice import unavailable

    blind = engine.converse(_exchange("oi", _Module(available=False)), None)
    assert blind == unavailable(language="pt-BR")


def test_GESTURES_alone_stage_what_the_role_read_and_nothing_for_a_plain_answer():
    defect = ProductAnswer(ok=True, text="Isso contradiz o requisito 4.", is_defect=True,
                           violates=4)
    offered = engine.gestures(_exchange("a conciliação duplica"), defect)

    assert isinstance(offered, engine.Reply) and offered.options is not None
    assert staging.find_waiting("C0PROD", "C0PROD")[1]["kind"] == "defect"
    assert engine.gestures(_exchange("oi"), ProductAnswer(ok=True, text="oi")) is None


def test_STAGING_alone_drafts_a_request_and_nothing_for_a_question():
    drafted = ProductAnswer(ok=True, draft=RequirementDraft(title="Relatório", must_be_true=["x"]))
    module = _Module(drafted=drafted)
    request = ProductAnswer(ok=True, text="Entendi.", is_request=True)

    offered = engine.staging(_exchange("quero um relatório", module), request)

    assert isinstance(offered, engine.Reply) and staging.find_waiting("C0PROD", "C0PROD")[1]["kind"] == "draft"
    assert engine.staging(_exchange("oi", _Module()), ProductAnswer(ok=True, text="oi")) is None


# ── a workspace per turn: the turn gives its view back ──────────────────────────────────────────

def test_the_turn_RELEASES_the_module_s_view_when_it_ends():
    """ADR-0051 D11: each turn reads a view of its own (`ProductModule._workspace`), and the turn
    is what ends it — so no view outlives the answer it was made for."""
    module = _Module()
    engine.turn(_project(), _message("o extrato pode mudar?"), module=module)
    assert module.released == 1


def test_the_turn_releases_it_even_when_the_turn_CRASHES():
    class _Crashing(_Module):
        def answer(self, *a, **k):
            raise RuntimeError("the harness died")

    module = _Crashing()
    replies = engine.turn(_project(), _message("isto quebra"), module=module)

    assert module.released == 1
    from openfactory.product.voice import broke

    assert replies[-1].text == broke(language="pt-BR")


# ── the factory's own question is not a turn ────────────────────────────────────────────────────

def test_CONSULT_is_the_model_s_answer_and_nothing_else(_quiet_memory):
    """The job's gather asks the role about an undescribed file: nothing is recorded, settled or
    staged — the answer, through the one place allowed to ask for it."""
    module = _Module()
    answer = engine.consult(_project(), "o que faz o fechamento.py?", context="card 7",
                            module=module)

    assert answer.text == "uma resposta" and module.calls == ["answer"]
    assert _quiet_memory == [] and staging.find_waiting("C0PROD", "C0PROD")[1] is None


# ── the workflows already in flight ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_ASK_activity_kept_for_workflows_in_flight_runs_no_model(monkeypatch):
    """`ProductAskWorkflow` stays registered for one release so a workflow started before the
    deploy can replay; its activity answers "ask again" and builds no module — the engine is the
    one path that converses, and a shim that did too would be a second one."""
    from openfactory.product import module as module_mod
    from openfactory.runtime.temporal.activities import product_role_ask
    from openfactory.runtime.temporal.io import ProductAskInput

    def _never(*a, **k):
        raise AssertionError("the shim built a product module")

    monkeypatch.setattr(module_mod, "ProductModule", _never)

    out = await product_role_ask(ProductAskInput(project="books", question="oi"))

    assert out["ok"] is False and "ask again" in out["error"], out


#: The real recall block, taken before `_quiet_memory` swaps it out for every other test here.
_WITH_ELSEWHERE = engine._with_elsewhere


def test_nobody_is_named_across_conversations(monkeypatch):
    """ADR-0051 D9. What was said in another conversation may inform the answer; the role never
    names a person from outside the conversation it is in — so the block the model reads carries no
    name it could repeat. The role's own turns keep its name."""
    from types import SimpleNamespace

    import openfactory.memory.recall as recall_mod
    from openfactory.memory.recall import CHANNEL, Hit, Said

    hits = [Hit(Said(id="1", ts="2026-09-20T10:00:00", store=CHANNEL, where="acme", role="person",
                     actor="bruno", text="o boleto venceu de novo"), 1.0),
            Hit(Said(id="2", ts="2026-09-21T10:00:00", store=CHANNEL, where="acme", role="agent",
                     actor="", text="anotado, abro um card"), 0.9),
            # a key that names its person — spelled in capitals, which read as a room before
            Hit(Said(id="3", ts="2026-09-22T10:00:00", store=CHANNEL, where="Person:bruno",
                     role="person", actor="bruno", text="o fornecedor mudou"), 0.8)]
    monkeypatch.setattr(recall_mod, "recall", lambda *a, **k: hits)
    monkeypatch.setattr("openfactory.paths.project_memory_dir", lambda project: "/nowhere")

    block = _WITH_ELSEWHERE(SimpleNamespace(name="acme"), "", "boleto", own="person:ana",
                            agent_name="Ana PO")

    assert "bruno" not in block.lower() and "someone" in block, "named by the key, not the who"
    assert "Ana PO" in block, "the role's own turns keep its name"
    assert "o boleto venceu de novo" in block, "what was said still informs the answer"
