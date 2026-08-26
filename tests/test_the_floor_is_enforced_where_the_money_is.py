"""The quality floor gates a paid agent pass, not just a CLI command (C-40, #83).

`policy/floor.py` names `test` and `security` as the platform's non-negotiable validation roles.
Its only reader was `policy/conformance.py::check`, whose only caller is `sdlc conformance <name>`
— a command nothing in the job path invokes. So a project registered with a thin `validate:` block
ran the agent, and then:

    RunResult.all_passed = all(v.passed for v in self.validations)   # all([]) is True
    should_auto_merge    = gates on exactly that                     # merge_policy.py:41

…auto-merged on a quality floor that was the empty set. Nothing would ever have told the client.

The same property carried a SECOND defect, mine, hours old: `machine._all_passed` learned to
exclude advisory gates (C-37) and this one — the one `should_auto_merge` actually reads — did not,
so an advisory security scan reporting a finding blocked the merge. The free security preset would
have been the first thing a client turned off.
"""

from __future__ import annotations

import pytest

from openfactory.contracts import Manifest, RunResult, ValidationResult
from openfactory.policy.conformance import floor_reason


@pytest.fixture
def no_deployment_floor(monkeypatch):
    """The world BEFORE `org_defaults/floor.yaml`: nothing is inherited, so a manifest means
    exactly what its own file says.

    WHY THESE TESTS NEED IT NOW. Every project inherits a `security` gate from the deployment's
    default (`Manifest._inherit_the_deployment_floor`), so `validate: {test: …}` no longer violates
    the floor — which is the point of that change and would silently gut these three tests into
    tautologies. They are about the REFUSAL, not about which role happens to be missing, so they
    keep their subject and state their world. It is not a hypothetical world either: a build that
    cannot read `floor.yaml` is exactly this one, and it is the path `floor_reason` still takes."""
    monkeypatch.setattr("openfactory.policy.presets.org_default_validation", lambda: {})


def _v(name: str, passed: bool, advisory: bool = False) -> ValidationResult:
    return ValidationResult(name=name, command="c", exit_code=0 if passed else 1,
                            passed=passed, advisory=advisory)


def _result(*validations) -> RunResult:
    return RunResult(ticket_id="#1", state="pr_open", validations=list(validations))


# ── all_passed stops claiming a green nobody earned ──────────────────────────────────────────────

def test_no_gates_at_all_is_not_a_pass():
    """`all([])` is True. That was the entire quality floor of a thin manifest."""
    assert _result().all_passed is False


def test_an_ADVISORY_failure_does_not_block():
    """C-37's whole claim, on the property `should_auto_merge` actually reads."""
    assert _result(_v("test", True), _v("security", False, advisory=True)).all_passed is True


def test_a_BLOCKING_failure_still_blocks():
    assert _result(_v("test", False)).all_passed is False


def test_advisory_alone_is_not_a_pass_either():
    """A project whose only gates are advisory has nothing that can fail — the same vacuous green
    by a different route."""
    assert _result(_v("security", True, advisory=True)).all_passed is False


def test_auto_merge_follows_it():
    """The reachability half: the property is only worth fixing because this reads it."""
    from openfactory.orchestrator.merge_policy import should_auto_merge

    m = Manifest(version=1, base_branch="main", merge_policy="auto",
                 validate={"test": "pytest -q", "security": "s"})
    assert should_auto_merge(m, _result(_v("test", True), _v("security", False, advisory=True)))
    assert not should_auto_merge(m, _result())


# ── the floor refuses before an agent is paid ────────────────────────────────────────────────────

def test_a_manifest_missing_security_is_refused(no_deployment_floor):
    reason = floor_reason(Manifest(version=1, base_branch="main", validate={"test": "pytest -q"}))
    assert reason and "security" in reason


def test_the_refusal_says_what_to_ADD_not_just_what_is_wrong(no_deployment_floor):
    """`doctor`'s standing bar: one cause, one actionable line. A floor violation lives in the
    client's repository, so the sentence has to point there."""
    reason = floor_reason(Manifest(version=1, base_branch="main", validate={"test": "p"}))
    assert "validate:" in reason and ".openfactory/project.yaml" in reason
    assert "security-oss" in reason  # a preset that satisfies it for free


def test_a_complete_manifest_is_not_refused():
    assert floor_reason(Manifest(version=1, base_branch="main",
                                 validate={"test": "p", "security": "s"})) is None


def test_a_PRESET_can_satisfy_the_floor():
    """The floor is about what will RUN, not about what is typed in one file — `security-oss`
    ships the gate, so a component adopting it must count."""
    m = Manifest(version=1, base_branch="main", validate={"test": "p"},
                 components={"api": {"path": "api/", "stack": "security-oss"}})
    assert floor_reason(m) is None


