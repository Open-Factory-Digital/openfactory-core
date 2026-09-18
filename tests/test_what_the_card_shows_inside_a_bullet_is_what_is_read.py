"""What the card shows inside a bullet is what the factory reads — wrapped with or without an
indent (#163).

#139 fixed the silent truncation of a criterion wrapped across two lines when the continuation is
INDENTED. CommonMark's lazy continuation reads the unindented form the same way, and so does every
renderer a card is shown in — it is one list item:

    - the file is created
    and never executed          →  ['the file is created']            (main, before this)

So the card DISPLAYED the tail inside the bullet and the parser dropped it, and the tail is usually
the operative clause. The unindented wrap is also what a person typing into a plain textarea
produces, which is exactly what the panel's card form offers.

THE RULE IS THE RENDERER'S, AS FAR AS THE RENDERER GOES AND NO FURTHER: a non-blank line directly
under a list item's line continues that item unless it is something that starts a block of its own
(a bullet, a heading, a fence, a thematic break, a quote, a table row). A BLANK line ends the item,
so a paragraph separated from the list is never swallowed. A paragraph glued under a list with no
blank line IS read into the last item — because that is where the card shows it.

Every case goes through `parse_ticket_body`, the one reading the gate, the form, triage and the
queue share.
"""

from __future__ import annotations

import pytest

from openfactory.adapters.tracker.parse import parse_ticket_body
from openfactory.orchestrator.machine import spec_verdict


def _ticket(body: str):
    return parse_ticket_body(id="#1", title="t", body=body, repo="o/app")


def _criteria(section: str) -> list[str]:
    body = f"## Objective\nDo it.\n\n## Acceptance criteria\n{section}"
    return [c.text for c in _ticket(body).acceptance_criteria]


# ── the defect ──────────────────────────────────────────────────────────────────────────────────

def test_a_criterion_wrapped_WITHOUT_an_indent_keeps_its_tail():
    assert _criteria("- the file is created\nand never executed\n") == [
        "the file is created and never executed"]


def test_the_two_ways_of_wrapping_read_the_same():
    lazy = _criteria("- the file is created\nand never executed\n- it is logged\n")
    indented = _criteria("- the file is created\n  and never executed\n- it is logged\n")

    assert lazy == indented == ["the file is created and never executed", "it is logged"]


def test_a_tail_wrapped_over_several_unindented_lines_is_all_kept():
    assert _criteria("- the export is written\nto the bucket the project declares,\n"
                     "and never to a bucket named in the card\n- second\n") == [
        "the export is written to the bucket the project declares, and never to a bucket named in "
        "the card", "second"]


def test_the_scope_lists_read_the_unindented_wrap_too():
    body = ("## In scope\n- the importer, including the\nretry it does on a 429\n\n"
            "## Out of scope\n- changing the signature of `split`, which three\n"
            "callers outside this repository depend on\n")

    ticket = _ticket(body)
    assert ticket.in_scope == ["the importer, including the retry it does on a 429"]
    assert ticket.out_of_scope == ["changing the signature of `split`, which three callers "
                                   "outside this repository depend on"]


def test_a_wrapped_STEP_written_without_an_indent_joins_its_step():
    """One bullet per step, and the person wrapped the `Then`."""
    assert _criteria("- Given a file\n- When the job runs\n- Then it is created\n"
                     "and never executed\n") == [
        "Given a file\nWhen the job runs\nThen it is created and never executed"]


def test_a_tail_that_happens_to_open_with_a_step_word_is_still_the_bullets_tail():
    """`E`, `Mas`, `And`, `When` are ordinary words when no scenario is open — the parser's own
    rule — and a wrapped line is as likely to start with one as with any other."""
    assert _criteria("- o arquivo é criado na pasta do projeto\nE nunca é executado\n"
                     "- segundo\n") == [
        "o arquivo é criado na pasta do projeto E nunca é executado", "segundo"]
    assert _criteria("- the file is created\n  And never executed\n") == [
        "the file is created And never executed"]


# ── where the renderer stops, this stops ────────────────────────────────────────────────────────

def test_a_BLANK_line_ends_the_item_so_a_separate_paragraph_is_never_swallowed():
    assert _criteria("- the file is created\n\nThis paragraph is about something else.\n") == [
        "the file is created"]


def test_a_paragraph_GLUED_under_the_list_is_read_where_the_card_shows_it():
    """The risk the rule carries, stated as a case: with no blank line between them CommonMark puts
    this sentence inside the last bullet, so the person reading the card sees it there — and the
    factory now reads it there too, instead of showing one thing and reading another."""
    assert _criteria("- first\n- second\nNote that this was agreed on Tuesday.\n") == [
        "first", "second Note that this was agreed on Tuesday."]


