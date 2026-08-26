"""Nobody waits in silence — the receipt that goes out before the thinking starts.

THE PRODUCT OWNER'S FIRST REAL MESSAGE SAT SILENT FOR 2min38s. She had received it, answered
correctly and
posted the answer; the telemetry proves all three. But from the outside, "she is thinking", "she
ignored me" and "she crashed" are the same experience, and Slack's typing indicator expires after
about five seconds — so it is not the fix for a two-minute answer. A sentence is.

The tests are about REACH and RESTRAINT in equal measure: the receipt must go out on the paths
that are slow, must NOT go out on the ones that answer instantly (noise a client learns to
ignore), must be sent ONCE, and must never be able to cost us the real answer.
"""

from __future__ import annotations

import add_ons
import pytest

import openfactory.product.channel as pc
from openfactory.contracts.product import ProductConfig
from openfactory.contracts.project import Project, ProviderRef


def _is_receipt(text: str) -> bool:
    """Any of the variants counts. Pinning one phrase would fail the moment somebody adds another,
    which is a test that punishes the very change it was written alongside."""
    from openfactory.product.voice import _ON_IT

    return any(v in (text or "") for v in _ON_IT["pt-BR"])


def _project():
    return Project(name="books", repo_path="/t", language="pt-BR",
                   tracker=ProviderRef(kind="github", repo="a/b"),
                   forge=ProviderRef(kind="github", repo="a/b"),
                   product=ProductConfig(docs_repo="a/docs", channel_id="C0PROD",
                                         admins=["U1"], agent_name="Nina"))


class _Slow:
    """A module whose model call is the slow part."""

    def __init__(self):
        self.asked = False

    def settle_acceptance(self, text):
        return None

    def context(self):
        from types import SimpleNamespace
        return SimpleNamespace(available=True, reason="")

    def answer(self, question, *, context="", conversation="", **_):
        self.asked = True
        from types import SimpleNamespace
        return SimpleNamespace(ok=True, text="a resposta", is_defect=False,
                               asked_for_something=False)


class _Fast:
    """A module answering from data already in hand — no model, no wait."""

    def settle_acceptance(self, text):
        return None

    def status_line(self):
        return "3 em andamento"


@pytest.fixture()
def sent(monkeypatch):
    out: list[str] = []
    monkeypatch.setattr(pc, "_waiting_line", lambda project: "", raising=False)
    return out


def test_a_slow_message_gets_a_receipt_BEFORE_the_model_is_called(sent):
    """Order is the whole point: a receipt that arrives with the answer is not a receipt."""
    module = _Slow()
    order: list[str] = []

    def notify(text):
        order.append(f"receipt:{module.asked}")
        sent.append(text)

    pc.handle(_project(), text="organiza nosso backlog", user="U1", thread="C0PROD",
              channel="C0PROD", module=module, notify=notify)

    assert sent, "the person waited with no sign of life"
    assert _is_receipt(sent[0]), sent[0]
    assert order == ["receipt:False"], "the receipt went out AFTER the slow call — useless"


def test_the_receipt_names_her_so_it_reads_as_a_person(sent):
    pc.handle(_project(), text="e o segundo?", user="U1", thread="C0PROD", channel="C0PROD",
              module=_Slow(), notify=sent.append)

    assert sent[0].startswith("Nina: "), sent[0]


def test_an_INSTANT_answer_gets_no_receipt(sent):
    """Restraint. `status` answers from the board already read — a "let me look" followed
    immediately by the answer is noise, and a channel that cries wolf gets muted."""
    pc.handle(_project(), text="como estamos?", user="U1", thread="C0PROD", channel="C0PROD",
              module=_Fast(), notify=sent.append)

    assert not sent, f"a receipt for an instant answer: {sent}"


def test_the_receipt_is_sent_at_most_once(sent):
    """A message that touches two slow steps must not produce two receipts."""
    module = _Slow()
    pc.handle(_project(), text="preciso de um relatório novo", user="U1", thread="C0PROD",
              channel="C0PROD", module=module, notify=sent.append)

    assert len(sent) <= 1, f"{len(sent)} receipts for one message: {sent}"


