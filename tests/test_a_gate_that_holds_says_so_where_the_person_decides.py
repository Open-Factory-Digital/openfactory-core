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


#: Roots `_facts_of` always trusts, independent of what any given function assigns locally — the
#: two objects `HOLDS_THE_MERGE` itself says a fact lives on.
_BASE_ROOTS = frozenset({"result", "manifest"})


def _facts_of(node: ast.AST, roots: frozenset[str] = _BASE_ROOTS) -> set[str]:
    """Every attribute name whose access chain roots at a name in `roots`. `result.review.decision`
    yields BOTH `review` and `decision`: each attribute node's own chain is walked back
    independently, and both root at `result`, so a fact is caught at whatever depth a condition
    happens to read it from — the same reason `_names` below stays a flat set rather than only the
    leaf attribute.

    `roots` DEFAULTS TO `result`/`manifest` BUT IS NOT LIMITED TO THEM — see `_holds`, which widens
    it to every name the function assigns locally. `assessment = of_attempt(manifest, result)` is
    the reason: `assessment` is built FROM `result`/`manifest` but is not itself one of those two
    names, so a condition reading `assessment.level` was invisible to this walk entirely (not one
    root, not the other) until the caller told it `assessment` counts too."""
    out: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Attribute):
            root = n
            while isinstance(root, ast.Attribute):
                root = root.value
            if isinstance(root, ast.Name) and root.id in roots:
                out.add(n.attr)
    return out


def _local_facts(fn: ast.FunctionDef, roots: frozenset[str]) -> dict[str, set[str]]:
    """The same one-hop local-assignment walk `_locals_of` does, keeping only the facts (rooted at
    `roots`) a local was built from — so `before = result.test_census_before` records `{"before":
    {"test_census_before"}}`, and a condition reading `before` is really reading
    `test_census_before`."""
    out: dict[str, set[str]] = {}
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                out.setdefault(target.id, set()).update(_facts_of(node.value, roots))
    return out


def _own_facts(test: ast.AST, local_facts: dict[str, set[str]],
                roots: frozenset[str]) -> set[str]:
    """Every fact THIS branch's OWN condition depends on — never `outer`, which stays exactly what
    it always was: the reason the ANY-test below can still credit a suppression-block's nested
    branch to `added_suppressions`. A fact this branch genuinely owes a reader is read here
    regardless of what encloses it, which is what makes the ALL-test below precise instead of
    borrowing correctness from an ancestor's condition."""
    out = set(_facts_of(test, roots))
    for n in ast.walk(test):
        if isinstance(n, ast.Name):
            out |= local_facts.get(n.id, set())
    return out


def _holds(fn: ast.FunctionDef) -> list[tuple[ast.If, set[str], set[str]]]:
    """Every branch that returns False, with (1) the identifiers its condition depends on
    INCLUDING everything enclosing `if`s contribute — the ANY-test's own input, unchanged — and
    (2) the facts its OWN condition alone depends on — the ALL-test's input.

    ENCLOSING CONDITIONS COUNT FOR (1) ONLY. `if result.review is None: return False` holds a
    merge because of the `if result.added_suppressions:` it sits inside — read alone it would look
    like a gate about reviews, and the reason a person is owed is the suppression. (2) never
    borrows from an ancestor: a fact THIS branch's own condition reads must be accounted for on
    its own terms, which is exactly the property the ANY-test using `outer` cannot guarantee.

    (2)'s ROOTS ARE WIDER THAN `result`/`manifest` (review, #26 — this file's own earlier defect,
    found live on the PR that introduced it). `assessment = of_attempt(manifest, result)` is a
    THIRD fact-carrying object, and `_facts_of` rooted at the literal names `result`/`manifest`
    alone could not see through the one hop `assessment` adds: `if assessment.needs_a_human:
    return False` computed `own_facts == set()` — not merely "vacuously fine", genuinely unable to
    see the branch's condition at all — so a second attribute added to that same condition, say
    `assessment.deploy_blocked`, would have held a merge in total silence, undetected by the very
    test this widening exists to make precise. Every name this function assigns locally
    (`_locals_of`'s own keys — `assessment`, `before`, `after`) is now a trusted root alongside
    `result`/`manifest`, so a fact reached through exactly one extra hop is caught the same way a
    fact reached directly is.
    """
    out: list[tuple[ast.If, set[str], set[str]]] = []
    resolved = _locals_of(fn)
    roots = _BASE_ROOTS | frozenset(resolved)
    local_facts = _local_facts(fn, roots)

    def walk(node: ast.AST, outer: set[str]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.If):
                names = outer | _names(child.test)
                for name in list(names):
                    names |= resolved.get(name, set())
                if any(isinstance(s, ast.Return)
                       and isinstance(s.value, ast.Constant) and s.value.value is False
                       for s in child.body):
                    out.append((child, names, _own_facts(child.test, local_facts, roots)))
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
    # 12 SINCE ADR-0046: the knowledge gate — `okf_gate: enforce` holds an amber or dark change
    # (`knowledge_stance`), declared in HOLDS_THE_MERGE with `okf_gate` as its qualifier.
    assert len(holds) == 12, (
        f"{len(holds)} branches of `should_auto_merge` hold a merge, not 12 — either a gate was "
        f"added or removed (say which, here) or this guard no longer finds the branches it reads")


