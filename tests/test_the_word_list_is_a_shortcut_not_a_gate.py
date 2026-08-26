"""A phrasing the word list does not carry must cost a round trip — never the gesture.

THE EVIDENCE, 2026-08-01. The owner asked *"podemos avançar?"* in the product channel, meaning
"propose the queue". `avançar` and `seguir` were not in the verb list; `começar`, `iniciar`,
`tocar` and `arrancar` were. The gesture fell through to conversation and nobody could tell,
because a missed intent and a deliberate answer look identical from outside.

THE FIX THE TICKET PROPOSED WAS A PATCH: add more verbs. That list had been written the day before
to REPLACE operator vocabulary — and it replaced one closed dictionary with another, keeping the
shape that fails. The next natural phrasing fails the same way.

THE SHAPE IS THE DEFECT: a regex guessing at natural language on a surface where a model already
reads every word of it, and already DECLARES what it read via three markers ([[PEDIDO]],
[[DEFEITO]], [[DECISAO]]). The queue gesture had no such channel — so a model that understood the
message perfectly had no way to say so. The same asymmetry this codebase already named: a promise
the output shape cannot express is one the system cannot keep.

So the pattern stays as a SHORTCUT (one model call instead of two when it matches, zero regression
on the phrasings that already worked) and `[[FILA]]` is the escape. Missing a word now costs a
round trip that was going to happen anyway.
"""

from __future__ import annotations

import pytest

import openfactory.product.channel as pc
from openfactory.product.intents import match_intent
from openfactory.product.role import QUEUE_MARKER


class _Product:
    def __init__(self, admins=("UADM",)):
        self.admins = list(admins)
        self.agent_name, self.docs_repo, self.channel_id = "Nina", "a/docs", "C1"
        self.enabled, self.docs_branch, self.staging_url = True, "main", ""


class _Project:
    name, language = "books", "pt-BR"

    def __init__(self, admins=("UADM",)):
        self.product = _Product(admins)


class _Answer:
    def __init__(self, text="", gesture="", is_request=False, is_defect=False):
        self.ok, self.text, self.gesture = True, text, gesture
        self.is_request, self.is_defect = is_request, is_defect
        self.decisions, self.violates, self.draft = [], None, None


class _Module:
    """Records which path the channel took."""

    def __init__(self, answer):
        self._answer = answer
        self.queue_asked = False
        self.drafted = None

    def answer(self, question, **_):
        return self._answer

    def propose_queue(self, **_):
        self.queue_asked = True
        return None, None, "sem quadro"      # the reply degrades; the CALL is what we assert

    def draft(self, request, **_):
        self.drafted = request
        return _Answer(text="rascunho")

    def confirmed(self, *_a, **_k):
        return "neither"

    def settle_acceptance(self, _t):
        return None

    def record_decisions(self, *_a, **_k):
        return 0

    def close_decisions_answered(self, **_):
        return 0

    def context(self):
        from types import SimpleNamespace

        class _Corpus:
            requirements: list = []

            def by_number(self, _n):
                return None

            def promises(self):
                return []

        return SimpleNamespace(available=True, corpus=_Corpus(), reason="")


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
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


#: A phrase NO pattern matches, so these tests exercise the MARKER path and not the shortcut.
#: With "podemos avançar?" here they all passed — through `match_intent`, never reaching the model.
#: A test that is green for the wrong reason is the guard sharing the failure mode of what it
#: protects, which is precisely what this file is about.
_SO_O_MODELO_LE = "queremos que o time arregace as mangas nisso agora"


def _say(module, text=_SO_O_MODELO_LE):
    from openfactory.product.intents import match_intent as _mi
    assert _mi(text) is None or _mi(text)[0] != "queue", (
        f"{text!r} matches the shortcut — this test would not exercise the marker at all")
    return pc.handle(_Project(), text=text, user="UADM", thread="C1", channel="C1", module=module)


# ── 1. the escape exists and production reaches it ────────────────────────────────────────────

def test_a_phrasing_the_list_MISSES_still_reaches_the_queue():
    """The whole point. The model read the message, declared the gesture, and the channel acted —
    with no word in any list having matched."""
    module = _Module(_Answer(text="claro", gesture="queue"))

    _say(module)

    assert module.queue_asked, "the gesture the model recognised reached nothing"


def test_a_gesture_is_NOT_read_as_a_request_for_something_new():
    """Asking to START the agreed work is not asking for something NEW. Falling through to the
    draft path would offer a client a brand-new requirement in answer to "let's go" — which is
    exactly what happened before the marker existed."""
    module = _Module(_Answer(text="claro", gesture="queue", is_request=True))

    _say(module)

    assert module.queue_asked
    assert module.drafted is None, "it offered to write a new requirement instead of starting work"


