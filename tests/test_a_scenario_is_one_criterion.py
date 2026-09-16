"""#150 slice 4 and #139: what counts as an acceptance criterion, decided once, by the parser.

MEASURED ON `506317a`, five card bodies through the parser, the spec gate and the queue:

    card                                      criteria  gate      queue says ready
    A. the panel's new-card button (title)        0     refused   no
    B. a `Scenario:` under the criteria heading   0     refused   YES
    C. the same scenario, one `- ` per step       3     passes    yes
    D. a card the product role files              0     refused   no
    E. the format the docs teach                  1     passes    yes

B is the platform disagreeing with itself: the queue searched the body for `given ` while the gate
parsed it, so a card was proposed as ready and refused at pickup — and the refusal told its author
to rename `## Acceptance criteria` to `## Acceptance criteria`. C passes the gate and hands the
reviewer three "criteria", one of which is `Given a statement that has been reconciled`.

And #139, one level down: a criterion wrapped across two lines kept its first line, silently. The
count did not change, so nothing looked wrong, and the dropped half is usually the clause that
matters.

So there are three claims here, and each has its guard below:

1. **one scenario is one criterion**, whose text is the whole scenario — and Gherkin is a shape the
   parser reads, never one it requires;
2. **the queue, triage and the gate have one opinion**, the parser's, and the refusal says what it
   actually found;
3. **a multi-line criterion reaches the agent and the reviewer as one item**, and reads back as one.
"""

from __future__ import annotations

import pytest

from openfactory.adapters.tracker.parse import parse_ticket_body
from openfactory.contracts import AcceptanceCriterion, Ticket
from openfactory.orchestrator.machine import JobRunner, SpecValidationError

SCENARIO = """\
## Objective
Close the month.

## Acceptance criteria

Scenario: a reconciled statement locks the month
  Given a statement that has been reconciled
  When the month closes
  Then the balance can no longer be edited
"""

STEPS = """\
## Objective
Close the month.

## Acceptance criteria
- Given a statement that has been reconciled
- When the month closes
- Then the balance can no longer be edited
"""

TAUGHT = """\
## Objective
Close the month.

## Acceptance criteria
- a closed month cannot be edited
"""


def _texts(body: str) -> list[str]:
    return [c.text for c in parse_ticket_body(id="#1", title="t", body=body,
                                              repo="o/app").acceptance_criteria]


def _gate(body: str) -> str:
    """The spec gate's verdict on a body: `""` when it passes, its refusal otherwise."""
    ticket = parse_ticket_body(id="#1", title="t", body=body, repo="o/app")
    try:
        JobRunner._spec_validation(None, ticket)
    except SpecValidationError as refused:
        return str(refused)
    return ""


def _queue_ready(body: str) -> bool:
    from openfactory.product.queue import readiness
    from openfactory.product.triage import Ticket as Card

    card = Card(number="1", title="t", body=body, state="open", column="Backlog")
    return readiness([card]).ready == ["1"]


# ── 1. one scenario is one criterion ────────────────────────────────────────────────────────────

def test_a_scenario_under_the_criteria_heading_is_one_criterion_carrying_the_whole_scenario():
    """Row B: it parsed as none, and the gate refused a card written the way the operator asked."""
    assert _texts(SCENARIO) == [
        "Scenario: a reconciled statement locks the month\n"
        "Given a statement that has been reconciled\n"
        "When the month closes\n"
        "Then the balance can no longer be edited"]


def test_a_scenario_written_one_bullet_per_step_is_still_one_criterion():
    """Row C: three criteria, and the reviewer asked whether a `Given` had been met."""
    assert _texts(STEPS) == [
        "Given a statement that has been reconciled\n"
        "When the month closes\n"
        "Then the balance can no longer be edited"]


def test_two_scenarios_are_two_criteria_with_or_without_a_scenario_line():
    headed = ("## Acceptance criteria\nScenario: one\n  Given a\n  Then b\n\n"
              "Scenario: two\n  Given c\n  Then d\n")
    bare = "## Acceptance criteria\n- Given a\n- When b\n- Then c\n- Given d\n- Then e\n"

    assert _texts(headed) == ["Scenario: one\nGiven a\nThen b", "Scenario: two\nGiven c\nThen d"]
    assert _texts(bare) == ["Given a\nWhen b\nThen c", "Given d\nThen e"]


