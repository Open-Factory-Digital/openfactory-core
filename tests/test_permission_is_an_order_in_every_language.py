"""A gate answered with PERMISSION is a gate answered (#161, measured on the pilot 2026-08-21).

The pilot typed **"you can merge"** into the panel chat with the Merge button on screen, at a
gate whose whole question is "do we land this?". It fell through to the tech-lead, which answered
with prose and a button asking him to decide a second time — and, worse, said *"I'll merge it."*
about a merge it had not performed and would not perform.

IT IS NOT A REGRESSION, and that mattered enough to measure: `match_floor_intent("you can merge")`
returns None on today's matcher and on the one ten commits earlier. What changed is the other
half — `pode dar o merge` was added on the day the pilot typed THAT (#153, with the same button on
the same screen), and the English twin was never written.

So the defect is not a missing string. It is that a vocabulary grown one live failure at a time
grows exactly one language at a time, and the second language reveals what the first one hid —
the same shape this codebase already learned from a second vendor. The guard below is the part
that generalises: every row that accepts the permission form must accept it in EVERY language the
matcher catalogues, so the next language cannot be discovered by a client.
"""

from __future__ import annotations

import pytest

from openfactory.actions.floor_intents import match_floor_intent

#: The two gate verbs — the ones the platform ASKS about, so the ones a person answers with
#: permission rather than with an imperative. `resume`/`skip`/`stop` are recovery verbs the
#: tech-lead dictates verbatim ("Reply `resume #NN`") and they require a ref; they are not in this
#: family and widening them would add risk with no measured need.
GATE_VERBS = ("merge", "discard")


# ── 1. the same gesture, in both languages ──────────────────────────────────────────────────────

@pytest.mark.parametrize("said,intent", [
    # THE SENTENCE THAT WAS TYPED, verbatim.
    ("you can merge", "merge"),
    ("you can merge it", "merge"),
    ("you may merge", "merge"),
    ("you could merge", "merge"),
    ("you can go ahead and merge", "merge"),
    ("you can discard it", "discard"),
    # …and the Portuguese half, which has worked since #153 and must go on working.
    ("pode dar o merge", "merge"),
    ("pode mergear", "merge"),
    ("poderia fazer o merge", "merge"),
    ("pode descartar", "discard"),
])
def test_permission_reads_as_the_order_it_is(said, intent):
    matched = match_floor_intent(said)

    assert matched is not None, f"{said!r} was answered with a button asking again"
    assert matched[0] == intent, matched


def test_the_ref_still_rides_on_it():
    """An instruction's scope is part of the instruction — the permission form is no exception."""
    assert match_floor_intent("you can merge #106") == ("merge", {"ref": "106"})


# ── 2. what permission is NOT ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("said", [
    # THE FIRST PERSON IS A WITHDRAWAL, NOT A GRANT. English does not drop its subject, so a
    # permission form that accepts any subject reads "I'll do it myself" as "go ahead".
    "I can merge it",
    "i could merge this myself",
    # `we` includes the speaker: "we can merge" is a plan, not an instruction.
    "we can merge",
    # A QUESTION IS NOT AN ORDER.
    "can you merge?",
    "can I merge this?",
    # A NEGATED ORDER IS THE OPPOSITE ORDER — and this is the direction that costs a pull request.
    "you can't merge",
    "you cannot merge",
    "you can not merge yet",
    "do not merge yet",
    # THE SENTENCE CARRIES ON PAST THE VERB, so it is somebody thinking out loud.
    "you can merge it later once CI is green",
    "you could merge or you could wait",
])
def test_and_what_is_not_permission_stays_conversation(said):
    assert match_floor_intent(said) is None, f"{said!r} was performed"


# ── 3. the property, so the next language is not found by a client ──────────────────────────────

