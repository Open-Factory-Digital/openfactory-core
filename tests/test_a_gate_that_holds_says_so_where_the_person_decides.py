"""A gate that refuses without naming what it refused is a gate nobody can argue with.

THAT SENTENCE IS `policy/protected.py`'S OWN, AND THE MODULE THEN SHIPPED SUCH A GATE. So did the
census, and so did the profile. In one review round the same defect arrived four times:

  * `protected.reason()` was written, tested, and imported by nothing;
  * `census.reason()` was written, tested, and imported by nothing;
  * a manifest naming a class the caller never resolved returned `False` here with no log and no
    message, landing in the same branch as an ordinary ready-for-review pull request;
  * a suppression that survived the repair loop has gated since ADR-0011 and never said so.

In every case `should_auto_merge` returned False, `machine.py` took the `request_reviewers` branch,
and a human opened a pull request that looked exactly like one that was simply ready to read. Four
instances is not four accidents; it is the shape of this function — a `bool` return that throws away
its own reason at the moment it is computed.

THE FIX IS NOT A CHECKLIST ITEM, because prose is the weak form of a rule and this platform's whole
thesis is that the weak form does not hold. It is a declaration in `merge_policy.py` that this file
reads: `HOLDS_THE_MERGE` maps each fact that can hold a merge to the name `_pr_body` must read in
order to say it, and `SAYS_NOTHING_AND_WHY` carries the one exemption with its reason. Adding a gate
costs one line in each place, and forgetting either is RED rather than silent.

WHAT THIS CANNOT DO, said so it is not mistaken for more: it checks that the fact reaches the body,
not that the SENTENCE is a good one. A gate whose note is wrong or unreadable passes here. The
`ast` idiom is this repository's own, from `test_the_language_reaches_every_unprompted_surface.py`.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from openfactory.contracts import (
    Component,
    Manifest,
    RunResult,
    Ticket,
    ValidationResult,
)
from openfactory.contracts.review import ReviewResult
from openfactory.orchestrator import machine as machine_mod
from openfactory.orchestrator import merge_policy as mp

_FAILED = ValidationResult(name="test", command="pytest -q", exit_code=1, passed=False)
_PASS = [ValidationResult(name="test", command="pytest -q", exit_code=0, passed=True)]
_REJECTED = ReviewResult(decision="rejected", score=10, summary="no")
_TICKET = Ticket(id="#1", title="t", objective="o", repo="acme/app")


def _body(result_kw: dict | None = None, manifest_kw: dict | None = None,
          resolved: object | None = None) -> str:
    """The REAL `_pr_body`, on an attempt carrying one gate's evidence."""
    base = dict(ticket_id="#1", state="pr_open", validations=_PASS)
    base.update(result_kw or {})
    holder = type("_H", (), {
        "manifest": Manifest(**(manifest_kw or {})),
        "_stripped_workflows": set(),
        "_profile": resolved,
    })()
    return machine_mod.JobRunner._pr_body(holder, _TICKET, RunResult(**base))


def _function(module, name: str) -> ast.FunctionDef:
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} is gone from {module.__name__} — this guard measures nothing now")


def _names(node: ast.AST) -> set[str]:
    """Every identifier mentioned — attributes, plain names, and the functions called."""
    out: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Attribute):
            out.add(n.attr)
        elif isinstance(n, ast.Name):
            out.add(n.id)
    return out


def _locals_of(fn: ast.FunctionDef) -> dict[str, set[str]]:
    """What each local name was assigned from — ONE HOP, which is all this function needs.

    `before = result.test_census_before` and `assessment = of_attempt(manifest, result)` are the two
    shapes that matter: a condition that reads a local is really reading whatever fed it, and a
    guard that stopped at the local name would let any gate hide behind a variable.
    """
    out: dict[str, set[str]] = {}
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                out.setdefault(target.id, set()).update(_names(node.value))
    return out