def test_a_broken_notifier_never_costs_the_real_answer(sent):
    """The receipt is a courtesy. If Slack rejects it, the answer must still go out — the failure
    mode this whole change exists to remove is the person getting nothing."""
    def boom(text):
        raise RuntimeError("slack said no")

    reply = pc.handle(_project(), text="e o segundo?", user="U1", thread="C0PROD",
                      channel="C0PROD", module=_Slow(), notify=boom)

    assert reply, "a failed courtesy swallowed the answer"


def test_no_notifier_at_all_still_works(sent):
    """Callers that cannot post twice (tests, the panel) pass nothing and lose only the courtesy."""
    reply = pc.handle(_project(), text="e o segundo?", user="U1", thread="C0PROD",
                      channel="C0PROD", module=_Slow())
    assert reply


def test_the_receipt_is_NOT_recorded_as_a_conversation_turn(monkeypatch):
    """Layer 0 keeps what was SAID (ADR-0024). A receipt carries no information for audit or for
    recall — recorded, it would be injected into every later prompt and teach her to echo it."""
    import openfactory.runtime.temporal.activities as activities_mod

    class _Sink:
        rows: list = []

        def record(self, rec):
            self.rows.append(rec)

    sink = _Sink()
    sink.rows = []
    monkeypatch.setattr(activities_mod, "_metrics_sink", lambda *a, **k: sink)

    pc.handle(_project(), text="e o segundo?", user="U1", thread="C0PROD", channel="C0PROD",
              module=_Slow(), notify=lambda t: None)

    said = [r.extra.get("text", "") for r in sink.rows if r.kind == "message"]
    assert not any(_is_receipt(t) for t in said), f"the receipt polluted the memory: {said}"
    assert any("e o segundo?" in t for t in said), "the real message was not recorded"


def test_the_bot_passes_a_notifier_at_all():
    """Reach. The receipt working in this file while bot.py calls handle() without `notify` is
    this repository's signature defect, and it has shipped thirteen times."""
    import ast

    tree = ast.parse(add_ons.source("openfactory/runtime/slack/bot.py").read_text())
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "handle"
             and any(k.arg == "notify" for k in n.keywords)]
    assert calls, "bot.py calls product_channel.handle() without a notifier — nobody sees it"


# ── variation ──────────────────────────────────────────────────────────────────────────────────
def test_consecutive_DIFFERENT_messages_do_not_always_get_the_same_receipt(sent):
    """The same string every time is how a person stops reading it and starts hearing a machine."""
    for text in ("organiza o backlog", "e o segundo?", "quais bancos?", "o que falta?",
                 "refaz o plano", "quando sai?", "e o fiscal?", "isso resolveu?"):
        pc.handle(_project(), text=text, user="U1", thread="C0PROD", channel="C0PROD",
                  module=_Slow(), notify=sent.append)

    assert len(set(sent)) > 1, f"every receipt was identical: {set(sent)}"


def test_the_SAME_message_always_gets_the_same_receipt(sent):
    """Deterministic, not random: tests stay stable and "why did it say that?" has an answer.
    Randomness would buy nothing here and cost both."""
    for _ in range(3):
        pc.handle(_project(), text="organiza o backlog", user="U1", thread="C0PROD",
                  channel="C0PROD", module=_Slow(), notify=sent.append)

    assert len(set(sent)) == 1, sent


def test_every_variant_stays_free_of_delivery_vocabulary():
    """A receipt is still a message to a client. The whole variant set is checked, not the one that
    happened to be sampled."""
    # WORD boundaries, not substrings: "properly" contains "pr" and "backlog" contains "log".
    # A substring jargon check fails on innocent English and passes on nothing extra — this repo
    # has already paid for that lesson once.
    import re

    from openfactory.product.voice import _ON_IT

    banned = r"\b(prs?|pull requests?|branch|commit|tickets?|sprint|backlog|deploy)\b"
    for lang, variants in _ON_IT.items():
        for v in variants:
            assert not re.search(banned, v, re.IGNORECASE), f"[{lang}] {v}"
            assert len(v) < 90, f"[{lang}] too long to be a receipt: {v}"


def test_no_variant_promises_anything_specific():
    """It is sent BEFORE any thinking, so "I'll have it by X" or "I'll do Y" would be invented."""
    from openfactory.product.voice import _ON_IT

    for lang, variants in _ON_IT.items():
        for v in variants:
            assert "minuto" not in v.lower() or "me d" in v.lower(), f"[{lang}] promises a time: {v}"
