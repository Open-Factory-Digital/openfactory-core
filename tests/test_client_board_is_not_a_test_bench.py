"""A client's board carries the client's product — ADR-0027.

WHAT HAPPENED. Eleven tickets whose only purpose was to watch the pipeline move — "Add GET
/heartbeat endpoint (live autonomy demo)", "(panel e2e test)", "Add GET /autonomy endpoint
(autonomy proof)" — went through planning, execution, review and merge, and left eleven
constant-returning endpoints in a client's accounting product. `/healthz/ready` answers
`{"ready": true}` in production without touching a dependency.

Nobody decided that. There was no field to consult and no gate to fail, so the question of whose
product was receiving the code was never asked once.

The tests below are ordered by what is easiest to get wrong: the DEFAULT (a project that never
opted in must refuse), the DECLARATION (a label, never a title heuristic), the REACH (production
must actually pass the project, or the gate is decoration), and the VOICE (a refusal nobody can
read is the silent failure this replaces).
"""

from __future__ import annotations

import pytest

from openfactory.contracts.project import Project, ProviderRef
from openfactory.policy.test_work import TEST_WORK_LABEL, admissible, is_test_work, refusal_for


def _project(**kw):
    return Project(name="books", repo_path="/t",
                   tracker=ProviderRef(kind="github", repo="a/b"), **kw)


# ── the default ────────────────────────────────────────────────────────────────────────────────
def test_a_project_that_never_opted_in_REFUSES():
    """The default is the whole point. `books` never declared anything, and that is exactly the
    project the eleven endpoints shipped into."""
    assert _project().accepts_test_work is False
    assert refusal_for(_project(), "207", [TEST_WORK_LABEL])
    assert admissible(_project(), "207", [TEST_WORK_LABEL]) is False


def test_a_bench_project_accepts_it():
    bench = _project(accepts_test_work=True)
    assert refusal_for(bench, "207", [TEST_WORK_LABEL]) == ""
    assert admissible(bench, "207", [TEST_WORK_LABEL]) is True


def test_real_product_work_is_never_touched():
    """The gate must be invisible to everything that is not labelled. Blocking real work would be
    a worse failure than the one being fixed."""
    for labels in ([], None, ["bug"], ["security", "priority:high"]):
        assert admissible(_project(), "288", labels) is True, labels


# ── declared, not inferred ─────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("label", [TEST_WORK_LABEL, "Factory-Test", "  factory-test  "])
def test_the_label_is_matched_as_a_human_would_type_it(label):
    assert is_test_work([label]), label


def test_a_TITLE_that_looks_like_a_demo_is_NOT_test_work():
    """Deliberate: recognition is by declaration, never by guessing. `Project` carries the same
    reasoning in its own comments — what somebody declares beats what the machine infers. A title
    heuristic would miss a smoke ticket named like product work AND one day block a real ticket
    for containing the word "demo"."""
    assert is_test_work([]) is False
    assert admissible(_project(), "1", ["demo"]) is True
    assert admissible(_project(), "2", ["e2e"]) is True


# ── reach ──────────────────────────────────────────────────────────────────────────────────────
def test_the_factory_hands_the_project_to_the_runner():
    """A gate the production assembler never feeds is decoration — thirteen capabilities in this
    repository have shipped that way."""
    import ast
    from pathlib import Path

    tree = ast.parse(Path("openfactory/factory.py").read_text())
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "JobRunner"
             and any(k.arg == "project" for k in n.keywords)]
    assert calls, "build_runner assembles a JobRunner without a project — the gate never fires"


def test_the_runner_consults_the_gate_before_doing_ANY_work():
    """Refused where it is cheap: before the box, before an agent pass, before a merge. A check
    that only fires after the merge is not a guard, it is a report about damage already done."""
    import ast
    from pathlib import Path

    src = Path("openfactory/orchestrator/machine.py").read_text()
    tree = ast.parse(src)
    run = next(n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "run")
    calls = {getattr(n.func, "attr", None) or getattr(n.func, "id", None): n.lineno
             for n in ast.walk(run) if isinstance(n, ast.Call)}
    assert "refusal_for" in calls, "JobRunner.run() never asks"
    assert calls["refusal_for"] < calls.get("set_assignees", 10**9), \
        "the gate runs after the job already started claiming the ticket"


# ── voice ──────────────────────────────────────────────────────────────────────────────────────
def test_the_refusal_says_what_to_do_about_it():
    """A job that vanishes with no reason is the silent failure this codebase keeps paying for."""
    why = refusal_for(_project(), "207", [TEST_WORK_LABEL])

    assert "accepts_test_work" in why, "no way to act on it"
    assert "books" in why, "does not name the project that refused"
    assert "ADR-0027" in why, "no trail back to the decision"


def test_the_refusal_is_shouted_where_an_alarm_can_see_it(capsys):
    admissible(_project(), "207", [TEST_WORK_LABEL])
    assert "OPENFACTORY_TEST_WORK_REFUSED" in capsys.readouterr().out
