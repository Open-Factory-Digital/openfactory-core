"""Agreeing to a requirement produces WORK, not just a sentence — and in the client's words.

THE EVIDENCE. `quebra o requisito N em tarefas` is operator vocabulary. A client says "pode
começar?", and until now that matched no intent, fell through to the conversation, and the role —
correctly reading it as a request — offered to draft a NEW REQUIREMENT to somebody who had just
asked to start the work they had already agreed to. Meanwhile the acceptance itself produced one
sentence and nothing else, so anything existing at all depended on somebody knowing the magic
phrase.

DECIDED BY THE PRODUCT OWNER, 2026-07-31: a product owner does not ask permission to decompose.
Accepting
breaks the requirement down and says so. Filing spends nothing — Backlog is inert, and the money
gate is `promote`, which stays staged and gated (ADR-0019 §5).

THE TRAP THIS WOULD HAVE DIED IN, and it is why the first section here is about a cache. The module
answers from a context loaded once per message; `break_down` refuses anything that is not yet a
promise, and it asks that cached corpus — where the requirement the client had just agreed to was
still `proposed`. Every acceptance would have answered "this is not a promise yet" about the
promise made one line earlier, and no test with a stubbed module could ever have seen it: the stub
has no cache to be stale.
"""

from __future__ import annotations

import logging

import pytest

import openfactory.product.channel as pc
from openfactory.product.authoring import WriteResult
from openfactory.product.intents import match_intent


class _Result:
    def __init__(self, ok=True, detail="", ref="", existed=False):
        self.ok, self.detail, self.ref, self.existed = ok, detail, ref, existed
        self.url, self.merged = "", True


class _Product:
    def __init__(self, admins):
        self.admins = list(admins)
        self.agent_name, self.docs_repo, self.channel_id = "Nina", "a/docs", "C1"
        self.enabled, self.docs_branch = True, "main"


class _Project:
    name, language = "books", "pt-BR"

    def __init__(self, admins=("UADM",)):
        self.product = _Product(list(admins))


class _Module:
    """Accept + break_down, which is exactly what this branch calls."""

    def __init__(self, *, accepts=None, breaks=None, breaks_raises=False):
        self.accepted_with = self.broke_down = None
        self._accepts = accepts or _Result(ok=True)
        self._breaks = list(breaks) if breaks is not None else [_Result(ok=True, ref="#901")]
        self._breaks_raises = breaks_raises

    def accept(self, number, *, actor):
        self.accepted_with = (number, actor)
        return self._accepts

    def break_down(self, number, *, actor):
        self.broke_down = (number, actor)
        if self._breaks_raises:
            raise RuntimeError("the harness died")
        return self._breaks

    def confirmed(self, *_a, **_k):
        return "neither"


@pytest.fixture(autouse=True)
def _clean_stage(monkeypatch):
    # THE STATE LIVES IN `openfactory/product/staging.py` NOW (#98 slice 3), so isolation is
    # applied THERE. Rebinding the re-export on `product_channel` would leave the code
    # reading the original dict: the fixture would look like it isolates and would not,
    # which is how a staged proposal leaked into the next test when this move was first
    # attempted — with the symptom landing far from the cause.
    from openfactory.product import staging as _staging
    monkeypatch.setattr(_staging, "_PENDING", {})
    monkeypatch.setattr(_staging, "_EXPIRED_TOMBSTONES", {})
    from openfactory.memory import transcript

    monkeypatch.setattr(transcript, "record", lambda *a, **k: "")
    monkeypatch.setattr(transcript, "recent", lambda *a, **k: [])
    yield


def _accept(module, *, number=6):
    pc.remember("C1", {"kind": "accept", "number": number, "channel": "C1",
                       "asked_by": "<@UADM>"})
    return pc.handle(_Project(), text="sim", user="UADM", thread="C1", channel="C1",
                     module=module)