def _holds(fn: ast.FunctionDef) -> list[tuple[ast.If, set[str]]]:
    """Every branch that returns False, with the identifiers its condition depends on.

    ENCLOSING CONDITIONS COUNT. `if result.review is None: return False` holds a merge because of
    the `if result.added_suppressions:` it sits inside — read alone it would look like a gate about
    reviews, and the reason a person is owed is the suppression.
    """
    out: list[tuple[ast.If, set[str]]] = []
    resolved = _locals_of(fn)

    def walk(node: ast.AST, outer: set[str]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.If):
                names = outer | _names(child.test)
                for name in list(names):
                    names |= resolved.get(name, set())
                if any(isinstance(s, ast.Return)
                       and isinstance(s.value, ast.Constant) and s.value.value is False
                       for s in child.body):
                    out.append((child, names))
                walk(child, names)
            else:
                walk(child, outer)

    walk(fn, set())
    return out


def test_the_declaration_still_describes_a_function_that_exists():
    """The guard's own reachability. A declaration about a function nobody calls measures nothing,
    and every finding this file exists for was exactly that shape."""
    holds = _holds(_function(mp, "should_auto_merge"))

    # EXACT, NOT A FLOOR. A floor is satisfied by a walker that stopped descending into nested
    # `if`s and lost the entire suppression block — measured: with `>= 8` that cut scored GREEN.
    assert len(holds) == 11, (
        f"{len(holds)} branches of `should_auto_merge` hold a merge, not 11 — either a gate was "
        f"added or removed (say which, here) or this guard no longer finds the branches it reads")


def test_every_branch_that_holds_a_merge_names_a_fact_that_is_declared():
    """A NEW GATE MUST DECLARE ITSELF. Otherwise the next one is added, refuses correctly, and says
    nothing — which is how the four instances in this file's docstring each arrived."""
    declared = set(mp.HOLDS_THE_MERGE) | set(mp.SAYS_NOTHING_AND_WHY)

    for branch, names in _holds(_function(mp, "should_auto_merge")):
        assert names & declared, (
            f"the branch at merge_policy.py:{branch.lineno} holds a merge on "
            f"{sorted(n for n in names if not n.startswith('_'))} and none of those is declared in "
            f"HOLDS_THE_MERGE or SAYS_NOTHING_AND_WHY. A gate that is not declared is a gate the "
            f"pull request body is never checked for.")


# ── the behavioural half, and the reason it is behavioural ──────────────────────────────────────
#
# THE FIRST VERSION OF THIS FILE ASKED WHETHER `_pr_body` READ THE FIELD, and its own mutation plan
# killed it: disabling `if census_note: lines += [...]` leaves `result.test_census_before` being
# read INSIDE the call that computes the note, so the name was still there, the sentence was never
# printed, and the guard was green. That is this PR's own defect, committed by the guard against it.
#
# So each fact is TRIPPED on a real `_pr_body` and the body has to change. `rendered_by` in
# `HOLDS_THE_MERGE` is kept as the cheap half — it catches a note that was never computed at all —
# but it is not what holds the line.

#: A DECLARED COMPONENT, because `risk.note` returns "risk: not expressed" for a manifest that
#: declares none — and `_pr_body` suppresses that line, correctly: a project with no components has
#: not failed to declare anything.
_DECLARING = {"components": {"app": Component(path="src/**", stack="python")}}

