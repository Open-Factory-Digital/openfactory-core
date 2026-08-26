"""No gesture exists in one language only (#161, the product owner's rule, 2026-08-21).

    *"this has to be fixed everywhere … we cannot have anything in Portuguese only, or in
    English only"* — the product owner, on being shown the measurement below.

The pilot typed "you can merge" at a merge gate on an `en` project and was answered with a button
asking him to decide again. The Portuguese twin — "pode dar o merge" — had worked since #153,
added the day he typed THAT. Every row in these two matchers grew the same way: one live failure
at a time, in whichever language the failure happened to arrive in.

So the fix that matters is not a string. It is this file, which states the invariant as a property
over BOTH matchers and makes a monolingual row impossible to add:

  1. every intent is reachable by an equivalent sentence in EVERY catalogued language;
  2. every ROW of both `_PATTERNS` tables is exercised by at least one of those sentences — so a
     row added tomorrow fails here until somebody writes it in every language;
  3. the negative twin, because a matcher that accepts everything is symmetric and useless.

THE TABLE IS THE DELIVERABLE. A regex diff cannot be reviewed for this — the asymmetry lives in a
connector, a copula, a noun — and it was found by running sentences, not by reading patterns. Four
of the five gaps this file first measured were invisible in the source: `record … that`, `is a
duplicate of`, `is out of scope`, `rewrite the criteria of`.
"""

from __future__ import annotations

import pytest

from openfactory.actions import floor_intents as fi
from openfactory.product import intents as pi

#: Every language these matchers claim to speak. A row that answers in a subset of this is the
#: defect, whichever subset it is.
LANGUAGES = ("pt-BR", "en")

#: intent → one equivalent sentence per language. Equivalent means A PERSON WOULD TYPE EITHER to
#: mean the same thing — not a literal translation, which is how "pode dar o merge" and
#: "you can merge" differ in shape and are the same gesture.
FLOOR: dict[str, dict[str, str]] = {
    "merge":   {"pt-BR": "pode fazer o merge", "en": "you can merge"},
    "discard": {"pt-BR": "descarta esse", "en": "discard it"},
    # THE PERMISSION SHAPE IS ITS OWN ROW OF THE TABLE, for both gate verbs. The imperative and
    # the permission are two ways to answer the same question and they live in one pattern — so a
    # table carrying only the imperative leaves the half this card was opened for unexercised.
    # Measured: reverting `discard`'s permission form to Portuguese-only kept this file green.
    "merge/permission":   {"pt-BR": "pode fazer o merge", "en": "you can merge"},
    "discard/permission": {"pt-BR": "pode descartar", "en": "you can discard it"},
    "adjust":  {"pt-BR": "ajusta: usa o cache do redis",
                "en": "adjust: use the redis cache"},
    # THE REPETITION IS THE VERB (#181), and it has to repeat in both languages: the row matches
    # on "again"/"de novo", so a table carrying only one of them leaves half the gesture to a
    # client to discover. The permission shape is its own row here too, for the reason the two
    # gate verbs above have one — at a merge gate the platform has just asked a question, and
    # people answer a question with permission as often as with an order.
    "review":  {"pt-BR": "revisa de novo", "en": "review it again"},
    "review/permission": {"pt-BR": "pode revisar de novo", "en": "you can re-review it"},
    "stop":    {"pt-BR": "mata o job 106", "en": "stop job 106"},
    "resume":  {"pt-BR": "retoma o 106", "en": "resume 106"},
    "skip":    {"pt-BR": "pula o 106", "en": "skip 106"},
}