# ── 1. the trap: a module must not answer from what it read before its own write ───────────────
def test_a_corpus_WRITE_invalidates_what_the_module_already_read():
    """The whole feature stands on this, and nothing about the feature makes it visible.

    Without it `break_down` reads a corpus where the requirement is still `proposed`, refuses it as
    "not a promise", and every acceptance in production answers that the promise it just made is
    not one — while every unit test with a stubbed module passes."""
    from openfactory.product.module import ProductModule

    mod = ProductModule.__new__(ProductModule)
    mod._context = "the version from before the write"

    kept = mod._corpus_changed(WriteResult(ok=True, ref="0006-x.md"))

    assert mod._context is None, "the module would go on answering from the pre-write corpus"
    assert kept.ref == "0006-x.md", "the result must pass straight through"


def test_a_REFUSED_write_does_not_throw_the_context_away():
    """A refusal changed nothing, and dropping the context would buy a repo sync for nothing."""
    from openfactory.product.module import ProductModule

    mod = ProductModule.__new__(ProductModule)
    mod._context = "still valid"

    mod._corpus_changed(WriteResult(ok=False, detail="não pode"))
    assert mod._context == "still valid"

    mod._corpus_changed(WriteResult(ok=True, existed=True, detail="esse já estava acordado"))
    assert mod._context == "still valid", "nothing was written, so nothing went stale"


def test_the_invalidation_is_WRAPPED_AROUND_the_write_not_written_after_it():
    """Structural, because the next act that changes the corpus will be written by somebody who
    never read this file. A value that has to pass through the invalidator to be returned cannot
    be returned without it; a line placed after the write can simply be left out."""
    import inspect

    from openfactory.product.module import ProductModule

    for method in (ProductModule.accept, ProductModule.drop):
        src = inspect.getsource(method)
        assert "self._corpus_changed(" in src, (
            f"{method.__name__} writes the corpus and leaves the module reading the old one")


# ── 2. the acceptance now produces work ────────────────────────────────────────────────────────
def test_agreeing_breaks_the_requirement_down_without_being_asked():
    module = _Module()

    said = _accept(module)

    assert module.accepted_with == (6, "UADM"), module.accepted_with
    assert module.broke_down == (6, "UADM"), (
        "the acceptance produced a sentence and no work — the state this fixes")
    assert "#901" in said, said


def test_the_client_is_told_that_starting_is_still_their_call():
    """Filing costs nothing and this reply must never read as "we have begun". The spend gate is
    `promote`, and a client who believes work started will not release it."""
    said = _accept(_Module())

    assert "Backlog" in said, said
    assert "decisão de uma pessoa" in said, said


def test_an_ALREADY_agreed_requirement_files_nothing_new():
    """`existed` means this turn agreed nothing, so there is nothing new to decompose — and running
    it anyway would re-file a breakdown on every repeated yes."""
    module = _Module(accepts=_Result(ok=True, existed=True, detail="esse já estava acordado"))

    said = _accept(module)

    assert module.broke_down is None, "a repeated yes filed work again"
    assert "Acordado" in said, said


# ── 3. the breakdown can never cost the agreement ──────────────────────────────────────────────
def test_a_breakdown_that_FAILED_does_not_take_the_acceptance_with_it():
    """The promise is written and pushed before this runs. Reporting the second act's failure as
    the first's would tell a client their acceptance did not happen — about the one thing that
    certainly did."""
    module = _Module(breaks=[_Result(ok=False, detail="não consegui quebrar isso")])

    said = _accept(module)

    assert "Acordado" in said, f"the agreement was not reported: {said}"
    assert said.index("Acordado") < said.index("Ainda não consegui"), (
        "the failure was announced before what still holds, which reads as a failed acceptance")
    assert "quebrar em tarefas" in said, "no way back was offered"


def test_a_breakdown_that_RAISED_does_not_take_the_acceptance_with_it(caplog):
    module = _Module(breaks_raises=True)

    with caplog.at_level(logging.ERROR, logger="openfactory.product"):
        said = _accept(module)

    assert "Acordado" in said, said
    assert any("OPENFACTORY_PRODUCT_AUTOBREAK_FAILED" in r.getMessage() for r in caplog.records), (
        "a refactor could rename `break_down` and every acceptance would quietly stop filing work")


