"""The runner, the workflow and the activities never name a provider (ADR-0049 D8).

THE SIBLING AND WHY THIS IS A SECOND FILE. `test_sandbox_registry.py::
test_the_workflow_body_names_no_provider` greps ONE file for ONE literal (`"fargate"`), and
`test_the_board_says_where_it_lives.py` covers vendor URLs across the whole package. Neither
asks the question this one asks: does the LIFECYCLE — the runner, the workflow body and the
activities — decide anything by the name of the provider it happens to be talking to?

It did, in one place, and the place is the reason this guard exists rather than a paragraph in
an ADR. `activities._mention_for` read `project.tracker.kind` and compared it to `"github"` to
decide whether a mention should carry an `@`. Every other row on that axis — Jira, Azure Boards,
a client's own, a stranger's add-on, the platform's own local board — was rendered as *not
GitHub* by a module that had no way to ask any of them. The fix is a port method (ADR-0049 D7);
this is what stops the next one, because the next one will look just as small.

WHAT IS DELIBERATELY NOT FORBIDDEN, because a ratchet that fires on honest code teaches people
to widen its exemptions:

  · **`.kind == …` in general.** The activities compare eight DOMAIN kinds — an open question, a
    ledger loop's kind, a stall's kind, a notification level. Those are the platform's own
    vocabulary and they are exactly what this layer is supposed to reason about. Only a chain
    that reaches a PROVIDER's kind is refused.
  · **Passing a provider kind on.** `forge_kind=(project.forge.kind …)` reaches four activity
    inputs, and carrying a value to somebody who records it is not deciding by it.
  · **`.github/workflows`.** A path in the client's repository, which the strip is about
    (`machine.py`); it is not a kind and it is not a host.
  · **A vendor URL.** Covered, with its `# vendor-url-ok:` marker rule, by
    `test_the_board_says_where_it_lives.py`. Two guards owning one rule is how one of them rots.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

#: The three files the lifecycle lives in. Named one by one rather than globbed: a glob would
#: quietly widen or narrow with the tree, and the claim is about these three.
LIFECYCLE = (
    "openfactory/orchestrator/machine.py",
    "openfactory/runtime/temporal/workflow.py",
    "openfactory/runtime/temporal/activities.py",
)

#: The attribute whose value is a provider's name. A chain ending `.kind` is only a provider's
#: when the thing it hangs off is one of the axes.
PROVIDER_HOLDERS = ("tracker", "forge", "ci", "environment", "board", "channel", "notifier")

#: A call whose RESULT is a provider kind, wherever it is spelled.
PROVIDER_CALLS = ("forge_kind", "tracker_kind", "board_kind", "provider_kind")

#: The vocabulary itself. A string equal to one of these is a provider's name, whatever it is
#: being compared with or assigned to — the shape the defect took, and the shape a reviewer
#: recognises. Prose never matches, because the match is on the WHOLE string.
PROVIDER_WORDS = frozenset({
    "github", "jira", "azure_devops", "local",
    "github_actions", "azure_pipelines", "azure",
    "github.com", "dev.azure.com", "atlassian.net",
})


def _source(rel: str) -> tuple[str, ast.Module]:
    text = (ROOT / rel).read_text(encoding="utf-8")
    return text, ast.parse(text)


def _chain(node: ast.AST) -> list[str]:
    """The dotted names of an attribute chain, outermost last — `a.b.kind` → ['a','b','kind']."""
    out: list[str] = []
    while isinstance(node, ast.Attribute):
        out.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        out.append(node.id)
    return list(reversed(out))


def _is_provider_kind(node: ast.AST) -> bool:
    """Whether this expression's VALUE is a provider's name."""
    if isinstance(node, ast.Attribute):
        chain = _chain(node)
        return (len(chain) >= 2 and chain[-1] == "kind"
                and chain[-2].lower() in PROVIDER_HOLDERS)
    if isinstance(node, ast.Call):
        called = node.func
        name = called.attr if isinstance(called, ast.Attribute) else getattr(called, "id", "")
        return name in PROVIDER_CALLS
    return False


def _docstrings(tree: ast.Module) -> set[int]:
    """Line numbers of every docstring node, so prose explaining a rule never breaks it."""
    out: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        body = getattr(node, "body", None) or []
        first = body[0] if body else None
        if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            for line in range(first.lineno, (first.end_lineno or first.lineno) + 1):
                out.add(line)
    return out


def provider_kind_decisions(tree: ast.Module) -> list[int]:
    """Line numbers of every comparison that reads a provider's kind — THE RULE ITSELF.

    A FUNCTION, AND THIS IS THE WHOLE REASON IT IS ONE. The first version of this file walked the
    tree inline in the real test and again in its planted twin, so the twin proved its own copy of
    the rule rather than the rule — and a mutation that made the real walk read only the left-hand
    side survived, because the twin's copy still read both. A guard's self-test must call the
    guard.

    BOTH SIDES, not just the left. `kind == "github"` and `"github" == kind` are the same decision,
    and a rule that reads one of them teaches the next author which way round to write it."""
    return sorted(node.lineno for node in ast.walk(tree)
                  if isinstance(node, ast.Compare)
                  and any(_is_provider_kind(s) for s in (node.left, *node.comparators)))


def provider_words(tree: ast.Module) -> list[tuple[int, str]]:
    """Every string constant that IS a provider's name, outside prose — THE RULE ITSELF.

    Shared with the planted twin for the reason above: the prose exemption is the part most likely
    to be widened by accident, so the test that pins it has to be pinning the real one."""
    prose = _docstrings(tree)
    return sorted(
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and node.lineno not in prose
        and node.value.strip().lower() in PROVIDER_WORDS)


def test_the_property_is_about_exactly_these_three_files() -> None:
    """The scope is an assertion, not a variable somebody may quietly shorten.

    A parametrized guard that loses a file does not FAIL — it runs fewer cases and stays green,
    which is how a property silently stops covering the module it was written for (measured: this
    exact cut survived the first run of the plan)."""
    assert LIFECYCLE == (
        "openfactory/orchestrator/machine.py",
        "openfactory/runtime/temporal/workflow.py",
        "openfactory/runtime/temporal/activities.py",
    ), "the lifecycle is these three files; adding or dropping one is a decision, not an edit"
    for rel in LIFECYCLE:
        assert (ROOT / rel).is_file(), f"{rel} is named by the property and is not there"


@pytest.mark.parametrize("rel", LIFECYCLE)
def test_the_lifecycle_takes_no_decision_by_a_providers_kind(rel: str) -> None:
    """No comparison in these three files reads a provider's kind on either side."""
    _, tree = _source(rel)
    offenders = [f"{rel}:{n}" for n in provider_kind_decisions(tree)]

    assert not offenders, (
        "the lifecycle decides by the name of the provider it is talking to — every row on that "
        "axis that is not the one named is decided against by a module with no way to ask it. "
        "Put the question on the port and let the row answer (ADR-0049 D7, "
        "`TrackerAdapter.identity_of` / `.mention` are the two that came from this):\n  "
        + "\n  ".join(offenders))