def test_a_portuguese_scenario_in_a_code_fence_is_read_without_its_fence():
    body = ("## Critérios de aceite\n```gherkin\nCenário: saldo\n  Dado um extrato conciliado\n"
            "  Quando o mês fecha\n  Então o saldo não pode mais ser editado\n"
            "  E o fechamento aparece no histórico\n```\n")

    assert _texts(body) == [
        "Cenário: saldo\nDado um extrato conciliado\nQuando o mês fecha\n"
        "Então o saldo não pode mais ser editado\nE o fechamento aparece no histórico"]


def test_an_outlines_examples_table_belongs_to_its_scenario():
    body = ("## Acceptance criteria\nScenario Outline: split\n  Given a total of <total>\n"
            "  Then it splits into <parts>\n\n  Examples:\n    | total | parts |\n"
            "    | 100   | 25,75 |\n")

    [only] = _texts(body)
    assert only.endswith("Examples:\n| total | parts |\n| 100   | 25,75 |"), only


def test_gherkin_is_read_not_required():
    """Plenty of good criteria are not behaviour. A plain bullet next to a scenario stays its own
    criterion, and a bullet that merely starts with `When` is not a step of anything."""
    body = ("## Acceptance criteria\n- `tests/test_store.py` covers each rule\n"
            "Scenario: saved\n  Given a task\n  When it is saved\n  Then it is listed\n"
            "- When the export fails, an error is shown\n"
            "- When nothing is exported, nothing is written\n")

    assert _texts(body) == [
        "`tests/test_store.py` covers each rule",
        "Scenario: saved\nGiven a task\nWhen it is saved\nThen it is listed",
        "When the export fails, an error is shown",
        "When nothing is exported, nothing is written"]


def test_a_scenario_line_with_nothing_under_it_is_a_sentence_not_a_criterion():
    """The gate must not be defanged by a heading-shaped sentence."""
    assert _texts("## Acceptance criteria\nScenario: to be written\n\nSome prose.\n") == []


# ── #139: a wrapped criterion keeps its tail ────────────────────────────────────────────────────

def test_a_criterion_wrapped_across_two_lines_keeps_the_second_line():
    body = ("## Objective\nDo the thing.\n\n## Acceptance criteria\n\n"
            "- A short one-line criterion.\n"
            "- A longer criterion that a human wrapped across\n"
            "  two lines because it did not fit in eighty columns.\n"
            "- Another single-line one.\n")

    assert _texts(body) == [
        "A short one-line criterion.",
        "A longer criterion that a human wrapped across two lines because it did not fit in "
        "eighty columns.",
        "Another single-line one."]


def test_a_wrapped_step_joins_its_step_and_a_nested_bullet_stays_a_bullet():
    body = ("## Acceptance criteria\nScenario: s\n  Given a file\n  Then it is created and\n"
            "    never executed\n- outer\n  - inner\n")

    assert _texts(body) == ["Scenario: s\nGiven a file\nThen it is created and never executed",
                            "outer", "inner"]


def test_the_scope_lists_keep_their_wrapped_tails_too():
    body = ("## Out of scope\n- changing the signature of `split`, which three\n"
            "  callers outside this repository depend on\n\n  a paragraph after a blank line\n")

    ticket = parse_ticket_body(id="#1", title="t", body=body, repo="o/app")
    assert ticket.out_of_scope == ["changing the signature of `split`, which three callers outside "
                                   "this repository depend on"]


# ── 2. one opinion ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("body", [
    "",                                                             # A. the panel's title-only card
    SCENARIO,                                                       # B.
    STEPS,                                                          # C.
    TAUGHT,                                                         # E.
    "## Acceptance criteria\nThe balance matches.\n",               # a heading with prose under it
    "Given a statement\nWhen the month closes\nThen it locks\n",    # steps under no heading
    "- [ ] a checkbox under no heading\n",
    "## Definition of Done\n- [ ] it works\n",
])
def test_the_queue_calls_ready_exactly_what_the_gate_takes(body):
    """THE TABLE, RE-MEASURED AS A GUARD. The queue proposing a card the gate refuses is how an
    operator spends a pickup to be told no."""
    assert _queue_ready(body) is (_gate(body) == ""), (_queue_ready(body), _gate(body))