def test_a_module_that_LOST_the_method_is_loud_rather_than_merely_polite(caplog):
    """The catch-all is wide enough to swallow a rename, which would leave every acceptance
    answering politely that it could not break anything down — for ever, with the client reading
    it as ordinary trouble. This is the runtime half of that guard; the structural half is below."""

    class _Renamed(_Module):
        """`break_down` has become `decompose` somewhere else in the codebase."""

        def __getattr__(self, item):
            raise AttributeError(item)

        break_down = property(lambda self: (_ for _ in ()).throw(AttributeError("break_down")))

    with caplog.at_level(logging.ERROR, logger="openfactory.product.channel"):
        said = _accept(_Renamed())

    assert "Acordado" in said, said
    assert "Ainda não consegui" in said, "the client was told nothing about the missing work"
    assert any("OPENFACTORY_PRODUCT_AUTOBREAK_FAILED" in r.getMessage() for r in caplog.records), (
        "the degradation is invisible in the logs, so nobody would ever find it")


def test_the_accept_branch_really_calls_the_breakdown():
    """Reachability, read off the executor. Fourteen times this repository has shipped something
    built, tested and reached by nothing; a behaviour test with a stub proves the stub was called,
    never that production calls it.

    READ OFF THE DISPATCH TABLE, not off a chain of `if` (#105). The acceptance branch is now
    `confirm._EXECUTORS["accept"]`, so the reachability question is answerable exactly: whatever
    that key maps to IS what a confirmed acceptance runs, and it has to be the function that
    decomposes. Naming the function directly would pass the day the table stopped pointing at it.
    """
    import inspect

    from openfactory.product import confirm as confirm_mod

    runs = confirm_mod._EXECUTORS.get("accept")
    assert runs is not None, "a confirmed acceptance dispatches to nothing"
    assert "_also_broke_it_down(" in inspect.getsource(runs), (
        "the acceptance branch never reaches the composer")
    assert "module.break_down(" in inspect.getsource(confirm_mod._also_broke_it_down), (
        "the composer does not decompose anything")


# ── 4. the gesture, in the words a client actually uses ────────────────────────────────────────
@pytest.mark.parametrize("phrase", [
    "pode começar?",
    "podemos começar",
    "posso começar?",
    "vamos começar então",
    "bora começar",
    "vamos tocar isso",
    "Nina, pode começar?",
    "pode começar agora",
    "can we start?",
    "let's start",
])
def test_a_client_asks_to_start_in_their_own_words(phrase):
    """None of the queue pattern's words is a client's: "próximos", "fila", "TO-DO", "sequência".
    Every one of these fell through to conversation, where asking to START got you an offer to
    write a new requirement."""
    matched = match_intent(phrase)

    assert matched and matched[0] == "queue", f"{phrase!r} -> {matched}"


@pytest.mark.parametrize("phrase", [
    "vamos começar a discutir o relatório de julho",
    "quando podemos começar a falar disso?",
    "pode começar pelo relatório e depois o extrato",
    "não vamos começar ainda",
    "não vamos começar",
    "nunca vamos começar",
])
def test_a_PLAN_to_start_something_else_never_arms_the_spend_gate(phrase):
    """The queue gesture stages a proposal ending in "Aprovo?", and an approver's yes there
    promotes tickets — money. This pattern's own neighbour carries the warning in writing: a
    question about something else must never arm that gate. So the clause has to END at the verb,
    give or take a particle people actually append."""
    matched = match_intent(phrase)

    assert not (matched and matched[0] == "queue"), f"{phrase!r} armed the spend gate: {matched}"


def test_the_operator_wording_still_works():
    """The new phrasing is an addition. Somebody who learned the old sentence must not find it
    broken — and `breakdown` stays a distinct gesture, because a requirement can be re-decomposed
    without anything being accepted."""
    assert match_intent("o que entra na fila agora?")[0] == "queue"
    assert match_intent("quebra o requisito 8 em tarefas")[0] == "breakdown"
