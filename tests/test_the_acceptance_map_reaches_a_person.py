"""The reviewer maps every acceptance criterion, and now a surface reads it (#184).

`ReviewResult.acceptance` has been in the schema the model is asked to fill since it was written.
It is parsed into a field. And:

    $ grep -rn "\\.acceptance\\b" openfactory/ | grep -v contracts/review.py | grep -v reviewer/
    (nothing)

Asked for, paid for in tokens, read by no one — this repository's signature defect, inside the
review path.

WHAT IT COST, measured on the pilot. PR #118 was rejected at score 30. What a person at the gate
saw was a decision, a score and four findings. What was also true: four of six criteria were
delivered, both hard constraints held, and the change killed a false alarm that had fired on every
panorama episode ever generated. Reconstructing that took four agents an evening — and the
reviewer had produced the map, in the same pass, for nothing.

A rejection reads as "this is wrong". The honest sentence was "this does most of what it promised
— keep it and finish it", and only the per-criterion map can say which.
"""

from __future__ import annotations

import pytest

from openfactory.review.verdict import criteria, headline, line

#: The pilot's own verdict, as it came back from the reviewer.
PILOT = {
    "decision": "rejected", "score": 30,
    "acceptance": [
        {"criterion": "an honest derived target", "status": "passed"},
        {"criterion": "the ratio stays at or above MIN_RATIO", "status": "passed"},
        {"criterion": "the style promise and what is delivered no longer contradict",
         "status": "failed"},
        {"criterion": "a regression test on the ratio", "status": "passed"},
        {"criterion": "HARD CONSTRAINT — the honesty clamp is intact", "status": "passed"},
        {"criterion": "tell the user this is a short overview", "status": "unknown"},
    ],
    "findings": [{"severity": "critical", "description": "the derived target never reaches the "
                                                         "prompt", "file": "generation.py"}],
}


# ── 1. the tally, and the third state ───────────────────────────────────────────────────────────

def test_every_criterion_is_counted_under_its_own_status():
    got = criteria(PILOT)

    assert (got["passed"], got["failed"], got["unknown"], got["total"]) == (4, 1, 1, 6)
    assert [c["criterion"] for c in got["unmet"]] == [
        "the style promise and what is delivered no longer contradict"]


def test_UNKNOWN_is_its_own_answer_and_folds_into_neither():
    """A criterion the reviewer could not evaluate is not one it passed, and not one it failed.
    Collapsing it either way is the Option-type defect this codebase keeps paying for — and here
    it would either invent a pass nobody earned or a failure nobody found."""
    got = criteria({"acceptance": [{"criterion": "c", "status": "unknown"}]})

    assert got == {"passed": 0, "failed": 0, "unknown": 1, "unmet": [], "total": 1}


def test_a_status_the_reviewer_invented_is_read_as_unknown():
    """The model fills this. A value outside the three must not silently vanish from the tally —
    a criterion that is counted nowhere is one the reader never learns exists."""
    got = criteria({"acceptance": [{"criterion": "c", "status": "probably fine"}]})

    assert got["unknown"] == 1 and got["total"] == 1


def test_a_review_with_no_map_produces_an_empty_tally_not_a_missing_key():
    for verdict in ({"decision": "approved"}, {}, {"acceptance": []}):
        assert criteria(verdict)["total"] == 0


# ── 2. it reaches the gate, unmet first ─────────────────────────────────────────────────────────

def test_the_gate_names_the_criterion_that_was_NOT_met():
    got = headline(PILOT)

    assert any("criterion NOT met" in p and "no longer contradict" in p for p in got["points"]), (
        f"the gate does not say which criterion failed: {got['points']}")


def test_and_the_unmet_one_comes_BEFORE_the_findings():
    """What the ticket ASKED FOR outranks what the reviewer noticed on its own. A person at a gate
    is deciding whether the change does its job; a finding is evidence towards that question, not
    the question."""
    got = headline(PILOT)["points"]

    unmet = next(i for i, p in enumerate(got) if p.startswith("criterion NOT met"))
    finding = next(i for i, p in enumerate(got) if p.startswith("critical:"))

    assert unmet < finding, got


def test_the_tally_is_on_the_gate_so_REJECTED_stops_meaning_only_wrong():
    """The sentence this card exists for: four of six, not zero of six."""
    got = headline(PILOT)

    assert any("4 passed, 1 failed, 1 unknown" in p for p in got["points"]), got["points"]


def test_and_the_tech_leads_line_carries_it_too():
    """That line is what reaches a channel, where "rejected (30)" alone is the sentence that makes
    somebody discard a branch that did most of what it promised."""
    said = line(PILOT)

    assert "criteria: 4 passed, 1 failed, 1 unknown" in said
    assert "not met: the style promise" in said


@pytest.mark.parametrize("verdict", [
    {"decision": "approved", "score": 90},
    {},
    None,
])
def test_a_review_that_mapped_NOTHING_adds_no_noise(verdict):
    """The negative twin. A gate that grows a line saying "0 passed, 0 failed" about a reviewer
    that never filled the field is a gate teaching people to skim past it."""
    got = headline(verdict)

    assert not [p for p in got["points"] if "criteria" in p or "criterion" in p]
    assert got["criteria"]["total"] == 0


