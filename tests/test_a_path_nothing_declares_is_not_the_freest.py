"""Risk is a verdict with a reason, and a path nothing declares is not the safest one to change.

THE HOLE THESE CLOSE. `RiskLevel` is declared per component and documented as *"drives how strong
the human gate is"*. Exactly one place read it — `merge_policy` asked whether any TOUCHED component
was `HIGH` — and `resolve_touched_components` returns only the components whose glob MATCHED. So a
change whose every path matched no component walked an empty list, found no `HIGH`, and merged
without a person; and the pull request body printed its "Touched components" line only when the
list was non-empty, so that change said nothing at all about components. Silence, which a reader
takes for "none were involved" rather than "these paths are declared by nobody".

It is the inversion this codebase names elsewhere as the sharpest idea it has — *a file nothing
describes is the least safe to change, not the freest* — inside the gate that decides whether a
human ever sees the merge.

THE DISTINCTION THAT KEEPS THE FIX FROM BEING WORSE THAN THE DEFECT. `components` defaults to `{}`
and a manifest without any is ordinary. A project that does not use components has not failed to
declare anything, and gating it would send every simple project on `merge_policy: auto` to a human
for ever. Only a manifest that DOES declare components and was then changed outside all of them is
the silence worth catching, and that separation has its own guard in both directions.

WHAT IS DELIBERATELY NOT FIXED, guarded so it stays honest: `RiskLevel.LOW` is read by nothing.
`low` and `normal` behave identically. Making `low` mean something is LOOSENING, and loosening
needs the recorded, named decision this platform has no mechanism for yet.
"""

from __future__ import annotations

import pytest

from openfactory.contracts.manifest import Manifest
from openfactory.contracts.run import RunResult
from openfactory.contracts.state import JobState, RiskLevel
from openfactory.orchestrator.merge_policy import should_auto_merge
from openfactory.orchestrator.risk import (
    MAX_UNDECLARED_SHOWN,
    RiskAssessment,
    assess,
    of_attempt,
)


def _manifest(**components) -> Manifest:
    return Manifest.model_validate({"merge_policy": "auto", "components": {
        name: {"path": path, "stack": "python", "risk": risk}
        for name, (path, risk) in components.items()}})


def _bare() -> Manifest:
    return Manifest.model_validate({"merge_policy": "auto"})


def _result(assessment: RiskAssessment, **kw) -> RunResult:
    """A finished attempt carrying what the attempt recorded — the shape the gate actually reads."""
    kw.setdefault("state", JobState.VALIDATING)
    return RunResult(ticket_id="1",
                     touched_components=list(assessment.touched),
                     undeclared_paths=list(assessment.undeclared_paths),
                     undeclared_count=assessment.undeclared_count, **kw)


# ── the defect ───────────────────────────────────────────────────────────────────────────────────

def test_a_change_outside_every_declared_component_needs_a_human() -> None:
    """THE HOLE. Two declared components, and a diff that touches neither — so the old loop walked
    an empty list, found no high-risk component, and permitted the merge."""
    manifest = _manifest(api=("services/api/**", "normal"), infra=("infra/**", "high"))

    a = assess(["scripts/deploy.sh", "Makefile"], manifest)

    assert a.level is None, "nothing declared covers this change"
    assert a.needs_a_human
    assert a.undeclared_count == 2


def test_a_change_INSIDE_a_declared_component_still_merges() -> None:
    """The positive twin, and it is what stops the fix from being a blanket refusal."""
    manifest = _manifest(api=("services/api/**", "normal"))

    a = assess(["services/api/app.py"], manifest)

    assert a.level == RiskLevel.NORMAL
    assert not a.needs_a_human


def test_one_undeclared_path_beside_declared_ones_is_enough() -> None:
    """The dangerous shape in the field: a change that mostly lands where it should, plus one file
    in a corner nobody described. Averaging it away is how the corner never gets looked at."""
    manifest = _manifest(api=("services/api/**", "normal"))

    a = assess(["services/api/app.py", "scripts/deploy.sh"], manifest)

    assert a.level == RiskLevel.NORMAL, "what it DID touch is still reported"
    assert a.needs_a_human
    assert a.undeclared_paths == ("scripts/deploy.sh",)


