"""The split announcement must be actionable by the person who reads it (measured on the pilot).

podbeam #104 was too large, was split into three, and the board refused one of them. What the
operator received:

    I created all 3, but could not move #121 to TO-DO — drag them on the board, in order,
    or they will never run:
      • #119 — feat(documents): split news and documents … (a) [auto-split of #104]
      • #120 — feat(documents): split news and documents … (b) [auto-split of #104]
      • #121 — feat(documents): split news and documents … (c) [auto-split of #104]

Three defects in one message, and two of them were introduced by #160 the same day:

1. **"drag them" for a SINGLE stuck card.** The row was written by copying the Portuguese, where
   `arrasta` is impersonal and hides the number. In English it lands on the half of the sentence
   the reader acts on: one card or all three?

2. **The list does not say which one is stuck.** Three near-identical titles under a sentence that
   names a bare `#121`, so finding the card to move means cross-referencing a number.

3. **The reason is cut mid-word**, leaving `…with an unaddressed 1/day quota conflict) to).` — a
   dangling `to` and a parenthesis that closes nothing. A reader cannot tell that from a model
   that wrote badly. (Pre-existing, in the message #160 touched.)

A NEVER-MOVED CHILD IS UNREACHABLE by the poller's exact-match TO-DO scan — the code says so where
it logs it. This message is the only thing standing between that card and silence, which is why
its wording is not cosmetic.
"""

from __future__ import annotations

import pytest

from openfactory.runtime.temporal.activities import _clipped
from openfactory.techlead import voice

CHILDREN = "  • #119 — part (a)\n  • #120 — part (b)\n  ⚠ #121 — part (c)  ← NOT QUEUED"


def _say(key: str, language: str, **params) -> str:
    return voice.say(voice.NARRATION, key, language, **params)


# ── 1. one stuck card and several are different sentences ───────────────────────────────────────

@pytest.mark.parametrize("language", ["en", "pt-BR"])
def test_a_single_straggler_is_not_addressed_in_the_plural(language):
    said = _say("split.straggler-one", language, n=3, stuck="#121", children=CHILDREN)

    assert "#121" in said
    assert said != _say("split.stragglers", language, n=3, stuck="#121", children=CHILDREN), (
        "one stuck card and several read identically — the reader cannot tell how many to move")


def test_the_english_singular_says_THAT_ONE_and_the_plural_says_those():
    """The measured defect, in the language that shows it. Portuguese hid this behind an
    impersonal verb, which is exactly why a per-language table needs both rows instead of one
    clever one."""
    one = _say("split.straggler-one", "en", n=3, stuck="#121", children=CHILDREN)
    many = _say("split.stragglers", "en", n=3, stuck="#120, #121", children=CHILDREN)

    assert "drag that one" in one and "it will never run" in one
    assert "drag those" in many and "they will never run" in many


@pytest.mark.parametrize("key", ["split.straggler-one", "split.stragglers"])
@pytest.mark.parametrize("language", ["en", "pt-BR"])
def test_both_rows_exist_in_both_languages_and_carry_the_list(key, language):
    said = _say(key, language, n=3, stuck="#121", children=CHILDREN)

    assert CHILDREN in said, "the children were dropped from the sentence"
    assert "{" not in said, said


# ── 2. the stuck child is marked where the reader is looking ────────────────────────────────────

def test_the_list_marks_WHICH_child_is_out_of_the_queue():
    """The sentence names a ref; the list repeated three near-identical titles under it. A list
    that shows a problem must show it where the problem is."""
    import inspect

    from openfactory.runtime.temporal import activities
    src = inspect.getsource(activities._do_split)

    assert '"split.not-queued"' in src, "nothing marks the stuck child in the list"
    assert "if r in stragglers" in src, (
        "the marker is not decided per child — either every line is marked or none is")


@pytest.mark.parametrize("language", ["en", "pt-BR"])
def test_and_the_marker_is_a_sentence_in_the_projects_language(language):
    marker = _say("split.not-queued", language)

    assert marker and marker != "split.not-queued", "the marker key has no entry"
    assert "{" not in marker


# ── 3. the reason is cut at a word, and says it was cut ─────────────────────────────────────────

def test_a_clipped_reason_never_ends_mid_word():
    """The pilot's own message, verbatim, is the fixture: a hard slice left `conflict) to).`"""
    real = ("Fails Small/Independent: bundles a novel, high-risk scheduling/quota engine change "
            "(single→dual episode generation, with an unaddressed 1/day quota conflict) together "
            "with a UI split")

    got = _clipped(real, 160)

    assert got.endswith("…")
    assert not got.endswith("to…"), f"still cut mid-thought: {got[-30:]!r}"
    assert " to…" not in got


def test_and_never_ends_on_dangling_punctuation():
    assert _clipped("alpha beta, gamma delta", 12).endswith("…")
    assert not _clipped("alpha beta, gamma delta", 12).endswith(",…")
    assert not _clipped("alpha (beta gamma", 7).endswith("(…")


def test_a_reason_that_FITS_is_returned_whole_and_unmarked():
    """The positive twin: an ellipsis on a complete sentence tells the reader something was
    withheld when nothing was."""
    assert _clipped("short enough", 160) == "short enough"
    assert "…" not in _clipped("short enough", 160)


def test_whitespace_is_collapsed_so_the_cap_counts_what_a_reader_sees():
    assert _clipped("a\n\n   b\tc", 160) == "a b c"


def test_a_single_word_longer_than_the_cap_still_returns_something():
    """`rsplit` finds no space, and returning "" would drop the reason entirely — the one thing
    the message exists to carry."""
    got = _clipped("x" * 300, 20)

    assert got.startswith("x") and got.endswith("…") and len(got) <= 21
