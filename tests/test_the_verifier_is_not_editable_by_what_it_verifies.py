"""The agent may not move the ruler it is measured by — and may do it with a person watching.

The hole: the agent holds `Edit`/`Write` over the whole workspace and nothing deterministic stopped
it from editing `.openfactory/project.yaml` — the file naming the gates it must survive — or the CI
configuration. `roles/executor.md` spends a paragraph asking it not to, which is the weak form of a
rule, and this platform's whole thesis is that the weak form does not hold.

`.github/workflows/**` was protected at the WRONG MOMENT: the forge rejects the push, so the agent
edits freely, works, and the work is lost at the end.

Two properties are load-bearing:

  1. HUMAN-GATED, NOT FORBIDDEN. A ticket that legitimately retunes a gate is a ticket somebody
     signs off. Nothing is refused and nothing is lost.
  2. THE LIST ONLY GROWS. A project may add to the deployment's floor and has no field to subtract
     from it, because an off switch for a floor is the first thing that gets set.
"""

from __future__ import annotations

import pytest

from openfactory.contracts import Component, Manifest, RunResult, ValidationResult
from openfactory.contracts.state import RiskLevel
from openfactory.orchestrator.merge_policy import should_auto_merge
from openfactory.policy import protected

_PASS = [ValidationResult(name="test", command="t", exit_code=0, passed=True)]


def _result(**kw) -> RunResult:
    base = dict(ticket_id="#1", state="pr_open", validations=_PASS)
    base.update(kw)
    return RunResult(**base)


@pytest.fixture(autouse=True)
def _clean_cache():
    """`floor_protected_paths` is cached for the process, like the floor's gates beside it."""
    protected.floor_protected_paths.cache_clear()
    yield
    protected.floor_protected_paths.cache_clear()


# ── what the deployment ships ───────────────────────────────────────────────────────────────────


def test_the_floor_protects_the_manifest_and_the_ci_configuration():
    """These are not a preference. Every edit to either is, by construction, a change to what
    decides whether the agent passed."""
    floor = protected.floor_protected_paths()

    assert floor is not None, "the shipped floor must parse; None here means a broken install"
    assert ".openfactory/**" in floor
    assert ".github/workflows/**" in floor


def test_the_manifest_naming_its_own_gates_cannot_be_edited_unattended():
    hits = protected.violations([".openfactory/project.yaml"], Manifest())

    assert hits == (".openfactory/project.yaml",)


def test_a_project_cannot_quietly_rewrite_the_class_it_is_judged_as():
    """The profile is now one of the verifier's inputs: a worker that can edit its own class can
    rewrite what "good" means for the repository it is working in."""
    hits = protected.violations([".openfactory/profiles/regulated.yaml"], Manifest())

    assert hits == (".openfactory/profiles/regulated.yaml",)


def test_the_ci_configuration_is_gated_before_the_expensive_part_not_after():
    """The forge already rejected this push. Rejecting it at the END is a guard that costs more
    than the defect it catches — the agent has done the work by then."""
    hits = protected.violations([".github/workflows/ci.yml"], Manifest())

    assert hits == (".github/workflows/ci.yml",)


def test_ordinary_work_is_untouched_by_any_of_this():
    """The property that keeps this from being the fix doing more damage than the defect."""
    assert protected.violations(["src/app.py", "README.md", "tests/test_app.py"], Manifest()) == ()


def test_an_empty_diff_is_not_a_violation():
    """Nothing changed, so nothing reached the verifier — the same reading `risk.assess` gives."""
    assert protected.violations([], Manifest()) == ()
    assert protected.violations(None, Manifest()) == ()


# ── the list only grows ─────────────────────────────────────────────────────────────────────────


def test_a_project_may_add_to_the_floor_and_its_addition_takes_effect():
    m = Manifest(protected_paths=["infra/**"])

    assert protected.violations(["infra/main.tf"], m) == ("infra/main.tf",)
    assert protected.violations(["infra/main.tf"], Manifest()) == ()


def test_a_projects_own_list_never_subtracts_from_the_deployments():
    """There is no field for removal, and the floor survives whatever the project writes."""
    m = Manifest(protected_paths=["infra/**"])
    effective = protected.effective_protected_paths(m)

    assert effective is not None
    assert ".openfactory/**" in effective and ".github/workflows/**" in effective
    assert protected.violations([".openfactory/project.yaml"], m) == (".openfactory/project.yaml",)


# ── the failure direction is closed ─────────────────────────────────────────────────────────────


