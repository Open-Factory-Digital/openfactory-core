"""The PO gesture matcher knew four negators, all Portuguese (#161).

`_NOT_NEGATED` — the lookbehind that stops "não fecha o #511" from CLOSING #511 — listed
`não / nao / nunca / jamais` and nothing else. The floor's own `_NEGATORS`, one file over, has
always carried both languages. Two homes for one question, and the weaker one guards the surface
that writes on a client's board with no confirmation behind it.

THE TWO LISTS ARE ONE MECHANISM. `_BRIDGE` admits a negator so the lookbehind is the thing that
refuses it: a negator the bridge does not carry can never reach the position the lookbehind
watches, so the lookbehind decides nothing about it and the clause anchor is all that is left.
That anchor has already been widened once in this file's history.

AND `no` IS DELIBERATELY ABSENT. It is how a Spanish or English speaker negates, and in Portuguese
it is *in the*: "no PR 101 faz o merge" is an ordinary instruction with `no` sitting immediately
before the verb. Admitting it would refuse the sentence this platform exists to obey. That is the
collision discipline #157 wrote down for `ta` — a word enters only if, as it appears here, it can
mean nothing else in every catalogued language.
"""

from __future__ import annotations

import re

import pytest

from openfactory.product.intents import _BRIDGE, _NOT_NEGATED, match_intent

NEGATORS = ("não", "nao", "nunca", "jamais", "nem", "never", "don't", "dont", "do not")


# ── 1. the negators the matcher refuses ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("word", NEGATORS)
def test_a_negated_gesture_is_REFUSED(word):
    """`accept` writes on a client's board with no confirmation behind it. A negation read as an
    instruction is the one shape whose meaning inverts while every other signal stays identical."""
    assert match_intent(f"{word} aceita o requisito 1") is None, (
        f"{word!r} did not stop the gesture — the negation was obeyed as an order")


def test_and_the_gesture_itself_still_WORKS():
    """The positive twin. A lookbehind that refused everything would be a surface nobody can use,
    and it would look exactly like a careful one."""
    got = match_intent("aceita o requisito 1")

    assert got and got[0] == "accept"


# ── 2. the two lists are one mechanism ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("word", NEGATORS)
def test_every_negator_the_lookbehind_REFUSES_is_one_the_bridge_CARRIES(word):
    """The property that makes the lookbehind real. A negator missing from the bridge cannot reach
    the position the lookbehind watches, so it is refused by the clause anchor alone — and a
    widening of that anchor turns an instruction NOT to close into a staged close, with no test
    failing.

    ASKED OF THE REGEX, NOT OF ITS SOURCE TEXT: the bridge spells these as alternatives
    (`n[ãa]o`, `don'?t`, `do\\s+not`), so a substring search over the pattern answers about the
    spelling rather than about the language it accepts."""
    assert re.fullmatch(_BRIDGE, f"{word} "), (
        f"the bridge does not carry {word!r} — it never reaches the position the lookbehind "
        f"watches, so the refusal is decided by the clause anchor instead")


@pytest.mark.parametrize("word", NEGATORS)
def test_and_the_lookbehind_REFUSES_it_there(word):
    """The other half, also asked of the regex: a word the bridge carries and the lookbehind does
    not refuse arrives at the verb as an ordinary bridge word — and the gesture fires."""
    assert not re.match(_NOT_NEGATED + "x", f"{word} x"), (
        f"{word!r} is carried into the verb's position and nothing refuses it there")


# ── 3. the collision that keeps `no` out ────────────────────────────────────────────────────────

def test_bare_NO_is_not_a_negator_here():
    """In Portuguese it is *in the*. This is the same discipline that keeps a British `ta` out of
    the assent table, and it is why a Spanish deployment needs the gesture VERBS in a table rather
    than this list guessing."""
    assert "(?<!no )" not in _NOT_NEGATED
    assert not re.search(r"\|no\|", _BRIDGE), "`no` entered the bridge as a negator"


def test_and_an_instruction_that_CONTAINS_it_is_still_obeyed():
    """The sentence the exclusion protects: `no` immediately before the verb, meaning *in the*."""
    got = match_intent("aceita o requisito 1 no board")

    assert got and got[0] == "accept"