def test_high_risk_still_gates_exactly_as_it_did() -> None:
    """The behaviour that must not regress while the new one is added."""
    manifest = _manifest(api=("services/api/**", "normal"), infra=("infra/**", "high"))

    a = assess(["services/api/app.py", "infra/main.tf"], manifest)

    assert a.level == RiskLevel.HIGH
    assert a.driven_by == ("infra",)
    assert a.needs_a_human


# ── the distinction that keeps simple projects working ───────────────────────────────────────────

def test_a_manifest_that_declares_no_components_is_not_gated() -> None:
    """`components` defaults to `{}` and most projects never need it. A project that does not use
    the concept has not failed to declare anything, and gating it would send every simple project
    on `merge_policy: auto` to a human for ever — the fix doing more damage than the defect."""
    a = assess(["anything.py", "everything.py"], _bare())

    assert a.declares_nothing
    assert not a.needs_a_human
    assert not a.undeclared, "declaring nothing is not the same as failing to declare"


def test_declaring_nothing_and_missing_something_read_differently() -> None:
    """Two different facts about two different projects. A reader who cannot tell them apart draws
    the same conclusion from both, and one of them is a problem."""
    nothing = assess(["x.py"], _bare())
    missed = assess(["x.py"], _manifest(api=("services/api/**", "normal")))

    assert "declares no components" in nothing.note
    assert "UNDECLARED" in missed.note
    assert nothing.note != missed.note


# ── the verdict travels with its reason ──────────────────────────────────────────────────────────

def test_the_assessment_names_what_drove_it() -> None:
    """A verdict with no reason is a verdict nobody can argue with, and every other gate in this
    platform names what refused."""
    manifest = _manifest(a=("a/**", "high"), b=("b/**", "high"), c=("c/**", "normal"))

    a = assess(["a/x.py", "b/y.py", "c/z.py"], manifest)

    assert a.level == RiskLevel.HIGH
    assert a.driven_by == ("a", "b"), "both, sorted — not whichever the dict happened to yield"
    assert a.touched == ("a", "b", "c")


def test_the_note_is_never_empty() -> None:
    """A reader of a merged pull request has to see what the gate saw. An assessment that says
    nothing when it found nothing is indistinguishable from one that never ran."""
    for a in (assess([], _bare()), assess([], _manifest(api=("api/**", "normal"))),
              assess(["api/x.py"], _manifest(api=("api/**", "normal"))),
              assess(["nowhere.py"], _manifest(api=("api/**", "normal")))):
        assert a.note.strip()


def test_the_undeclared_list_is_capped_and_the_count_is_not() -> None:
    """The note travels into a pull request body. A change that moved four hundred files must not
    print four hundred lines — and the cap must never read as the total."""
    manifest = _manifest(api=("services/api/**", "normal"))

    a = assess([f"loose/f{i}.py" for i in range(40)], manifest)

    assert len(a.undeclared_paths) == MAX_UNDECLARED_SHOWN
    assert a.undeclared_count == 40
    assert "40 path(s)" in a.note and "more" in a.note


# ── one builder, so the two entries cannot drift ─────────────────────────────────────────────────

def test_the_gate_and_the_diff_reach_the_same_verdict() -> None:
    """`assess` reads a diff at the moment the change is resolved; `of_attempt` reads what the
    attempt recorded, at the merge gate. Two builders would be two answers to "is this high risk",
    drifting the day one of them learned something — so there is one, and this proves it."""
    manifest = _manifest(api=("services/api/**", "normal"), infra=("infra/**", "high"))

    for paths in (["services/api/app.py"], ["infra/main.tf"], ["loose.py"],
                  ["services/api/app.py", "loose.py"], []):
        from_diff = assess(paths, manifest)
        assert of_attempt(manifest, _result(from_diff)) == from_diff, paths


def test_an_attempt_that_recorded_nothing_is_not_upgraded_to_unknown() -> None:
    """A `RunResult` from before the field existed carries `undeclared_count` 0, which reads as
    "nothing was outside" — and that IS what the platform used to believe. Inventing a gate for it
    would refuse merges on evidence that does not exist."""
    manifest = _manifest(api=("services/api/**", "normal"))
    old = RunResult(ticket_id="1", state=JobState.VALIDATING, touched_components=["api"])

    assert not of_attempt(manifest, old).needs_a_human


# ── the gate itself ──────────────────────────────────────────────────────────────────────────────

def _passing(assessment: RiskAssessment) -> RunResult:
    from openfactory.contracts.run import ValidationResult

    return _result(assessment, validations=[ValidationResult(
        name="test", command="pytest", exit_code=0, passed=True)])


