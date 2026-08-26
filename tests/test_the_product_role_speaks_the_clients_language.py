"""The product role spoke Brazilian Portuguese to whoever the registry named (#160).

Six composers in `product/followup.py` — the delivery announcement, the acceptance question, the
question batch, the two chases and the release question — wrote pt-BR unconditionally. They are
the sentences a CLIENT reads, on a product whose `DEFAULT_LANGUAGE` is English, and the first
enterprise deployment is not Brazilian.

TRANSLATED IN A TABLE, NEVER GENERATED, for the reason `voice.py` gives beside its own: these are
the strings whose jargon-freedom is asserted, and a model-produced translation puts exactly the
operator vocabulary this surface exists to keep out back into the client's channel, in a language
nobody is checking.

The guard this card asks for is at the bottom: every composer that reaches a client either takes
the language or is named here as a surface that deliberately does not.
"""

from __future__ import annotations

import inspect

import pytest

from openfactory.product import followup
from openfactory.product.voice import DEFAULT_LANGUAGE

COMPOSERS = ("ask_text", "ask_batch", "chase_text", "acceptance_question",
             "decision_chase_text", "delivered_text", "release_question")


def _a_loop(subject="7", **context):
    from openfactory.product.followup import Loop

    return Loop(kind="delivery", subject=subject, state="open", ts="2026-08-20T00:00:00+00:00",
                context={"asked": "what has to be true?", "title": "Card", **context})


# ── 1. every composer takes it ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", COMPOSERS)
def test_every_composer_ACCEPTS_the_clients_language(name):
    assert "language" in inspect.signature(getattr(followup, name)).parameters, (
        f"`{name}` writes to a client and cannot be told which language they read")


@pytest.mark.parametrize("name", COMPOSERS)
def test_and_none_of_them_still_WELDS_it(name):
    """A composer that takes the parameter and ignores it is the defect wearing a fix. Two
    languages in, two different sentences out — asked of the function, not of its source."""
    fn = getattr(followup, name)
    kwargs = {"loop": _a_loop()} if "loop" in inspect.signature(fn).parameters else {}
    if name == "ask_batch":
        kwargs = {"pairs": [(_a_loop("1"), ""), (_a_loop("2"), "")]}
    if name == "release_question":
        kwargs = {"requirement": "7", "where": "https://x"}

    pt = fn(**kwargs, language="pt-BR")
    en = fn(**kwargs, language="en")

    assert pt and en and pt != en, f"`{name}` answers the same text in both languages"


#: Words that can only be Portuguese, chosen because they are the JOINING words a half-migration
#: leaves behind — an article, a preposition, a connective. A partial weld shows up here and not
#: in "the two languages differ", which stays true while one fragment of the sentence is welded.
_PORTUGUESE = (" do requisito ", " o que foi pedido", " está ", " não ", " para ", " que ")


@pytest.mark.parametrize("name", COMPOSERS)
def test_and_no_FRAGMENT_of_the_sentence_is_left_welded(name):
    """"The two languages differ" is satisfied by a sentence with one tabled word in it. A
    half-migrated composer — the body tabled, the `about` clause welded — reads as English with a
    Portuguese phrase inside, which is worse than either language alone."""
    fn = getattr(followup, name)
    kwargs = {"loop": _a_loop()} if "loop" in inspect.signature(fn).parameters else {}
    if name == "ask_batch":
        kwargs = {"pairs": [(_a_loop("1"), ""), (_a_loop("2"), "")]}
    if name == "release_question":
        kwargs = {"requirement": "7", "where": "https://x"}

    said = fn(**kwargs, language="en").lower()
    left = [word for word in _PORTUGUESE if word in said]

    assert not left, f"`{name}` answers English with {left} still in it"


@pytest.mark.parametrize("name", COMPOSERS)
def test_and_saying_nothing_answers_in_the_products_own_default(name):
    """`DEFAULT_LANGUAGE` is English on purpose — the words a client reads default to the language
    of nobody's deployment in particular, and a client who speaks another is NAMED in the registry
    rather than assumed. A composer defaulting to pt-BR was that decision quietly reversed."""
    fn = getattr(followup, name)
    kwargs = {"loop": _a_loop()} if "loop" in inspect.signature(fn).parameters else {}
    if name == "ask_batch":
        kwargs = {"pairs": [(_a_loop("1"), ""), (_a_loop("2"), "")]}
    if name == "release_question":
        kwargs = {"requirement": "7", "where": "https://x"}

    assert fn(**kwargs) == fn(**kwargs, language=DEFAULT_LANGUAGE)


def test_a_language_NOBODY_translated_gets_understandable_english():
    """Never a `KeyError` in a chat listener, and never silence: an untranslated language reads
    English rather than nothing."""
    said = followup.delivered_text(_a_loop(), language="fi")

    assert said and said == followup.delivered_text(_a_loop(), language="en")


# ── 2. the round hands it down ──────────────────────────────────────────────────────────────────

#: Call sites that compose for a client and are NOT handed a language, each with the reason.
#: Empty, and it must stay so unless somebody writes the reason next to the name.
_SYSTEM_SURFACES_BY_DESIGN: set[str] = set()


def _composer_calls() -> list[tuple[str, int, bool]]:
    """Every `followup.<composer>(…)` in the round: `(name, line, was told the language)`.

    ONE WALK, DRIVEN BY BOTH GUARDS BELOW. They had a walk each, so neutering the one that finds
    offenders left the one that counts them green — the same reachability hole those two guards
    exist to close, in the guards themselves. Caught by a mutation, twice in this codebase now.
    """
    import ast

    from openfactory.runtime.temporal import activities

    out = []
    for node in ast.walk(ast.parse(inspect.getsource(activities))):
        if not (isinstance(node, ast.Call) and getattr(node.func, "attr", "") in COMPOSERS):
            continue
        if getattr(getattr(node.func, "value", None), "id", "") != "followup":
            continue
        out.append((node.func.attr, node.lineno,
                    any(k.arg == "language" for k in node.keywords)))
    return out


def test_every_call_site_in_the_round_passes_the_language():
    """THE DELIVERABLE THIS CARD NAMES. The composers taking the parameter is half a fix: the
    round that calls them had `lang` in scope the whole time and passed it to some and not
    others, so a client could read one message in their language and the next in Portuguese."""
    unsaid = [f"{name}:{line}" for name, line, told in _composer_calls()
              if not told and name not in _SYSTEM_SURFACES_BY_DESIGN]

    assert not unsaid, (
        "these compose a message for a client without being told which language they read — "
        f"pass the project's own, or name the composer in `_SYSTEM_SURFACES_BY_DESIGN` with why: "
        f"{unsaid}")


def test_and_the_guard_is_actually_LOOKING():
    """A walk that matched nothing would report no offenders. The round calls every one of these,
    and this asks the SAME walk rather than a second copy of it."""
    seen = {name for name, _line, _told in _composer_calls()}

    assert len(seen) >= 5, f"the walk found only {sorted(seen)} — the round moved"