def test_criteria_is_present_on_EVERY_shape_of_the_answer():
    """Including the absent ones. A caller that must check whether the key exists is a caller that
    will forget — and the empty tally reads correctly as "this review mapped nothing"."""
    for got in (headline(None), headline({}), headline(PILOT), headline({}, unread=True),
                headline({**PILOT, "stale": "a pass rewrote it"})):
        assert "criteria" in got, got["word"]


def test_a_STALE_verdict_stamps_the_criteria_as_past_too():
    """`was:` exists because a verdict about code that is gone is not a verdict. A criterion it
    mapped then is no more current than a finding it made then."""
    got = headline({**PILOT, "stale": "a pass rewrote the pull request"})

    assert got["word"] == "Review out of date"
    assert all(p.startswith("was: ") for p in got["points"]), got["points"]


# ── 3. the contradiction ────────────────────────────────────────────────────────────────────────

def test_rejected_while_every_mapped_criterion_is_MET_is_said_out_loud():
    """It may be right — a reviewer can refuse on something the ticket never asked for. What it
    may not be is hidden behind whichever half the reader happens to look at."""
    got = headline({"decision": "rejected", "score": 40,
                    "acceptance": [{"criterion": "a", "status": "passed"},
                                   {"criterion": "b", "status": "passed"}]})

    assert any("every criterion it mapped is met" in p for p in got["points"]), got["points"]


def test_but_an_APPROVED_one_with_every_criterion_met_says_nothing_extra():
    got = headline({"decision": "approved", "score": 95,
                    "acceptance": [{"criterion": "a", "status": "passed"}]})

    assert not any("still rejected" in p for p in got["points"])


# ── 4. it fits a phone ──────────────────────────────────────────────────────────────────────────

def test_many_unmet_criteria_are_counted_rather_than_listed():
    """The gate item is read on a phone. The whole map belongs on the card; the gate names the
    first two and says how many more there are — never a wall."""
    many = {"decision": "rejected",
            "acceptance": [{"criterion": f"criterion {n}", "status": "failed"} for n in range(7)]}

    got = headline(many)["points"]
    named = [p for p in got if p.startswith("criterion NOT met")]

    assert len(named) == 2, got
    assert any("5 more unmet" in p for p in got), got


# ── 5. and it survives the trip to the gate ─────────────────────────────────────────────────────
#
# #184's first cut taught the RENDERER to show the map and stopped there. On the pilot the map
# reached the tech-lead's channel — which reads the whole `ReviewResult` — and arrived EMPTY at the
# merge gate, which reads the workflow's `verdict` query. That query's projection is hand-listed,
# and `acceptance` was never in it: the fix worked on one surface and was invisible on the one
# where somebody decides. Rendering something nobody delivers is this repository's signature
# defect wearing the fix as a disguise.

def test_the_verdict_QUERY_carries_the_acceptance_map():
    """Reachability, across the seam that actually broke it."""
    import ast
    import inspect

    from openfactory.runtime.temporal import workflow as wf

    src = inspect.getsource(wf.JobWorkflow)
    published = [n for n in ast.walk(ast.parse(src.lstrip()))
                 if isinstance(n, ast.Dict)
                 and {getattr(k, "value", None) for k in n.keys} >= {"decision", "score", "gates"}]

    assert published, "the verdict projection is gone — this guard measures nothing"
    for projection in published:
        keys = {getattr(k, "value", None) for k in projection.keys}
        assert "acceptance" in keys, (
            f"the verdict query publishes {sorted(k for k in keys if k)} and drops the "
            f"per-criterion map — the gate cannot show what nobody sends it")


def test_and_it_is_TRIMMED_like_everything_else_that_crosses_the_wire():
    """A query response is fetched on every panel refresh. The criterion text identifies it to a
    reader; the evidence is prose and belongs to the closed job's result."""
    import ast
    import inspect

    from openfactory.runtime.temporal import workflow as wf

    # READ AS SOURCE, NOT SLICED ON A BRACKET. The first `]` after the key belongs to the very
    # `[:200]` this asserts on, so cutting there removed the thing being measured — the guard
    # failed while the code was right.
    src = inspect.getsource(wf.JobWorkflow)
    published = next(n for n in ast.walk(ast.parse(src.lstrip()))
                     if isinstance(n, ast.Dict)
                     and "acceptance" in {getattr(k, "value", None) for k in n.keys})
    value = next(v for k, v in zip(published.keys, published.values, strict=False)
                 if getattr(k, "value", None) == "acceptance")
    block = ast.unparse(value)

    assert "[:200]" in block, f"the criterion text is published untrimmed: {block}"
    assert "evidence" not in block, "the evidence prose crosses the wire on every refresh"
    assert "[:12]" in block, "an unbounded list of criteria crosses the wire"