def test_the_merge_gate_refuses_a_change_it_cannot_place(monkeypatch) -> None:
    """End to end through the real policy: every other condition satisfied, and the only thing
    standing between this diff and an unattended merge is that nothing describes where it landed."""
    manifest = _manifest(api=("services/api/**", "normal"))

    inside = _passing(assess(["services/api/app.py"], manifest))
    outside = _passing(assess(["scripts/deploy.sh"], manifest))

    assert should_auto_merge(manifest, inside) is True
    assert should_auto_merge(manifest, outside) is False


def test_the_merge_gate_leaves_a_component_less_project_alone() -> None:
    """The regression that would hurt most people: a simple project on `auto` with no components
    declared must merge exactly as it did before this existed."""
    bare = _bare()

    assert should_auto_merge(bare, _passing(assess(["anything.py"], bare))) is True


# ── what is deliberately NOT fixed ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("declared", ["low", "normal"])
def test_low_and_normal_are_the_same_behaviour_and_that_is_recorded(declared: str) -> None:
    """`RiskLevel.LOW` is read by nothing, so a client who writes `risk: low` gets what `normal`
    gets. This guard exists so the day someone makes `low` mean something it is a DECISION with a
    failing test in front of it, rather than a quiet change to what a client's manifest means.

    Making `low` loosen anything needs the recorded, named decision — a waiver or a profile — that
    this platform has no mechanism for yet."""
    manifest = _manifest(area=("area/**", declared))

    a = assess(["area/x.py"], manifest)

    assert not a.needs_a_human
    assert should_auto_merge(manifest, _passing(a)) is True


# ── the wiring, which is where the whole fix actually lives ──────────────────────────────────────
#
# Everything above tests the assessment and the gate on hand-built results. Neither notices if the
# ATTEMPT never records what it could not place, or if the pull request never says what the gate
# saw — and both of those mutations survived their first run for exactly that reason.

def test_the_attempt_records_the_paths_it_could_not_place() -> None:
    """The gate reads a `RunResult`. If the attempt does not put the undeclared paths on it, every
    guard above still passes and the gate goes on seeing what it always saw."""
    from openfactory.orchestrator.machine import JobRunner

    manifest = _manifest(api=("services/api/**", "normal"))
    holder = type("_H", (), {"_risk": assess(["services/api/a.py", "loose.py"], manifest)})()
    result = RunResult(ticket_id="1", state=JobState.VALIDATING)

    JobRunner._record_risk(holder, result)

    assert result.undeclared_paths == ["loose.py"]
    assert result.undeclared_count == 1


def test_an_attempt_with_no_assessment_records_nothing_rather_than_raising() -> None:
    """`_risk` is set in `_validate`, and not every path through the machine validates. A recorder
    that raised on a result built before that point would turn a finished attempt into a crash."""
    from openfactory.orchestrator.machine import JobRunner

    result = RunResult(ticket_id="1", state=JobState.VALIDATING)
    JobRunner._record_risk(type("_H", (), {})(), result)

    assert result.undeclared_paths == []
    assert result.undeclared_count == 0


def test_the_pull_request_says_what_the_gate_saw() -> None:
    """The verdict belongs on the pull request the verdict was about. Without it a reviewer opening
    an auto-merged change cannot tell whether it went anywhere the manifest describes."""
    from openfactory.contracts import Ticket
    from openfactory.orchestrator.machine import JobRunner

    manifest = _manifest(api=("services/api/**", "normal"), infra=("infra/**", "high"))
    holder = type("_H", (), {"manifest": manifest})()
    ticket = Ticket(id="1", title="t", objective="o", repo="acme/api")

    body = JobRunner._pr_body(holder, ticket,
                               _result(assess(["infra/main.tf", "loose.py"], manifest)))

    assert "risk: high" in body
    assert "infra" in body
    assert "loose.py" in body


def test_a_component_less_project_gets_no_risk_line_at_all() -> None:
    """A project that does not use components would otherwise carry "risk: not expressed" on every
    pull request it ever opens — a line that says nothing, on every page, for ever."""
    from openfactory.contracts import Ticket
    from openfactory.orchestrator.machine import JobRunner

    holder = type("_H", (), {"manifest": _bare()})()
    body = JobRunner._pr_body(holder, Ticket(id="1", title="t", objective="o", repo="acme/api"),
                               _result(assess(["anything.py"], _bare())))

    assert "risk:" not in body