#: The product role's, including the SHAPES that are separate rows: an imperative, a first-person
#: withdrawal and an object-first statement are three ways to retire a requirement, and each was a
#: row that spoke one language.
PRODUCT: dict[str, dict[str, str]] = {
    "announce":     {"pt-BR": "se apresenta", "en": "introduce yourself"},
    "triage":       {"pt-BR": "faz a triagem do quadro", "en": "run the board triage"},
    "needs_action": {"pt-BR": "olha os impedimentos", "en": "check needs-action"},
    "breakdown":    {"pt-BR": "quebra o requisito 4", "en": "break down requirement 4"},
    "accept":       {"pt-BR": "aceita o requisito 4", "en": "accept requirement 4"},
    "accept/as":    {"pt-BR": "da o requisito 4 como acordado",
                     "en": "accept the requirement 4"},
    "decision":     {"pt-BR": "registra no requisito 4 que vamos usar postgres",
                     "en": "record on requirement 4 that we will use postgres"},
    "drop":         {"pt-BR": "cancela o requisito 4, mudou o escopo",
                     "en": "drop requirement 4, the scope changed"},
    "drop/withdrawn": {"pt-BR": "nao vamos mais fazer o requisito 4",
                       "en": "we are not building requirement 4 any more"},
    "drop/state":   {"pt-BR": "o requisito 4 nao vale mais",
                     "en": "requirement 4 is out of scope"},
    "close":        {"pt-BR": "fecha o card 511 como duplicado do 288",
                     "en": "close card 511 as a duplicate of 288"},
    "close/state":  {"pt-BR": "o card 511 e uma duplicata do 288",
                     "en": "card 511 is a duplicate of 288"},
    "align":        {"pt-BR": "realinha o card 511 com o requisito 4",
                     "en": "realign card 511 to requirement 4"},
    "align/criteria": {"pt-BR": "reescreve os criterios do card 511 pelo requisito 4",
                       "en": "rewrite the criteria of card 511 from requirement 4"},
    "refine":       {"pt-BR": "reescreve os criterios do 511",
                     "en": "rewrite the criteria of 511"},
    "baseline":     {"pt-BR": "faz o levantamento do produto",
                     "en": "start a survey of the code"},
    "fact":         {"pt-BR": "anota que o fechamento e no dia 5",
                     "en": "note down that closing is on the 5th"},
    "queue":        {"pt-BR": "o que entra agora", "en": "what's next in the queue"},
    "queue/go":     {"pt-BR": "podemos comecar entao", "en": "can we start then"},
    "status":       {"pt-BR": "situacao", "en": "status"},
}


def _intent(got) -> str | None:
    if got is None:
        return None
    return got[0] if isinstance(got, tuple) else getattr(got, "kind", None)


def _cases(table):
    return [(name, lang, said) for name, langs in table.items()
            for lang, said in langs.items()]


# ── 1. the same gesture, in every language ──────────────────────────────────────────────────────

@pytest.mark.parametrize("name,lang,said", _cases(FLOOR))
def test_every_floor_gesture_answers_in_every_language(name, lang, said):
    assert _intent(fi.match_floor_intent(said)) == name.split("/")[0], (
        f"{said!r} ({lang}) is not the gesture its twin in the other language is — which is how "
        f"'pode dar o merge' worked for four months and 'you can merge' did not")


@pytest.mark.parametrize("name,lang,said", _cases(PRODUCT))
def test_every_product_gesture_answers_in_every_language(name, lang, said):
    assert _intent(pi.match_intent(said)) == name.split("/")[0], (
        f"{said!r} ({lang}) reaches no intent — the row it belongs to speaks another language")


@pytest.mark.parametrize("table", [FLOOR, PRODUCT], ids=["floor", "product"])
def test_the_table_itself_covers_every_language(table):
    """A row written in one language HERE would let the guard pass while proving half of it."""
    for name, langs in table.items():
        assert set(langs) == set(LANGUAGES), f"{name} is only stated in {sorted(langs)}"


# ── 2. every ROW is exercised, so a monolingual one cannot be added ──────────────────────────────

@pytest.mark.parametrize("module,table,attr", [
    (fi, FLOOR, "_PATTERNS"),
    (pi, PRODUCT, "_PATTERNS"),
], ids=["floor", "product"])
def test_every_row_of_the_matcher_is_reached_by_the_table(module, table, attr):
    """THE PART THAT GENERALISES. Without it, a new row added in one language passes every guard
    above — they only assert about sentences somebody thought to write down.

    Matching is asked of the ROW's own pattern rather than of the matcher, because the matcher
    stops at the first row that accepts: two rows for one intent would leave the second one
    unexercised while the intent looked covered.
    """
    sentences = [said for langs in table.values() for said in langs.values()]

    unreached = []
    for index, (name, pattern) in enumerate(getattr(module, attr)):
        if not any(pattern.search(said) for said in sentences):
            unreached.append(f"{index}:{name}")

    assert not unreached, (
        f"these rows are reached by no sentence in the table: {unreached} — add the gesture in "
        f"EVERY language above, or the row is one a client discovers for us")


# ── 3. the negative twin ────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("said", [
    # A NEGATED ORDER IS THE OPPOSITE ORDER, in both languages.
    "do not merge yet", "nao mergeia ainda",
    # THESE TWO DEPEND ON THE NEGATOR LIST ITSELF, and the ones above did not: bare "merge" is in
    # no imperative alternative, so "do not merge yet" is refused by the pattern rather than by
    # the negation. "don't merge it" DOES match `merge it` — it is held only by `_NEGATORS`, and
    # with one pull request at the gate the cost of dropping it is that pull request.
    "don't merge it", "do not merge it yet", "nao faz o merge",
    "we are building requirement 4", "vamos fazer o requisito 4",
    "do not drop requirement 4", "nao cancela o requisito 4",
    "requirement 4 is not cancelled",
    # A QUESTION IS NOT AN ORDER.
    "can you merge?", "posso fazer o merge?",
    "is requirement 4 out of scope?",
    "is card 511 a duplicate of 288?",
    # ORDINARY PROSE THAT HAPPENS TO CARRY A VERB.
    "card 511 is a good card",
    "requirement 4 is in scope",
])
def test_a_matcher_that_accepts_everything_is_symmetric_and_USELESS(said):
    """Widening a vocabulary is only an improvement while the fences hold. Every sentence here
    reads as an instruction to a substring search and as conversation to a person."""
    assert _intent(fi.match_floor_intent(said)) is None, f"floor performed {said!r}"
    assert _intent(pi.match_intent(said)) is None, f"product performed {said!r}"