@pytest.mark.parametrize("interrupting", [
    "### A heading",
    "```",
    "~~~",
    "---",
    "***",
    "___",
    "> a quotation",
    "| a | table |",
    "* another list",
    "+ another list",
    "1. a numbered list",
    "<details>",
])
def test_a_line_that_starts_a_block_of_its_own_is_not_a_tail(interrupting):
    assert _criteria(f"- the file is created\n{interrupting}\n- second\n") == [
        "the file is created", "second"]


def test_what_follows_an_interrupting_line_is_not_a_tail_either():
    """`2.` cannot interrupt a paragraph on its own, but here it is the second item of the numbered
    list the line above opened — not the bullet's tail."""
    assert _criteria("- the file is created\n1. one\n2. two\nand more\n") == [
        "the file is created"]


# ── what #154 settled stays settled ─────────────────────────────────────────────────────────────

def test_a_scenario_on_plain_lines_still_ends_at_the_next_unindented_sentence():
    """No bullet is open here, so there is no item for the sentence to continue."""
    assert _criteria("Scenario: s\n  Given a\n  When b\n  Then c\nThis is a remark.\n") == [
        "Scenario: s\nGiven a\nWhen b\nThen c"]


def test_a_plain_scenario_under_a_bullet_does_not_inherit_the_bullets_open_item():
    """The bullet above was a list item; the scenario the parser opens on a plain line is not, so
    the sentence after it ends the scenario exactly as it does with no bullet above."""
    assert _criteria("- a plain criterion\nScenario: s\n  Given a\n  Then b\nThis is a remark.\n") == [
        "a plain criterion", "Scenario: s\nGiven a\nThen b"]
    assert _criteria("- a plain criterion\nGiven a\nThen b\nThis is a remark.\n") == [
        "a plain criterion", "Given a\nThen b"]


def test_a_table_row_a_scenario_took_ends_the_item_it_was_under():
    assert _criteria("- Given a total of <total>\n- Then it splits into <parts>\n"
                     "| total | parts |\nand this is not a tail of the table\n") == [
        "Given a total of <total>\nThen it splits into <parts>\n| total | parts |"]


def test_a_scenario_line_right_under_a_bullet_still_opens_a_scenario():
    assert _criteria("- `tests/test_store.py` covers each rule\nScenario: saved\n"
                     "  Given a task\n  Then it is listed\n") == [
        "`tests/test_store.py` covers each rule", "Scenario: saved\nGiven a task\nThen it is listed"]


def test_a_given_right_under_a_bullet_still_opens_a_scenario():
    assert _criteria("- a plain criterion\nGiven a task\nThen it is listed\n") == [
        "a plain criterion", "Given a task\nThen it is listed"]


def test_a_scenario_survives_a_blank_line_but_a_lazy_tail_does_not_cross_one():
    assert _criteria("- Given a\n- Then b\n\nA remark after a blank line.\n") == ["Given a\nThen b"]


# ── the refusal names what it did not read ──────────────────────────────────────────────────────

def test_the_parser_says_which_lines_of_the_criteria_section_it_did_not_use():
    from openfactory.adapters.tracker.parse import unread_criteria_lines

    body = ("## Acceptance criteria\nThe balance matches the ledger.\n\n"
            "Scenario: to be written\n\n- a real one\nwith its tail\n\nA closing remark.\n")

    assert unread_criteria_lines(body) == ["The balance matches the ledger.",
                                           "Scenario: to be written", "A closing remark."]
    assert unread_criteria_lines("## Acceptance criteria\n- one\n- two\nand its tail\n") == []
    assert unread_criteria_lines("## Objective\nNo criteria heading at all.\n") == []


def test_the_gates_refusal_quotes_the_lines_under_the_heading_that_read_as_nothing():
    """A heading with prose under it: the refusal used to say only that nothing read as a
    criterion. The author is looking at a sentence they believe IS one, so it is shown back."""
    body = "## Objective\nDo it.\n\n## Acceptance criteria\nThe balance matches the ledger.\n"

    said = spec_verdict(_ticket(body))

    assert "nothing under it reads as a criterion" in said
    assert "The balance matches the ledger." in said


def test_a_long_unread_section_is_quoted_in_part_and_counted():
    lines = "\n\n".join(f"Sentence number {i}." for i in range(1, 8))
    body = f"## Objective\nDo it.\n\n## Acceptance criteria\n{lines}\n"

    said = spec_verdict(_ticket(body))

    assert "Sentence number 1." in said and "Sentence number 7." not in said
    assert "4 more" in said
