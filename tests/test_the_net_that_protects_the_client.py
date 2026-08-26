"""The two nets between the agent's raw output and a client's eyes — both had a hole.

BOARD #9. `claims_a_write` fires when a reply asserts an outcome the platform can observe did not
happen, and `_DENIES_WRITE` silences it when the same text is a self-correction. The list of
denials contained *"não vejo o resultado"* — which is not a denial at all. It is a statement about
OBSERVABILITY, the role adopted it as a habitual and CORRECT formula in nearly every message, and
so the detector was switched off for the whole conversation. On 2026-07-31 she wrote *"Registrado o
pedido junto ao time"* about a request that exists nowhere, and nothing said anything: a true
positive swallowed by the guard against false ones.

The second half of the same defect: the denial was tested against the WHOLE MESSAGE, so one honest
retraction at the bottom licensed everything asserted above it.

BOARD #10. `_ANY_MARKER_RE` could not cross a newline, so a marker the model wrapped over two lines
matched neither the parser nor the net and reached the client raw — the third version of one
mistake inside a single regex (a `{0,400}` ceiling, then a `[^\\]\\n]` class, now `[^\\n]`). And an
opener that never closed was recorded as a known limit rather than fixed, which is how it was still
there to be found.

WHAT THE BOUNDARY IS NOW, in all three: a BLANK LINE. A marker is one directive and never contains
a paragraph break, so the delimiter is structural — there is no constant left here to be wrong by a
hundred characters next time.
"""

from __future__ import annotations

import logging

import pytest

from openfactory.product.role import _ANY_MARKER_RE, _DECISION_RE, _UNCLOSED_MARKER_RE
from openfactory.product.voice import claims_a_write

# ── 1. the false-claim detector sees what it was built to see ──────────────────────────────────

def test_the_sentence_that_got_through_is_caught():
    """The literal message from 2026-07-31, with the habitual formula in it."""
    said = ("Registrado o pedido junto ao time.\n\n"
            "Não vejo o resultado do quadro agora, então não afirmo em que coluna ele entrou.")

    assert claims_a_write(said), (
        "the claim was swallowed by a sentence that denies nothing — it states what she cannot see")


@pytest.mark.parametrize("formula", [
    "Não vejo o resultado da escrita.",
    "não consigo ver o resultado dessa operação.",
])
def test_saying_you_cannot_OBSERVE_something_excuses_only_ITS_OWN_sentence(formula):
    """The distinction the fix rests on, and the case a paragraph rule alone would still miss.

    "I cannot see the outcome" is honest, is what the prompt asks for, and refers to nothing before
    it — so it cannot vouch for the sentence beside it. It is consulted at all only because the
    phrase trips the claim detector on itself ("escrita" is both the noun and the participle)."""
    assert claims_a_write(f"Registrado o requisito 4. {formula}"), formula
    assert claims_a_write(formula) == "", (
        f"it flagged her for the honest formula itself: {formula}")


def test_a_REAL_self_correction_is_still_not_contradicted():
    """The incident the guard was built for, and it must survive the fix. Being corrected while
    right is worse than not being corrected: it teaches the reader to distrust both voices, and it
    punishes the exact behaviour the rule exists to produce."""
    said = ("Corrijo o que escrevi: eu disse 'Registrado o Requisito 1'. Não foi. "
            "Não vejo o resultado de escrita nenhuma.")

    assert claims_a_write(said) == "", f"a correct retraction was contradicted: {said}"


def test_a_retraction_excuses_ITS_OWN_claim_and_no_other():
    """One honest correction at the bottom used to license everything asserted above it."""
    said = ("Registrado o pedido junto ao time.\n\n"
            "Corrijo o que escrevi antes: eu disse 'Registrado o Requisito 1'. Não foi.")

    caught = claims_a_write(said)
    assert caught, "the retraction in the second paragraph excused the claim in the first"
    assert caught.lower() == "registrado", caught


def test_the_formula_in_the_SAME_paragraph_no_longer_excuses_the_claim():
    """What a paragraph rule alone would have left open, and it is how she actually writes: the
    claim and the honest caveat in one breath."""
    said = "Registrado o pedido junto ao time. Não vejo o resultado do quadro agora."

    assert claims_a_write(said), f"the caveat vouched for the claim beside it: {said}"


def test_a_message_that_is_ONLY_a_retraction_stays_untouched():
    said = ("Corrijo o que escrevi: eu disse 'Registrado o Requisito 1'. Não foi.\n\n"
            "Nada daquela mensagem existe na base.")

    assert claims_a_write(said) == "", said


def test_an_ordinary_message_with_no_claim_is_not_flagged():
    assert claims_a_write("O requisito 4 fala do portal. Quer que eu proponha o texto?") == ""


