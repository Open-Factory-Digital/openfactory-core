"""Reading the board — and the mistake this module exists to prevent.

On 2026-07-26 two tickets sat in "In progress" with no job running, which looks exactly like a board
lying about its own state. They were a human-owned spike whose body says "NOT for the automated
coding pipeline", and an epic whose children were being executed. Both were correct; the reading was
wrong, because it judged a column without opening the ticket.

So the tests below spend more effort on what triage must NOT flag than on what it must.
"""

from __future__ import annotations

import pytest

from openfactory.product.triage import Ticket, TriageReport, triage

CRITERIA = "## Acceptance criteria\n- [ ] it works\n"


def _t(number=1, **kw):
    kw.setdefault("body", CRITERIA)
    kw.setdefault("column", "TO-DO")
    return Ticket(number=number, **kw)


def _kinds(report) -> set[str]:
    return {o.kind for o in report.observations}


# ── what it must NOT flag ───────────────────────────────────────────────────────────────────────

def test_a_human_owned_spike_in_an_active_column_is_NOT_stalled():
    """THE regression. Its body says a person owns it; the column is intended, not rot."""
    t = _t(1, column="In progress", updated_days_ago=90,
           body="**Spike / research issue.** Maintainer/human-owned. NOT for the automated coding "
                "pipeline. Stays OUT of the TO-DO column.\n" + CRITERIA)
    report = triage([t])
    assert "stalled" not in _kinds(report)
    assert "1" in report.skipped and "a person owns this" in report.skipped["1"]


@pytest.mark.parametrize("label", ["spike", "research", "human", "on-hold", "Spike"])
def test_a_label_alone_is_enough_to_claim_a_ticket_out_of_the_pipeline(label):
    t = _t(1, column="In progress", updated_days_ago=90, labels=[label])
    assert "stalled" not in _kinds(triage([t]))


def test_an_epic_stays_open_while_its_children_run():
    """A container is not a stalled ticket — the same misreading in a different costume."""
    epic = _t(1, column="In progress", updated_days_ago=60, labels=["epic"], children=[2])
    child = _t(2, column="In progress", updated_days_ago=1)
    report = triage([epic, child])
    assert "stalled" not in _kinds(report)
    assert "1" in report.skipped


def test_a_ticket_being_actively_worked_is_not_flagged():
    assert triage([_t(1, column="In progress", updated_days_ago=1)]).observations == []


def test_the_skip_list_says_WHY_so_ignoring_something_is_answerable():
    """"you ignored these" must have an answer, or the next pass gets asked to explain itself."""
    t = _t(1, column="In progress", updated_days_ago=90, labels=["epic"], children=[2])
    assert triage([t]).skipped["1"]


# ── what it must flag ───────────────────────────────────────────────────────────────────────────

def test_a_genuinely_stalled_ticket_is_reported():
    report = triage([_t(1, column="In progress", updated_days_ago=30)])
    assert "stalled" in _kinds(report)
    assert "30 days" in report.observations[0].detail


def test_something_waiting_on_a_person_for_a_month_is_reported():
    report = triage([_t(1, column="Needs Action", updated_days_ago=40)])
    assert "waiting-too-long" in _kinds(report)


def test_a_ticket_with_nothing_testable_is_reported_before_it_parks():
    """It would fail the sizing gate hours later, with nobody able to say whether it is done."""
    report = triage([_t(1, body="please make the reports better")])
    assert "no-criteria" in _kinds(report)


@pytest.mark.parametrize("body", [
    "## Critérios de aceite\n- coisa",
    "## Definition of done\n- it works",
    "## AC\n- [ ] a checkbox under a heading the parser knows",
    "## Acceptance criteria\nScenario: reconciled\n  Given a statement\n  When reconciled\n"
    "  Then it locks",
])
def test_a_well_written_ticket_is_not_nagged_for_using_a_different_heading(body):
    """Flagging good tickets because of an unusual heading is how a report teaches people to
    ignore it."""
    assert "no-criteria" not in _kinds(triage([_t(1, body=body)]))


@pytest.mark.parametrize("body", [
    "- [ ] a checkbox is enough",
    "## Definition of done\nit works",
    "Given a statement, When reconciled, Then it locks",
])
def test_a_ticket_pickup_would_refuse_is_flagged_however_testable_it_sounds(body):
    """THESE THREE WERE CALLED WELL WRITTEN, and every one of them is refused at pickup (#150).

    A list of substrings found `- [ ]`, `definition of done` and `given ` in them and kept quiet. The
    spec gate parses the body, finds no criteria under a criteria heading, and refuses — hours
    later, after somebody moved the card to TO-DO on the strength of a report that said nothing was
    wrong. Staying quiet here is not generosity; it is the platform disagreeing with itself."""
    from openfactory.contracts import Ticket as Card
    from openfactory.orchestrator.machine import JobRunner, SpecValidationError

    assert "no-criteria" in _kinds(triage([_t(1, body=body)]))
    with pytest.raises(SpecValidationError):
        JobRunner._spec_validation(None, Card(id="#1", title="t", objective="o", repo="o/app",
                                              raw=body))