def _env_reads_in(node) -> list[str]:
    """Every read of the process environment inside `node`, as source text.

    `os.environ[...]`, `os.environ.get(...)`, `os.getenv(...)` and a bare `environ` imported from
    `os` — the four shapes a switch arrives in. Deliberately NOT a substring match on "environ":
    `Manifest.environments` is a legitimate field of this codebase and the loose version flagged
    it, which is a guard that fires on correct code and therefore a guard somebody deletes.
    """
    import ast

    out: list[str] = []
    for n in ast.walk(node):
        if isinstance(n, ast.Attribute) and n.attr in ("environ", "getenv"):
            out.append(ast.unparse(n))
        elif isinstance(n, ast.Name) and n.id in ("environ", "getenv"):
            out.append(ast.unparse(n))
    return out


def test_NO_ENVIRONMENT_VARIABLE_CAN_TURN_THE_FLOOR_OFF(monkeypatch):
    """The floor refuses, always. There is nothing to set, and that is the assertion.

    `OPENFACTORY_ENFORCE_FLOOR` used to decide this, off by default, and the tests above it in this file
    asserted exactly that — *"every project this platform drives violates the floor today,
    including the live client's; a floor that arrives as an outage is a floor an operator
    disables"*. True when written, and it expired the day `org_defaults/floor.yaml` landed: every
    project now inherits a `security` gate that needs only a POSIX shell and `git`, so the only way
    to fail the floor is to declare no `test` command — which is precisely what must not buy a paid
    agent pass.

    THE VARIABLE WAS REMOVED, NOT DEFAULTED TO ON, and this test guards that rather than a value.
    A switch that can turn the floor off is the floor being negotiable, and four places say in
    writing that it is not (`policy/floor.py`, `org_defaults/floor.yaml`, `docs/architecture.md`
    §7, ADR-0001 D-2). Off by default made all four false wherever nobody knew the name — which,
    on an open-source install, is everywhere.

    Asserted over the SOURCE as well as the behaviour, because a reintroduced switch would most
    likely arrive as a new name, and a test that only set the old one would never see it.
    """
    import ast
    import inspect

    from openfactory.doctor import floor_is_enforced
    from openfactory.orchestrator import machine

    for value in ("", "0", "false", "no", "1", "true"):
        monkeypatch.setenv("OPENFACTORY_ENFORCE_FLOOR", value)
        assert floor_is_enforced() is True, f"a floor switched by the environment: {value!r}"
    monkeypatch.delenv("OPENFACTORY_ENFORCE_FLOOR", raising=False)
    assert floor_is_enforced() is True

    # THE CODE, NOT THE PROSE — `ast.unparse` drops comments, and that distinction is the point.
    # The first version of this line read the raw source and failed on the comment that RECORDS
    # why the variable was removed, which would have taught the next person to delete the
    # explanation in order to make the guard pass. The history is worth keeping; the read is not.
    tree = ast.parse(inspect.getsource(machine))
    code = ast.unparse(tree)
    assert "OPENFACTORY_ENFORCE_FLOOR" not in code, "the runner reads a floor switch again"
    # NO environment read at all inside the refusal path — a new variable under a different name is
    # the same defect wearing a different word, and this catches that too.
    run = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "run")
    assert _env_reads_in(run) == [], (
        f"the job path consults the environment before refusing: {_env_reads_in(run)}")


def test_this_guard_can_SEE_an_environment_read():
    """The positive twin. A scanner that stopped matching would report a clean runner.

    Absence reads as compliance — the way three guards in this repository stayed green over live
    defects — so the detector is handed the four shapes a switch actually arrives in, and then the
    one that must NOT match. `manifest.environments.keys()` is not hypothetical: the first version
    of `_env_reads_in` matched the substring "environ" and flagged it, which would have made this
    guard fire on the manifest's own deployment-environments field.
    """
    import ast

    for source in ("import os\nos.environ.get('X')",
                   "import os\nos.environ['X']",
                   "import os\nos.getenv('X')",
                   "from os import environ\nenviron.get('X')"):
        found = _env_reads_in(ast.parse(source))
        assert found, f"the detector cannot see a read it is given: {source!r}"
    assert _env_reads_in(ast.parse("list(self.manifest.environments.keys())")) == [], (
        "the detector fires on `manifest.environments`, which is a field and not a switch")