def test_every_branch_that_holds_a_merge_names_a_fact_that_is_declared():
    """A NEW GATE MUST DECLARE ITSELF. Otherwise the next one is added, refuses correctly, and says
    nothing — which is how the four instances in this file's docstring each arrived.

    THIS IS THE ANY-TEST, KEPT AS IS. It only asks that SOME name in the branch's condition (own
    or inherited from an enclosing `if`) is declared — see the ALL-test right below for the
    branch's own condition specifically, which is the check review on #21 found this one alone
    could not make."""
    declared = set(mp.HOLDS_THE_MERGE) | set(mp.SAYS_NOTHING_AND_WHY)

    for branch, names, _own in _holds(_function(mp, "should_auto_merge")):
        assert names & declared, (
            f"the branch at merge_policy.py:{branch.lineno} holds a merge on "
            f"{sorted(n for n in names if not n.startswith('_'))} and none of those is declared in "
            f"HOLDS_THE_MERGE or SAYS_NOTHING_AND_WHY. A gate that is not declared is a gate the "
            f"pull request body is never checked for.")


def test_every_branch_that_holds_a_merge_declares_EVERY_fact_its_own_condition_reads():
    """THE ANY-TEST'S BLIND SPOT, NAMED BY REVIEW ON #21. A branch whose condition names two
    facts — one declared, one not — passed the check above because `names & declared` only needs
    ONE match. Demonstrated live in review: `if result.review is not None and
    result.deploy_window_closed: return False` would have been accepted as `review`, silently
    promoting an undeclared `deploy_window_closed` to a merge gate nobody is ever told about — the
    exact defect `HOLDS_THE_MERGE` exists to prevent, surviving the guard against it. Worse: the
    count assertion above's own message ("either a gate was added or removed, say which here")
    makes bumping the count from 11 to 12 the natural response to the one thing that goes red, and
    bumping the count is what makes the hole green.

    Checked on the branch's OWN condition, never `outer` — `outer` exists only so the ANY-test
    above can still credit a suppression-block's nested branch to `added_suppressions`; a fact
    genuinely owed by THIS branch is read here regardless of what encloses it, so this test cannot
    be satisfied by borrowing correctness from an ancestor's condition the way the ANY-test can."""
    declared = set(mp.HOLDS_THE_MERGE) | set(mp.SAYS_NOTHING_AND_WHY) | set(mp.PART_OF_ANOTHER_FACT)

    for branch, _names, own_facts in _holds(_function(mp, "should_auto_merge")):
        undeclared = own_facts - declared
        assert not undeclared, (
            f"the branch at merge_policy.py:{branch.lineno} reads {sorted(undeclared)} off "
            f"`result`/`manifest` and none of those is declared in HOLDS_THE_MERGE, "
            f"SAYS_NOTHING_AND_WHY or PART_OF_ANOTHER_FACT. A fact a merge-gate condition reads "
            f"and never declares is invisible to a reader of the pull request body.")