def test_done_but_never_closed_is_reported():
    report = triage([_t(1, column="Done", state="open")])
    assert "done-but-open" in _kinds(report)


def test_a_closed_ticket_whose_card_never_moved_is_reported():
    report = triage([_t(1, column="In review", state="closed")])
    assert "closed-elsewhere" in _kinds(report)


def test_an_epic_whose_children_are_all_finished_is_reported():
    epic = _t(1, column="In progress", labels=["epic"], children=[2, 3], updated_days_ago=1)
    kids = [_t(2, state="closed", column="Done"), _t(3, state="closed", column="Done")]
    report = triage([epic, *kids])
    assert "container-complete" in _kinds(report)
    assert "2 of 2 found" in [o.detail for o in report.of_kind("container-complete")][0]


def test_an_epic_with_one_child_still_open_is_left_alone():
    epic = _t(1, column="In progress", labels=["epic"], children=[2, 3], updated_days_ago=1)
    report = triage([epic, _t(2, state="closed", column="Done"), _t(3, column="TO-DO")])
    assert "container-complete" not in _kinds(report)


# ── it reports, it does not act ─────────────────────────────────────────────────────────────────

def test_every_finding_is_a_SUGGESTION_not_a_record_of_something_done():
    """The first pass writes nothing: this role has the least context on first contact and the most
    to misread, and closing a ticket destroys information somebody took effort to write."""
    report = triage([_t(1, column="Done", state="open"),
                     _t(2, body="vague"),
                     _t(3, column="Needs Action", updated_days_ago=40)])
    assert report.observations
    for o in report.observations:
        assert o.suggestion, o
        assert not any(word in o.suggestion.lower() for word in ("i closed", "i moved", "i have"))


def test_the_counts_summarise_without_hiding_the_detail():
    report = triage([_t(1, body="vague"), _t(2, body="also vague")])
    assert report.counts["no-criteria"] == 2
    assert len(report.of_kind("no-criteria")) == 2


# ── recurring passes are diffs ──────────────────────────────────────────────────────────────────

def test_a_later_pass_reports_only_what_is_NEW():
    """A recurring report that lists the same forty things every week is one nobody opens twice."""
    first = triage([_t(1, body="vague")])
    second = triage([_t(1, body="vague"), _t(2, body="also vague")])
    fresh = second.diff(first)
    assert [o.ticket for o in fresh.observations] == ["2"]


def test_the_first_pass_diffs_against_nothing_and_reports_everything():
    report = triage([_t(1, body="vague")])
    assert report.diff(None).observations == report.observations


def test_a_pass_that_found_nothing_new_is_empty_not_a_repeat():
    first = triage([_t(1, body="vague")])
    assert triage([_t(1, body="vague")]).diff(first).observations == []


def test_the_diff_keeps_the_full_counts_so_the_totals_stay_honest():
    """"nothing new" must not read as "nothing wrong" — the backlog of known problems is still
    there, and a reader deciding whether to act needs its size."""
    first = triage([_t(1, body="vague")])
    second = triage([_t(1, body="vague"), _t(2, body="also vague")])
    fresh = second.diff(first)
    assert fresh.counts["no-criteria"] == 2
    assert len(fresh.observations) == 1


def test_an_empty_board_is_not_an_error():
    assert triage([]) == TriageReport()


# ── one opinion about criteria, and it is the parser's (#24 item 7, #150) ───────────────────────

def test_queue_and_triage_ask_the_same_function():
    """Two copies of a marker list had already diverged once. One list fixed that and left the spec
    gate reading the body a third way; now there is one function and it asks the parser."""
    # From-imports of the NAME, because `openfactory.product`'s __init__ re-exports `triage` the
    # FUNCTION over the submodule attribute — `import ... as` resolves the shadowing function.
    from openfactory.product.queue import has_criteria as queue_reads
    from openfactory.product.triage import has_criteria as triage_reads

    assert queue_reads is triage_reads, "a second opinion is growing back"


def test_a_given_when_then_ticket_is_ready_to_propose_when_pickup_would_take_it():
    """The regression the drift caused, pinned from the queue's side — and then the one the fix
    for it caused. This exact body was 'needs_refinement' there while triage called it fine, so the
    queue learned `dado que`; after that it called READY a card the gate refuses, because the steps
    sit under no criteria heading. Under one, the same steps are a criterion to all three readers."""
    from openfactory.contracts import Ticket as Card
    from openfactory.orchestrator.machine import JobRunner, SpecValidationError
    from openfactory.product.queue import has_criteria

    steps = "Dado que o extrato foi importado\nQuando o mês fecha\nEntão o saldo bate"
    bare = Ticket(number="9", title="import", state="open", column="Backlog", body=steps)
    headed = Ticket(number="9", title="import", state="open", column="Backlog",
                    body=f"## Critérios de aceite\n{steps}")

    assert has_criteria(bare) is False
    with pytest.raises(SpecValidationError):
        JobRunner._spec_validation(None, Card(id="#9", title="import", objective="o",
                                              repo="o/app", raw=bare.body))
    assert has_criteria(headed) is True