def test_the_violation_is_SAID_even_when_it_does_not_block():
    """Announced-but-invisible would be the worst of both: no protection and no warning."""
    import ast
    import inspect

    from openfactory.orchestrator.machine import JobRunner

    tree = ast.parse(inspect.getsource(JobRunner.run).lstrip())
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "floor_reason"):
            continue
        enclosing = ast.unparse(tree)
        assert "quality floor" in enclosing, "the violation is computed and never said"
        return
    raise AssertionError("the runner never asks the floor")


def test_the_runner_asks_BEFORE_any_agent_call():
    """The reachability guard. `floor_reason` returning the right string proves nothing if the
    job path never asks — which is exactly the state this card describes."""
    import ast
    import inspect

    from openfactory.orchestrator.machine import JobRunner

    src = inspect.getsource(JobRunner.run)
    tree = ast.parse(src.lstrip())
    called = [n for n in ast.walk(tree)
              if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "floor_reason"]
    assert called, "the runner never asks the floor"
    # and it asks before the agent: the floor call must precede any `self.agent.` use
    body = src.split("floor_reason(")[0]
    assert "self.agent." not in body, "an agent pass happens before the floor is checked"


@pytest.mark.parametrize("roles", [{"test"}, {"security"}, set()])
def test_every_incomplete_shape_is_refused(roles, no_deployment_floor):
    m = Manifest(version=1, base_branch="main", validate={r: "cmd" for r in roles})
    assert floor_reason(m) is not None


# ── the non-negotiables name what enforces them (C-40, second half) ──────────────────────────────

def test_every_global_deny_names_a_real_enforcement_path():
    """`GLOBAL_DENY` was a frozenset of four English phrases referenced by NOTHING — an audit found
    it as the single occurrence of its own name, in the file whose docstring claims to make "what
    the platform guarantees regardless of project" auditable in one place. It was auditable and
    inert, in the file a security review opens first.

    A frozenset of prose can never be enforced: "push to protected branch" is not an interceptable
    operation, it is a description of one. So each entry now names the code that actually denies
    it — and this test is what stops that decaying back into prose: every path must exist."""
    import pathlib

    from openfactory.policy.floor import GLOBAL_DENY

    root = pathlib.Path(__file__).resolve().parent.parent
    assert GLOBAL_DENY, "the platform's non-negotiables are empty"

    missing = []
    for action, where in GLOBAL_DENY.items():
        assert where.strip(), f"{action} names no enforcement"
        for ref in where.replace(";", " ").split():
            if "::" not in ref and not ref.endswith(".py"):
                continue
            path = ref.split("::", 1)[0]
            symbol = ref.split("::", 1)[1] if "::" in ref else ""
            file = root / path
            if not file.exists():
                missing.append(f"{action}: {path} does not exist")
                continue
            if symbol and symbol not in file.read_text(encoding="utf-8"):
                missing.append(f"{action}: {path} has no {symbol}")
    assert missing == [], missing


def test_the_denials_cover_the_actions_a_review_asks_about():
    """The set may shrink only deliberately: each of these is a question an enterprise security
    review asks in its first pass."""
    from openfactory.policy.floor import GLOBAL_DENY

    for action in ("push --force", "push to protected branch", "access production",
                   "read secrets directly"):
        assert action in GLOBAL_DENY


def test_an_e2e_TICKET_is_not_held_by_the_floor():
    """The floor guards the MONEY, and an e2e ticket spends none of it.

    An `e2e`-labelled ticket dispatches the client's own workflow and reports that workflow's real
    conclusion (ADR-0008) — no plan, no agent, no PR. There is no vacuous green to prevent and no
    pass to pay for, so holding it spends nothing to protect nothing and tells a client their test
    suite may not run because they declared no test command.

    FOUND BY REMOVING THE SWITCH. Two e2e tests went red the moment the refusal became
    unconditional; while it sat behind `OPENFACTORY_ENFORCE_FLOOR`, off by default, nothing could have
    shown it. The fix was ordering — the floor now sits below the e2e short-circuit — and this is
    the guard, because "these two lines are in this order" is exactly what a refactor loses.
    """
    import ast
    import inspect

    from openfactory.orchestrator import machine

    run = next(n for n in ast.walk(ast.parse(inspect.getsource(machine)))
               if isinstance(n, ast.FunctionDef) and n.name == "run")
    body = ast.unparse(run).splitlines()
    e2e = next(i for i, line in enumerate(body) if "_is_e2e_ticket" in line)
    floor = next(i for i, line in enumerate(body) if "floor_reason" in line)
    assert e2e < floor, (
        "the quality floor is checked BEFORE the e2e short-circuit, so an e2e ticket on a project "
        "with no `test` gate is held — a refusal that costs the client their test run and saves "
        "nobody an agent pass, because that path never calls one"
    )