def test_row_b_now_passes_every_reader():
    from openfactory.adapters.tracker.parse import criteria

    assert _gate(SCENARIO) == "" and _queue_ready(SCENARIO) and criteria(SCENARIO)


def test_a_refusal_with_the_heading_present_says_what_is_missing_under_it():
    """It told the author to rename `## Acceptance criteria` to `## Acceptance criteria`."""
    refusal = _gate("## Objective\nx\n\n## Critérios de Aceite\nO saldo bate.\n")

    assert "'Critérios de Aceite'" in refusal, refusal
    assert "Rename" not in refusal and "none of them reads as a criteria heading" not in refusal
    assert "`- `" in refusal and "Scenario:" in refusal


def test_a_refusal_without_a_criteria_heading_still_names_the_headings_it_found():
    refusal = _gate("## Requisitos do negócio\n- algo\n")

    assert "'Requisitos do negócio'" in refusal and "Rename one" in refusal


# ── 3. a multi-line criterion is one item wherever it is rendered ───────────────────────────────

def test_a_multi_line_criterion_renders_as_one_bullet_that_reads_back_as_one_criterion():
    [scenario] = parse_ticket_body(id="#1", title="t", body=SCENARIO,
                                   repo="o/app").acceptance_criteria
    rendered = f"## Acceptance criteria\n{scenario.bullet()}\n- a plain one\n"

    assert rendered.splitlines()[1:4] == [
        "- Scenario: a reconciled statement locks the month",
        "  Given a statement that has been reconciled",
        "  When the month closes"]
    assert _texts(rendered) == [scenario.text, "a plain one"]
    assert AcceptanceCriterion(text="one line").bullet() == "- one line"


def test_a_scenario_with_no_scenario_line_reads_back_whole_once_rendered():
    """Written back as `- Given …` with its later steps indented under it — the plain lines are
    inside that bullet, and dropping them would lose every step after the first."""
    steps = "Given a task\nWhen it is saved\nThen it is listed"
    rendered = f"## Acceptance criteria\n{AcceptanceCriterion(text=steps).bullet()}\n"

    assert _texts(rendered) == [steps]


def _scenario_ticket() -> Ticket:
    return parse_ticket_body(id="#7", title="Close the month", body=SCENARIO, repo="o/app")


def test_the_agent_brief_carries_the_scenario_inside_one_bullet():
    from openfactory.adapters.agent.base import AgentContext, ticket_brief

    brief = ticket_brief(AgentContext(ticket=_scenario_ticket()))

    assert ("- Scenario: a reconciled statement locks the month\n"
            "  Given a statement that has been reconciled\n"
            "  When the month closes\n"
            "  Then the balance can no longer be edited") in brief


@pytest.mark.parametrize("prompt", ["harness", "claude_code"])
def test_the_reviewer_is_handed_one_criterion_not_three(prompt):
    from openfactory.adapters.reviewer.base import ReviewInput

    ri = ReviewInput(ticket=_scenario_ticket(), diff="+ x", validations=[])
    if prompt == "harness":
        from openfactory.adapters.reviewer.harness import build_review_prompt

        text = build_review_prompt(ri)
    else:
        from openfactory.adapters.reviewer.claude_code import ClaudeCodeReviewer

        text = ClaudeCodeReviewer()._prompt(ri)

    section = text.split("## Acceptance criteria\n", 1)[1]
    assert section.startswith("- Scenario: a reconciled statement locks the month\n"
                              "  Given a statement that has been reconciled\n"), section[:200]
    assert "\n- Given" not in section


def test_the_sizer_reads_the_scenario_as_one_criterion():
    from openfactory.adapters.agent.base import AgentContext
    from openfactory.adapters.agent.techlead import _ticket_text

    text = _ticket_text(AgentContext(ticket=_scenario_ticket()))

    assert "- Scenario: a reconciled statement locks the month\n  Given a statement" in text