def test_the_any_test_alone_would_have_missed_hermes_own_repro():
    """THE CONCRETE PROOF, not just three real names being declared. Reproduces the exact
    hypothetical from the #21 review as a synthetic branch: `review` declared,
    `deploy_window_closed` not. The ANY-test accepts it; the ALL-test above is what actually
    catches it — this pins that difference directly, independent of anything real in
    `should_auto_merge` today."""
    tree = ast.parse(
        "def f(result, manifest):\n"
        "    if result.review is not None and result.deploy_window_closed:\n"
        "        return False\n"
    )
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
    [(_branch, names, own_facts)] = _holds(fn)

    declared = set(mp.HOLDS_THE_MERGE) | set(mp.SAYS_NOTHING_AND_WHY)
    assert names & declared, "the ANY-test should still accept this — `review` is declared"
    assert own_facts == {"review", "deploy_window_closed"}
    assert own_facts - declared, (
        "the ALL-test must reject this: `deploy_window_closed` is undeclared and the ANY-test "
        "alone would have let it hold a merge silently")


def test_the_all_test_would_have_missed_a_fact_reached_through_a_local():
    """THE ALL-TEST'S OWN BLIND SPOT, NAMED BY REVIEW ON #26 — a second-round finding on the guard
    the row above already fixed once. `assessment = of_attempt(manifest, result)` is a fact-carrying
    object built from `result`/`manifest` one hop away from them, and `_facts_of` rooted at the
    literal names `result`/`manifest` alone could not see through that hop: `if
    assessment.needs_a_human: return False` computed `own_facts == set()` — not "vacuously fine",
    genuinely blind to the branch's own condition. A second attribute read off the same local,
    `assessment.deploy_blocked`, would have held a merge in total silence, the ALL-test passing not
    because the fact was declared but because the walk never found it to ask. `_holds` now widens
    its roots to every name the function assigns locally, so a fact reached through exactly one
    extra hop is caught the same way a fact reached directly is."""
    tree = ast.parse(
        "def f(result, manifest):\n"
        "    assessment = of_attempt(manifest, result)\n"
        "    if assessment.needs_a_human or assessment.deploy_blocked:\n"
        "        return False\n"
    )
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
    [(_branch, _names, own_facts)] = _holds(fn)

    assert own_facts == {"needs_a_human", "deploy_blocked"}, (
        "a fact reached through a local built from result/manifest must be caught exactly like "
        "one read off result/manifest directly — an empty set here means the walk never even saw "
        "the branch's own condition")


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
    # ADR-0046: the stance holds only under `okf_gate: enforce`, and the body says the stance and
    # the mode side by side whatever the mode — so the reader sees why this one was held.
    "knowledge_stance":      ({"knowledge_stance": "dark",
                               "knowledge_question": "this change touches 1 file(s) nothing "
                                                     "describes (`app.py`)"},
                              {"okf_gate": "enforce"}, "knowledge gate: **dark** (`enforce`"),
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


def test_a_second_half_names_which_fact_it_belongs_to():
    """Same discipline as the exemption table above, for the same reason: a name in
    `PART_OF_ANOTHER_FACT` with no real explanation is indistinguishable from a gate somebody
    forgot to declare, wearing this table's clothes instead."""
    assert mp.PART_OF_ANOTHER_FACT, "an empty table proves the ALL-test below is never exercised"
    for fact, why in mp.PART_OF_ANOTHER_FACT.items():
        assert len(why) > 80, (
            f"the entry for `{fact}` is {len(why)} characters — that is a label, not a reason a "
            f"reviewer can disagree with")


def test_a_fact_cannot_be_both_owed_and_exempt():
    assert not (set(mp.HOLDS_THE_MERGE) & set(mp.SAYS_NOTHING_AND_WHY))
    assert not (set(mp.HOLDS_THE_MERGE) & set(mp.PART_OF_ANOTHER_FACT)), (
        "a name cannot be its own second half")
    assert not (set(mp.SAYS_NOTHING_AND_WHY) & set(mp.PART_OF_ANOTHER_FACT)), (
        "a name cannot be both an exemption and a qualifier of something else")


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