@pytest.mark.parametrize("rel", LIFECYCLE)
def test_the_lifecycle_spells_no_providers_name(rel: str) -> None:
    """No string in these three files IS a provider's name.

    The whole string, never a substring: `.github/workflows` is a path in the client's repo and
    stays (ADR-0049 D3), and a sentence explaining a vendor's behaviour is documentation. What is
    refused is the vocabulary itself — the shape `kind == "github"` needs to exist at all."""
    _, tree = _source(rel)
    offenders = [f"{rel}:{n}: {word!r}" for n, word in provider_words(tree)]

    assert not offenders, (
        "the lifecycle spells a provider's own name — the value belongs in an adapter, a registry "
        "row or a port's answer, never in the layer that is supposed to work the same for every "
        "row (ADR-0049 D8):\n  " + "\n  ".join(offenders))


def test_the_guard_can_see_both_offences() -> None:
    """The guard is only worth its runtime if it FAILS on the shape it forbids.

    Planted rather than asserted about: the two rules are run over a synthetic module that holds
    exactly the two offences and nothing else, so a rule that silently stopped walking would be
    caught here rather than three refactors later."""
    planted = ast.parse(
        'def f(project):\n'
        '    """A docstring naming github, which is prose and must not count."""\n'
        '    if project.tracker.kind == "local":\n'
        '        return 1\n'
        '    if "github" == forge_kind(project):\n'
        '        return 2\n'
        '    return 0\n')

    caught = provider_kind_decisions(planted)
    assert len(caught) == 2, (
        f"the comparison rule saw {caught} — it must catch the chain on the LEFT (line 3) and the "
        f"call on the RIGHT (line 5); missing one means the rule reads a single side")

    words = [word for _, word in provider_words(planted)]
    assert sorted(words) == ["github", "local"], (
        f"the literal rule saw {words!r} — it must catch both planted names and neither the "
        f"docstring's mention nor anything else")


def test_the_prose_exemption_does_not_excuse_code() -> None:
    """A docstring may name a vendor; the line under it may not.

    THIS IS THE EXEMPTION'S OWN TEST, because "skip docstrings" is exactly the kind of widening
    that turns into "skip strings" one edit later."""
    planted = ast.parse('def f():\n    """github"""\n    x = "github"\n    return x\n')
    hits = [line for line, _ in provider_words(planted)]
    assert hits == [3], (
        f"the assignment on line 3 must be the one offender, got {hits} — [2, 3] means the prose "
        f"exemption stopped working, [] means it widened to every string")