#: One gesture per language, for each gate verb. A row added here that no matcher accepts is the
#: whole defect, stated once instead of discovered twice.
SAME_GESTURE = {
    "merge": {"pt-BR": "pode fazer o merge", "en": "you can merge"},
    "discard": {"pt-BR": "pode descartar", "en": "you can discard"},
}


@pytest.mark.parametrize("verb", GATE_VERBS)
def test_every_gate_verb_takes_permission_in_EVERY_catalogued_language(verb):
    """The generalisation. `pode dar o merge` worked and `you can merge` did not, for four months,
    because each was added the day somebody hit it — and only that one was hit."""
    answers = {lang: match_floor_intent(said)
               for lang, said in SAME_GESTURE[verb].items()}

    missing = sorted(lang for lang, got in answers.items() if got is None or got[0] != verb)

    assert not missing, (
        f"`{verb}` is answerable by permission in some languages and not in {missing} — which is "
        f"this card's defect, one language over")


def test_the_permission_prefix_has_ONE_home():
    """Reachability, and the shape that let this happen: the Portuguese alternatives were inlined
    in the merge row, so adding the English ones to that row would have left `discard` behind —
    and the next reader would have had two half-lists to keep in step."""
    import inspect

    from openfactory.actions import floor_intents

    src = inspect.getsource(floor_intents)

    assert "_MAY = (" in src, "the permission form is not a named piece"

    # INSIDE THE ROWS ONLY. `pode` is also a courtesy LEADER (`_LEADER_WORDS`), which is a
    # different job — it says a clause may OPEN with it, not that it grants anything. A scan of
    # the whole file reads that as a second spelling and fails on the file's own vocabulary;
    # measured, on this guard, within minutes of writing it.
    rows = src[src.index("_PATTERNS: tuple"):src.index("_BARE: tuple")]

    for verb in GATE_VERBS:
        row = rows[rows.index(f'("{verb}", re.compile('):]
        row = row[:row.index("re.I)),")]
        assert "_MAY" in row, f"the `{verb}` row spells its own permission form again"
    assert "pode|podes|poderia" not in rows, (
        "a row spells the permission form again instead of using `_MAY` — a second spelling is a "
        "second answer, and this file's whole history is two answers drifting")


# ── 4. and the tech-lead may not claim it acted ─────────────────────────────────────────────────

def test_the_guidance_forbids_announcing_an_action_it_has_not_taken():
    """The second half of what the pilot saw: the reply read *"I'll merge it."* and nothing merged.

    `techlead/watch.py::report` already states this rule for the scheduled round — "SAYS WHAT
    HAPPENED, NOT WHAT IT MEANT TO DO … once somebody learns the messages are aspirational, they
    stop trusting all of them" — and the CHAT, which is the surface a person actually answers on,
    never had it. A suggestion is an offer waiting on one more word; a message that announces it
    as done sends the reader away believing the gate is cleared.
    """
    from openfactory.techlead.conversation import _guidance

    said = _guidance(("merge", "resume", "skip"))

    assert "NEVER SAY YOU HAVE DONE IT" in said
    assert "'I'll do it'" in said, "the rule does not name the shape it forbids"
    assert "nothing happens until they answer" in said

    # AND IT NAMES NO CONCRETE VERB, because it is composed into a block that may offer only what
    # the asker's credential can perform. An illustration saying "I'll merge it" to a resume/skip
    # asker breaks the sibling guard in `test_the_techlead_can_see_what_it_reasons_about.py` — a
    # rule about honesty that quietly offers an action is not an improvement.
    #
    # ASKED OF AN ASKER WHO CANNOT MERGE, which is the only composition where the word appearing
    # means anything: with `merge` in the list it appears legitimately, from `_verb_block`.
    for_a_reader_who_cannot = _guidance(("resume", "skip"))

    assert "NEVER SAY YOU HAVE DONE IT" in for_a_reader_who_cannot
    assert "merge" not in for_a_reader_who_cannot.split("WHAT YOU CAN ACTUALLY DO")[1]