def test_a_BROKEN_PROMISE_outranks_a_request_to_start():
    """`remember` holds ONE staged entry per conversation, so two branches staging in the same turn
    displace each other in silence. A defect is about work already owed."""
    module = _Module(_Answer(text="isso está quebrado", gesture="queue", is_defect=True))

    said = _say(module)

    assert not module.queue_asked, "the defect confirmation was displaced by a queue proposal"
    assert "confirm" in str(said).lower() or "registr" in str(said).lower(), said


def test_an_ordinary_answer_reaches_neither():
    module = _Module(_Answer(text="o requisito 6 fala disso"))

    said = _say(module, "o que diz o requisito 6?")

    assert not module.queue_asked and module.drafted is None
    assert said == "o requisito 6 fala disso"


# ── 2. the marker is plumbing and never reaches a person ──────────────────────────────────────

def test_the_marker_is_parsed_and_STRIPPED_before_the_safety_net():
    """Read after the net, the gesture would be read from text the net had already emptied — built,
    tested, and reached by nothing, which is this repository's signature defect."""
    from openfactory.contracts import AgentRunResult
    from openfactory.product.corpus import Corpus
    from openfactory.product.role import ProductRole

    class _Harness:
        name = "h"

        def ask(self, *, sandbox, workspace, prompt, phase="ask"):
            return AgentRunResult(ok=True, summary=f"Podemos sim, tudo pronto.\n{QUEUE_MARKER}")

    answer = ProductRole(_Harness(), corpus=Corpus(requirements=[])).answer(
        sandbox=None, workspace=None, question="podemos avançar?")

    assert answer.gesture == "queue", "the marker was emitted and read by nothing"
    assert "[[" not in answer.text, f"plumbing reached the client: {answer.text!r}"
    assert "tudo pronto" in answer.text


def test_the_prompt_ASKS_for_the_marker_it_parses():
    """A parser for a marker the prompt never requests is a capability nothing will ever use — the
    inverse of the defect this file is about, and the same audit."""
    import inspect

    from openfactory.product.role import ProductRole

    src = inspect.getsource(ProductRole.answer)
    assert "QUEUE_MARKER" in src, "the prompt never asks for the marker"
    assert "SPENDS MONEY" in src, (
        "the model is not told what the gesture costs, so it cannot weigh a plan against an order")


# ── 3. the shortcut still works, and still cannot arm the spend gate by accident ───────────────

@pytest.mark.parametrize("phrase", [
    "podemos avançar?", "podemos seguir?", "vamos prosseguir", "pode começar?",
    "can we proceed?", "bora começar", "vamos tocar isso",
])
def test_the_common_phrasings_stay_on_the_cheap_path(phrase):
    """The shortcut is worth keeping: when it matches, the answer costs one model call instead of
    two. Widening it is free — it just stopped being the only door."""
    matched = match_intent(phrase)

    assert matched and matched[0] == "queue", f"{phrase!r} -> {matched}"


@pytest.mark.parametrize("phrase", [
    "vamos avançar na discussão do relatório de julho",
    "quando podemos avançar?",
    "não vamos avançar ainda",
    "vamos começar a discutir o relatório de julho",
])
def test_a_PLAN_still_cannot_arm_the_spend_gate_from_the_pattern(phrase):
    """The end anchor is what separates the gesture from a plan, and widening the verb list must
    not have loosened it. The marker path has its own guard — the prompt says a plan is not the
    gesture — but this one is deterministic and must hold on its own."""
    matched = match_intent(phrase)

    assert not (matched and matched[0] == "queue"), f"{phrase!r} armed the spend gate: {matched}"


def test_the_pattern_is_documented_as_a_SHORTCUT_not_a_gate():
    """Structural, because the next person to touch this list needs to know that missing a word is
    no longer fatal — otherwise they re-derive the closed-dictionary reflex and the escape rots.

    Read off the CLIENT-phrasing pattern (the last `("queue"` in the table; the first is the
    operator vocabulary), because that is the one that failed."""
    from pathlib import Path

    src = Path("openfactory/product/intents.py").read_text()
    comentario = src[:src.rfind('("queue", re.compile(')][-1400:]

    assert "SHORTCUT, NOT A GATE" in comentario, comentario[-500:]
    assert "QUEUE_MARKER" in comentario, "the escape is not named where the shortcut is defined"