# ── 4. a hold in its own clause holds what follows (product owner, 2026-08-21) ───────────────────
#
# `_NEGATORS` already carried `wait`, `hold`, `segura` and `espera` for exactly this, and
# `_negated_before` searched only from the verb back to ITS OWN clause start — so the comma that
# makes "hold off, merge it" two clauses put the hold out of reach, and the gate was inverted by
# the sentence typed to stop it. The bare-verb path had no fence at all beyond the question test.

@pytest.mark.parametrize("said", [
    # THE THREE THAT WERE MEASURED LANDING A PULL REQUEST.
    "hold off, merge it",
    "wait, discard it",
    "segura, pode fazer o merge",
    # …the same shape reaching the OTHER path — a bare verb in a later clause.
    "espera, mergeia",
    "wait, merge",
    "espera o CI ficar verde, ai mergeia",
    "wait for CI to finish, then merge it",
    # …in both directions, because a person retracts either way.
    "merge it, wait",
    "merge, wait",
    # …and a clause that is only a refusal, which is the same shape wearing another word.
    "nao, mergeia",
    "never, merge",
])
def test_a_hold_in_its_own_clause_holds_the_instruction(said):
    assert fi.match_floor_intent(said) is None, (
        f"{said!r} was performed — the gate inverted by the sentence written to stop it")


@pytest.mark.parametrize("said", [
    # THE COUNTEREXAMPLE THE FILE HAS NAMED SINCE THE HOLD LIST WAS WRITTEN: the wait is OVER.
    # It is why the test is "does the clause OPEN with the verb", not "does the word appear".
    "a espera acabou, faz o merge",
    "esperei o suficiente, faz o merge",
    "the waiting is over, merge it",
    # …and ordinary courtesy, which must never read as a hold.
    "ok, merge", "beleza, mergeia", "entao, merge #106",
])
def test_but_a_wait_that_is_OVER_still_instructs(said):
    assert fi.match_floor_intent(said) is not None, (
        f"{said!r} was refused — a sentence saying the wait ended is a sentence that instructs")


# ── 5. the same rule for what the factory SAYS, not only for what it hears ──────────────────────

def test_every_narration_row_exists_in_every_language():
    """The product owner's rule applies to both directions of the conversation. A row that speaks
    one language is a client hearing the deployment default instead of what their project declares
    — and `pick` falls back silently, so nothing goes red and nobody finds out.

    Measured: `split.not-queued` was added with an English row only, and a mutation removing its
    Portuguese twin stayed green because the fallback answered in English and the guard asked only
    whether the string was non-empty."""
    from openfactory.techlead import voice

    monolingual = {key: sorted(row) for key, row in voice.NARRATION.items()
                   if set(row) != set(LANGUAGES)}

    assert not monolingual, (
        f"these narration rows speak a subset of {list(LANGUAGES)}: {monolingual}")


def test_and_no_two_languages_of_a_row_are_the_SAME_string():
    """A row whose translation is a copy of the original is a row nobody translated — it passes
    the check above and says the wrong thing to half the clients.

    A ROW THAT CARRIES NO PROSE IS EXEMPT, and the exemption is DERIVED rather than listed: some
    entries are pure frames — `{mention}{verb} — {reason}`, `⏳ #{issue} — {say}` — whose every
    word arrives already translated from the table that produced it. Those are identical in every
    language by construction, and a hand-written allow-list of them would go stale the day
    somebody adds a fourth.

    The one thing still named by hand is a row whose PROSE really is the same word in both — the
    Backlog column is called Backlog either way — because nothing structural can tell that from a
    translation somebody forgot."""
    import re

    from openfactory.techlead import voice

    same_word_in_both = {"split.to-backlog"}

    def carries_prose(text: str) -> bool:
        """Whether anything survives once the placeholders and punctuation are removed."""
        return bool(re.search(r"[^\W\d_]{2,}", re.sub(r"\{[^}]*\}", " ", text)))

    copied = sorted(key for key, row in voice.NARRATION.items()
                    if len(set(row.values())) == 1
                    and key not in same_word_in_both
                    and any(carries_prose(v) for v in row.values()))

    assert not copied, f"these rows carry the same PROSE in every language: {copied}"