_TRIPS: dict[str, tuple[dict, dict, str]] = {
    #  fact                  (RunResult kwargs, Manifest kwargs, what the reader must see)
    "all_passed":            ({"validations": [_FAILED]}, {}, "❌"),
    "review":                ({"review": _REJECTED}, {}, "rejected"),
    "added_suppressions":    ({"added_suppressions": ["noqa"]}, {}, "noqa"),
    "needs_a_human":         ({"undeclared_paths": ["infra/main.tf"], "undeclared_count": 1},
                              _DECLARING, "infra/main.tf"),
    "protected_hits":        ({"protected_hits": [".openfactory/project.yaml"],
                               "protected_count": 1}, {}, "move the ruler"),
    "floor_unreadable":      ({"floor_unreadable": True}, {}, "OUR install"),
    "test_census_before":    ({"test_census_before": 120, "test_census_after": 119}, {}, "119"),
    # the WIRING half of the class gate; the strengthening half has its own test below, because it
    # needs a risk level and this table is deliberately one line per fact.
    "profile":               ({}, {"profile": "regulated"}, "never resolved it"),
}


def test_every_declared_fact_has_a_case_that_trips_it():
    """A fact with no case is a fact this file only pretends to check."""
    assert set(_TRIPS) == set(mp.HOLDS_THE_MERGE), (
        f"declared but never tripped: {sorted(set(mp.HOLDS_THE_MERGE) - set(_TRIPS))}; "
        f"tripped but not declared: {sorted(set(_TRIPS) - set(mp.HOLDS_THE_MERGE))}")


@pytest.mark.parametrize("fact", sorted(_TRIPS))
def test_every_declared_fact_changes_what_the_person_reads(fact):
    """THE HALF THAT WAS ACTUALLY BROKEN. `protected.reason` and `census.reason` were written and
    tested and called by nothing at all; the profile and the suppressions never had a sentence."""
    result_kw, manifest_kw, expected = _TRIPS[fact]

    body = _body(result_kw, manifest_kw)

    assert expected in body, (
        f"`{fact}` can hold a merge in should_auto_merge and the pull request body does not say so "
        f"— the person deciding opens a pull request that looks exactly like one that was simply "
        f"ready for review. Expected {expected!r} somewhere in:\n{body}")
    assert body != _body(), "the body is identical to a clean attempt's"


@pytest.mark.parametrize("fact,rendered_by", sorted(mp.HOLDS_THE_MERGE.items()))
def test_every_declared_fact_is_at_least_computed(fact, rendered_by):
    """The cheap half, kept because it names the missing thing precisely when a note was never
    written at all — the behavioural test above only says the sentence is absent."""
    assert rendered_by in _names(_function(machine_mod, "_pr_body")), (
        f"`_pr_body` never reads `{rendered_by}`, so nothing there can say `{fact}`")


def test_an_exemption_is_a_decision_somebody_wrote_down():
    """An exemption with no reason is indistinguishable from a gate somebody forgot, which is the
    whole failure mode this file guards. Short strings are how that erodes."""
    assert mp.SAYS_NOTHING_AND_WHY, "an empty exemption table hides nothing and is a trap"
    for fact, why in mp.SAYS_NOTHING_AND_WHY.items():
        assert len(why) > 80, (
            f"the exemption for `{fact}` is {len(why)} characters — that is a label, not a reason a "
            f"reviewer can disagree with")


def test_a_fact_cannot_be_both_owed_and_exempt():
    assert not (set(mp.HOLDS_THE_MERGE) & set(mp.SAYS_NOTHING_AND_WHY))


def test_the_class_that_strengthened_the_gate_is_named_where_the_person_decides():
    """The other half of `profile`, and the one a client feels. A `regulated` project whose class
    sent a high-risk change to a person saw a manifest that says `auto`, a risk note that says
    `high`, and nothing connecting the two — a platform that appears to have ignored the
    configuration the client themselves wrote."""
    from openfactory.contracts.state import RiskLevel
    from openfactory.policy.profiles import resolve_profile

    body = _body(
        {"touched_components": ["infra"]},
        {"profile": "regulated", "merge_policy": "auto",
         "components": {"infra": Component(path="infra/**", stack="terraform",
                                           risk=RiskLevel.HIGH)}},
        resolve_profile("regulated"))

    assert "regulated" in body
    assert "`merge_policy` says `auto`" in body