def test_a_floor_that_cannot_be_read_gates_everything_rather_than_permitting_it(monkeypatch,
                                                                               tmp_path, caplog):
    """`None` is not `()`. A build that cannot read its own floor must stop the queue, not quietly
    widen what may merge — the correct direction for a floor and the expensive one for us."""
    monkeypatch.setattr(protected, "ORG_FLOOR_FILE", tmp_path / "gone.yaml")
    protected.floor_protected_paths.cache_clear()

    with caplog.at_level("ERROR"):
        assert protected.floor_protected_paths() is None
        assert protected.effective_protected_paths(Manifest()) is None
        assert protected.violations(["src/app.py"], Manifest()) == ("src/app.py",)
    assert "OPENFACTORY_FLOOR_UNREADABLE" in caplog.text


def test_a_deployment_that_declares_no_protected_path_is_not_a_broken_one(monkeypatch, tmp_path):
    """READ, NOTHING THERE. A floor with no `protected_paths:` is a configuration, not an install
    that failed — and collapsing the two would report a broken build to a deliberate deployment."""
    floor = tmp_path / "floor.yaml"
    floor.write_text("validate:\n  security: 'true'\n", encoding="utf-8")
    monkeypatch.setattr(protected, "ORG_FLOOR_FILE", floor)
    protected.floor_protected_paths.cache_clear()

    assert protected.floor_protected_paths() == ()
    assert protected.violations(["src/app.py"], Manifest()) == ()


# ── the merge gate reads it ─────────────────────────────────────────────────────────────────────


def test_a_change_to_the_verifiers_inputs_does_not_merge_by_itself():
    m = Manifest(merge_policy="auto")

    assert should_auto_merge(m, _result()) is True
    assert should_auto_merge(
        m, _result(protected_hits=[".openfactory/project.yaml"])) is False


def test_an_attempt_from_before_the_field_existed_is_not_retro_gated():
    """An old result cannot answer a question nobody asked it, and inventing a gate for it would
    refuse merges on evidence that does not exist — the rule `undeclared_count` already set."""
    m = Manifest(merge_policy="auto")

    assert should_auto_merge(m, _result(protected_hits=[])) is True


def test_the_gate_names_what_it_refused():
    """A gate that refuses without naming what it refused is a gate nobody can argue with."""
    line = protected.reason((".openfactory/project.yaml",))

    assert ".openfactory/project.yaml" in line
    assert "cannot also move the ruler" in line
    assert protected.reason(()) == ""


def test_it_stacks_with_the_risk_gate_rather_than_replacing_it():
    """Both are reasons a person looks; neither is the other's substitute."""
    m = Manifest(merge_policy="auto",
                 components={"infra": Component(path="infra/**", stack="terraform",
                                                risk=RiskLevel.HIGH)})

    assert should_auto_merge(m, _result(touched_components=["infra"])) is False
    assert should_auto_merge(
        Manifest(merge_policy="auto"),
        _result(protected_hits=[".github/workflows/ci.yml"])) is False


# ── the attempt has to ASK, and then RECORD ─────────────────────────────────────────────────────
#
# Everything above tests the guard and the gate on hand-built results, and neither notices if the
# attempt never asks the diff or never puts the answer where the gate reads it. Both mutations
# survived their first run for exactly that reason — the same lesson `undeclared_paths` learned one
# field earlier.


def test_the_attempt_asks_the_diff_which_paths_are_the_verifiers_own():
    """If `_validate` never asks, the verifier's inputs are indistinguishable from application
    code and every guard above still passes."""
    from openfactory.orchestrator.machine import JobRunner

    holder = type("_H", (), {
        "sandbox": type("_S", (), {
            "diff_paths": staticmethod(
                lambda workspace=None: [".openfactory/project.yaml", "src/app.py"]),
        })(),
        "manifest": Manifest(),
        "_set_state": lambda self, ticket, state: None,
        "_run_validations": lambda self, ws, touched, ticket: [],
    })()

    JobRunner._validate(holder, None, None)

    assert holder._protected == (".openfactory/project.yaml",)


def test_the_attempt_records_what_it_asked_so_the_gate_can_read_it():
    """The gate holds a `RunResult`, not a diff. An answer dropped on the way there exists for the
    length of one method and changes nothing."""
    from openfactory.orchestrator.machine import JobRunner

    holder = type("_H", (), {"_protected": (".github/workflows/ci.yml",)})()
    result = _result()

    JobRunner._record_risk(holder, result)

    assert result.protected_hits == [".github/workflows/ci.yml"]


def test_an_attempt_that_never_reached_validation_records_nothing_rather_than_raising():
    """`_protected` is set in `_validate`, and not every path through the machine validates."""
    from openfactory.orchestrator.machine import JobRunner

    result = _result()
    JobRunner._record_risk(type("_H", (), {})(), result)

    assert result.protected_hits == []