# ── 2. the marker net: nothing plumbing-shaped reaches a person ────────────────────────────────

def test_a_marker_WRAPPED_OVER_TWO_LINES_no_longer_reaches_the_client():
    text = "Sobre o portal.\n\n[[DECISAO: qual CNPJ usar para as notas\nda filial de Campinas]]"

    assert _ANY_MARKER_RE.findall(text), "the net cannot see a marker the model wrapped"
    assert "[[" not in _ANY_MARKER_RE.sub("", text)


def test_a_wrapped_decision_is_RECORDED_and_not_merely_stripped():
    """The higher stake of the two. The net only decides whether plumbing leaks; the parser decides
    whether a COMMITMENT EXISTS. A wrapped decision that is stripped and not parsed is never
    chased, never answered, and loud only in a log."""
    m = _DECISION_RE.search("[[DECISAO: qual CNPJ usar para as notas\nda filial de Campinas]]")

    assert m is not None, "a decision the model wrapped would be dropped instead of tracked"
    assert "Campinas" in m.group("label")


def test_a_BLANK_LINE_ends_a_marker_so_the_net_cannot_eat_a_message():
    """The delimiter is structural, not numeric — and it has to hold in the dangerous direction: an
    unbalanced `[[` must never swallow the paragraphs after it."""
    text = "[[ALGO sem fechar\n\nEste parágrafo é do cliente e não pode sumir.]]"

    assert _ANY_MARKER_RE.findall(text) == [], "the net ate across a paragraph break"


def test_TWO_markers_on_two_lines_stay_two():
    labels = [m.group("label") for m in _DECISION_RE.finditer(
        "[[DECISAO: a primeira coisa]]\n[[DECISAO: a segunda coisa]]")]

    assert labels == ["a primeira coisa", "a segunda coisa"], labels


# ── 3. the marker that never closed ────────────────────────────────────────────────────────────

def test_an_UNCLOSED_marker_is_stripped_to_the_end_of_its_line():
    text = "Sobre o portal.\n[[SUGGEST: proponha o requisito do extrato\nE isto é do cliente."

    cleaned = _UNCLOSED_MARKER_RE.sub("", text)

    assert "[[SUGGEST" not in cleaned, "the plumbing reached the client whole"
    assert "E isto é do cliente." in cleaned, "it ate the line after the marker"
    assert "Sobre o portal." in cleaned


@pytest.mark.parametrize("text", [
    "veja [[isto sem marcador",
    "um [[link]] normal de wiki",
    "custa R$ [[2 mil",
])
def test_ordinary_text_with_brackets_survives(text):
    """This net DELETES text nobody balanced, so it is deliberately narrower than its sibling: only
    an opener followed by three or more capitals, which is what every marker here looks like."""
    assert _UNCLOSED_MARKER_RE.sub("", text) == text, text


def test_an_unclosed_DECISION_is_shouted_and_not_merely_swept(caplog):
    """A decision the agent asked for and nobody recorded is the silent loss the whole ledger
    exists to prevent — so it cannot leave as one line among the warnings."""
    from openfactory.contracts import AgentRunResult
    from openfactory.product.corpus import Corpus
    from openfactory.product.role import ProductRole

    class _Harness:
        name = "h"

        def ask(self, *, sandbox, workspace, prompt, phase="ask"):
            return AgentRunResult(
                ok=True,
                summary="Sobre o portal.\n[[DECISAO: qual CNPJ usar, sem fechar o marcador")

    role = ProductRole(_Harness(), corpus=Corpus(requirements=[]))
    with caplog.at_level(logging.ERROR, logger="openfactory.product"):
        answer = role.answer(sandbox=None, workspace=None, question="e aí?")

    assert "[[" not in answer.text, f"the plumbing reached the client: {answer.text!r}"
    assert any("OPENFACTORY_PRODUCT_LOST_MARKER" in r.getMessage() for r in caplog.records), (
        "a commitment was dropped quietly")


def test_a_WELL_FORMED_marker_keeps_the_rest_of_its_line():
    """Order matters: the unclosed net runs AFTER the balanced one. Reversed, it would cut the tail
    off every marker that was perfectly well formed."""
    from openfactory.contracts import AgentRunResult
    from openfactory.product.corpus import Corpus
    from openfactory.product.role import ProductRole

    class _Harness:
        name = "h"

        def ask(self, *, sandbox, workspace, prompt, phase="ask"):
            return AgentRunResult(ok=True, summary="[[PEDIDO]] e o resto desta linha importa.")

    answer = ProductRole(_Harness(), corpus=Corpus(requirements=[])).answer(
        sandbox=None, workspace=None, question="e aí?")

    assert answer.is_request is True
    assert "o resto desta linha importa." in answer.text, answer.text
