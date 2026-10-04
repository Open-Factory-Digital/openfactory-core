"""The model's prose and the code's frame describe one next step, and agree on it (#430).

MEASURED LIVE: a person reported controls cut off at smaller window heights. The product role
wrote "I'm not proposing a requirement for it. No existing requirement promises the Home screen
won't clip … say the word and I'll draft it", and ended with `[[DEFEITO]]`. The code then
appended, in the same message, "This breaks something we already promised — I will register this
problem to fix, exactly as below:" and the whole drafted card. One message offered, then did, then
asked twice, and claimed a promise the role had just said nobody wrote.

Two causes, two guards:
- the defect marker's instruction never told the model that a card is drafted and shown with its
  own question after its reply (the ticket marker's did);
- the defect frame claimed a broken promise whether or not the marker named one.
"""

from __future__ import annotations

import pytest

import openfactory.product.channel as pc
from openfactory.product import role as role_module
from openfactory.product.role import STAGED_AFTER_YOUR_REPLY, STAGING_MARKERS
from openfactory.product.voice import defect_confirmation, defect_filed
from tests.test_a_card_is_drafted_and_judged_before_the_yes import (  # noqa: F401 — the fixture
    GOOD,
    REPORT,
    _earlier_turns,
    _Reporter,
)
from tests.test_confirmation_by_click import ADMIN, KEY, _project
from tests.test_product_role import _call, _role
from tests.the_chat_turn import chat_turn

LANGUAGES = ("pt-BR", "en")
#: Words a frame may use only when the marker named a written promise.
_PROMISE_WORDS = ("promet", "promise", "requisito", "requirement")


def _instructions() -> list[str]:
    """The answer prompt as the model reads it, one paragraph per instruction."""
    role, harness = _role()
    _call(role, "answer", question="the question")
    return harness.prompts[0].split("\n\n")


# ── the prompt: every staging marker says what comes after the reply ─────────────────────────────

def test_the_markers_that_stage_are_the_ones_the_engine_stages():
    """ASSERT THE SCOPE, so the guard below cannot pass by checking fewer markers."""
    assert set(STAGING_MARKERS) == {
        role_module.REQUEST_MARKER, role_module.DEFECT_MARKER, role_module.TICKET_MARKER,
        role_module.ORDER_MARKER, role_module.QUEUE_MARKER,
        # #448: another pass on a change that waits on its requester, drafted after the reply
        role_module.ADJUST_MARKER,
    }


@pytest.mark.parametrize("marker", STAGING_MARKERS)
def test_every_staging_marker_tells_the_model_the_platform_asks_after_it(marker):
    paragraphs = [p for p in _instructions() if marker in p]

    assert paragraphs, f"{marker} is no longer instructed in the answer prompt"
    assert STAGED_AFTER_YOUR_REPLY in paragraphs[0], (
        f"{marker}'s instruction does not say the platform prepares it after the reply and asks "
        f"its own question — the model will offer or ask in prose, and the frame asks again")


def test_the_phrase_forbids_offering_and_asking():
    assert "do NOT offer" in STAGED_AFTER_YOUR_REPLY
    assert "do NOT ask them to confirm" in STAGED_AFTER_YOUR_REPLY
    assert "with its own question" in STAGED_AFTER_YOUR_REPLY


# ── the frame: claims no more than the marker carried ───────────────────────────────────────────

@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("card", ["", "## What is happening\n\nd"])
def test_a_defect_that_names_no_requirement_is_never_framed_as_a_broken_promise(language, card):
    said = defect_confirmation(violates=None, language=language, card=card, title="t").lower()

    for word in _PROMISE_WORDS:
        assert word not in said, f"the frame claims a promise the marker did not carry: {said!r}"


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("card", ["", "## What is happening\n\nd"])
def test_a_defect_that_names_a_requirement_says_which_promise_it_breaks(language, card):
    said = defect_confirmation(violates=7, language=language, card=card, title="t")

    assert "7" in said
    assert any(w in said.lower() for w in ("requisito 7", "requirement 7"))


def test_the_requirement_is_named_in_the_conversations_language():
    assert "requirement 7" in defect_filed(ref="1", violates=7, language="en")
    assert "requisito" not in defect_filed(ref="1", violates=7, language="en")
    assert "requisito 7" in defect_filed(ref="1", violates=7, language="pt-BR")


# ── through the engine: the message a person reads ─────────────────────────────────────────────

def test_a_staged_defect_with_no_requirement_does_not_claim_one(_earlier_turns):  # noqa: F811
    world = _Reporter(GOOD, violates=None)

    asked = str(chat_turn(_project(), text=REPORT, user=ADMIN, thread=KEY, module=world))

    assert pc.find_waiting(KEY, KEY)[1]["kind"] == "defect"
    frame = asked.split("\n\n", 1)[1]      # after the role's own words
    assert "não está funcionando como deveria" in frame
    assert "prometemos" not in frame and "prometeu" not in frame and "requisito" not in frame


def test_a_staged_defect_with_a_requirement_names_it(_earlier_turns):  # noqa: F811
    world = _Reporter(GOOD, violates=7)

    asked = str(chat_turn(_project(), text=REPORT, user=ADMIN, thread=KEY, module=world))

    assert "o que o requisito 7 prometeu" in asked
