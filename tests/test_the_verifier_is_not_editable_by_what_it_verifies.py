"""The agent may not move the ruler it is measured by — and may do it with a person watching.

The hole: the agent holds `Edit`/`Write` over the whole workspace and nothing deterministic stopped
it from editing `.openfactory/project.yaml` — the file naming the gates it must survive, and the
profile saying what the project IS. `roles/executor.md` spends a paragraph asking it not to, which
is the weak form of a rule, and this platform's whole thesis is that the weak form does not hold.

Two properties are load-bearing:

  1. HUMAN-GATED, NOT FORBIDDEN. A ticket that legitimately retunes a gate is a ticket somebody
     signs off. Nothing is refused and nothing is lost.
  2. THE LIST ONLY GROWS. A project may add to the deployment's floor and has no field to subtract
     from it, because an off switch for a floor is the first thing that gets set.

`.github/workflows/**` IS NOT ON THE FLOOR, and the section at the bottom of this file MEASURES why
rather than asserting it: `_commit` strips those changes before the commit and the diff this gate
reads is committed history, so the entry gated nothing while reading, to an operator, like
protection.
"""

from __future__ import annotations

import subprocess

import pytest

from openfactory.adapters.sandbox.base import Workspace
from openfactory.adapters.sandbox.worktree import WorktreeSandbox
from openfactory.contracts import Component, Manifest, RunResult, Ticket, ValidationResult
from openfactory.contracts.state import RiskLevel
from openfactory.orchestrator.merge_policy import should_auto_merge
from openfactory.policy import presets, protected

_PASS = [ValidationResult(name="test", command="t", exit_code=0, passed=True)]
_TICKET = Ticket(id="#1", title="raise the coverage floor", objective="o",
                 repo="acme/app")


def _result(**kw) -> RunResult:
    base = dict(ticket_id="#1", state="pr_open", validations=_PASS)
    base.update(kw)
    return RunResult(**base)


@pytest.fixture(autouse=True)
def _clean_cache():
    """Every cache over `floor.yaml`, not just this module's — the parse is shared with the floor's
    gates now, so clearing one accessor would leave the stale document underneath it."""
    presets.clear_floor_caches()
    yield
    presets.clear_floor_caches()


# ── what the deployment ships ───────────────────────────────────────────────────────────────────


def test_the_floor_protects_the_manifest_that_names_the_gates():
    """Not a preference. Every edit to `.openfactory/**` is, by construction, a change to what
    decides whether the agent passed."""
    floor = protected.floor_protected_paths()

    assert floor is not None, "the shipped floor must parse; None here means a broken install"
    assert ".openfactory/**" in floor


def test_the_manifest_naming_its_own_gates_cannot_be_edited_unattended():
    hits = protected.violations([".openfactory/project.yaml"], Manifest())

    assert hits == (".openfactory/project.yaml",)


def test_a_project_cannot_quietly_rewrite_the_class_it_is_judged_as():
    """The profile is now one of the verifier's inputs: a worker that can edit its own class can
    rewrite what "good" means for the repository it is working in."""
    hits = protected.violations([".openfactory/profiles/regulated.yaml"], Manifest())

    assert hits == (".openfactory/profiles/regulated.yaml",)


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
    assert ".openfactory/**" in effective
    assert protected.violations([".openfactory/project.yaml"], m) == (".openfactory/project.yaml",)


# ── the failure direction is closed, and it is a DIFFERENT SENTENCE ─────────────────────────────


def test_a_floor_that_cannot_be_read_gates_everything_rather_than_permitting_it(monkeypatch,
                                                                               tmp_path, caplog):
    """`None` is not `()`. A build that cannot read its own floor must stop the queue, not quietly
    widen what may merge — the correct direction for a floor and the expensive one for us."""
    monkeypatch.setattr(presets, "ORG_FLOOR_FILE", tmp_path / "gone.yaml")
    presets.clear_floor_caches()

    with caplog.at_level("ERROR"):
        assert protected.floor_protected_paths() is None
        assert protected.effective_protected_paths(Manifest()) is None
        assert protected.floor_unreadable(Manifest()) is True
    assert "OPENFACTORY_FLOOR_UNREADABLE" in caplog.text


def test_an_unreadable_floor_is_not_reported_as_a_change_to_the_clients_own_files(monkeypatch,
                                                                                  tmp_path):
    """THE FINDING REVIEW ON #18 NAMED, KEPT AS A TEST. The first revision answered an unreadable
    floor with the alphabetically first twelve CHANGED paths. It gated correctly, and every reader
    downstream — the pull request body, the durable `RunResult` — then said a real change had
    touched the verifier's own inputs, when what had happened is that OUR install is broken. That
    is this module's own `None`-is-not-`()` distinction, collapsed one layer down."""
    monkeypatch.setattr(presets, "ORG_FLOOR_FILE", tmp_path / "gone.yaml")
    presets.clear_floor_caches()

    assert protected.violations(["src/app.py", "README.md"], Manifest()) == ()
    assert protected.floor_unreadable(Manifest()) is True
    # and it still gates — the two facts are separate, not one traded for the other
    assert should_auto_merge(Manifest(merge_policy="auto"), _result(floor_unreadable=True)) is False


def test_the_unreadable_floor_blames_our_install_and_not_the_repository():
    """`floor_reason` already says this shape of sentence for the same situation, and for the same
    reason: nobody should be sent to edit a file that was already right."""
    line = protected.reason((), unreadable_floor=True)

    assert "OUR install" in line and "not this repository" in line
    assert "move the ruler" not in line, "this is not a finding about the client's change"


def test_a_deployment_that_declares_no_protected_path_is_not_a_broken_one(monkeypatch, tmp_path):
    """READ, NOTHING THERE. A floor with no `protected_paths:` is a configuration, not an install
    that failed — and collapsing the two would report a broken build to a deliberate deployment."""
    floor = tmp_path / "floor.yaml"
    floor.write_text("validate:\n  security: 'true'\n", encoding="utf-8")
    monkeypatch.setattr(presets, "ORG_FLOOR_FILE", floor)
    presets.clear_floor_caches()

    assert protected.floor_protected_paths() == ()
    assert protected.floor_unreadable(Manifest()) is False
    assert protected.violations(["src/app.py"], Manifest()) == ()


def test_one_parse_answers_both_gates_so_they_cannot_disagree(monkeypatch, tmp_path):
    """Two transcriptions of the same read WILL drift — `presets.py` already carries one edge case
    (`UnicodeDecodeError` as a `ValueError`) that cost a fleet-wide outage to find, and a copy
    inherits that fix by luck. Both gates turn the same answer into a merge decision, so "do they
    agree about whether the floor is READABLE" is a property worth having structurally."""
    bad = tmp_path / "floor.yaml"
    bad.write_bytes(b"validate:\n  security: '\xff\xfe not utf-8'\n")
    monkeypatch.setattr(presets, "ORG_FLOOR_FILE", bad)
    presets.clear_floor_caches()

    assert presets.org_default_validation() is None
    assert protected.floor_protected_paths() is None


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
    assert should_auto_merge(m, _result(floor_unreadable=False)) is True


def test_the_gate_names_what_it_refused():
    """A gate that refuses without naming what it refused is a gate nobody can argue with."""
    line = protected.reason((".openfactory/project.yaml",))

    assert ".openfactory/project.yaml" in line
    assert "cannot also move the ruler" in line
    assert protected.reason(()) == ""


def test_the_truncated_list_still_carries_the_true_number():
    """`MAX_SHOWN` bounds what a person is SHOWN, never what was measured. A change touching forty
    protected files reported twelve and the real number was gone, because a count taken from a
    truncated list is not a count — the split `undeclared_paths`/`undeclared_count` already makes."""
    many = tuple(f".openfactory/p{i:03d}.yaml" for i in range(40))

    line = protected.reason(many[:protected.MAX_SHOWN], len(many))

    assert "and 28 more" in line


def test_the_reason_reaches_the_pull_request_body_where_the_person_decides():
    """THE THIRD GATE IN THIS STACK THAT REFUSED SILENTLY. Without this the human opens a pull
    request that reads exactly like an ordinary "ready for review" — `should_auto_merge` returns
    False and the job takes the same `request_reviewers` branch — with no sign that a deterministic
    gate held it, let alone which file tripped it."""
    from openfactory.orchestrator.machine import JobRunner

    holder = type("_H", (), {
        "manifest": Manifest(),
        "_stripped_workflows": set(),
        "_knowledge_state": lambda self: "unavailable",
    })()
    result = _result(protected_hits=[".openfactory/project.yaml"], protected_count=1)

    body = JobRunner._pr_body(holder, _TICKET, result)

    assert ".openfactory/project.yaml" in body
    assert "cannot also move the ruler" in body


def test_it_stacks_with_the_risk_gate_rather_than_replacing_it():
    """Both are reasons a person looks; neither is the other's substitute."""
    m = Manifest(merge_policy="auto",
                 components={"infra": Component(path="infra/**", stack="terraform",
                                                risk=RiskLevel.HIGH)})

    assert should_auto_merge(m, _result(touched_components=["infra"])) is False
    assert should_auto_merge(
        Manifest(merge_policy="auto"),
        _result(protected_hits=[".openfactory/project.yaml"])) is False


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
        # `_validate` also takes the test census now, and a manifest with no `test_inventory`
        # returns None from it — but the METHOD still has to exist on the double.
        "_take_census": JobRunner._take_census,
    })()

    JobRunner._validate(holder, None, None)

    assert holder._protected == (".openfactory/project.yaml",)
    assert holder._floor_unreadable is False


def test_the_attempt_records_what_it_asked_so_the_gate_can_read_it():
    """The gate holds a `RunResult`, not a diff. An answer dropped on the way there exists for the
    length of one method and changes nothing."""
    from openfactory.orchestrator.machine import JobRunner

    many = tuple(f".openfactory/p{i:03d}.yaml" for i in range(40))
    holder = type("_H", (), {"_protected": many, "_floor_unreadable": False})()
    result = _result()

    JobRunner._record_risk(holder, result)

    assert result.protected_hits == list(many[:protected.MAX_SHOWN])
    assert result.protected_count == 40, "the count is taken before the truncation, or it is not a count"


def test_an_attempt_that_never_reached_validation_records_nothing_rather_than_raising():
    """`_protected` is set in `_validate`, and not every path through the machine validates."""
    from openfactory.orchestrator.machine import JobRunner

    result = _result()
    JobRunner._record_risk(type("_H", (), {})(), result)

    assert result.protected_hits == []
    assert result.protected_count == 0
    assert result.floor_unreadable is False


# ── the CI-repair path, which pushes to an ALREADY-ARMED auto-merge ─────────────────────────────
#
# The gate above is `should_auto_merge`, and the CI-repair pass never reaches it: it commits,
# pushes to an open pull request whose auto-merge is already armed, and the only thing standing
# between it and a merge is the suppression scan. The incentive on that path points straight at
# this feature — the agent is told "the CI for this PR is FAILING, make it pass", and the cheapest
# way to make a gate stop failing is to retune the gate in the file that names it.


def test_the_ci_repair_pass_disarms_auto_merge_when_it_touched_the_verifiers_inputs():
    from openfactory.orchestrator import machine as machine_mod

    src = _source_of(machine_mod)
    start = src.index("            supp = _added_suppressions(diff)")
    # to the end of the branch, not a character budget: a comment added inside it must not
    # be able to push the assertions below out of the window and turn this guard green.
    block = src[start:src.index("# THE PASS REVIEWS WHAT IT PRODUCED", start)]

    assert "protected_violations(" in block, (
        "the CI-repair pass never asks whether it edited the verifier's own inputs, so a repair "
        "that retunes `.openfactory/project.yaml` lands on an armed auto-merge with nothing in "
        "its way")
    assert "if supp or hits or unreadable:" in block, (
        "the disarm branch still fires on suppressions alone — a deleted gate emits no suppression "
        "token, and a floor that stopped parsing between the arming and this pass emits none "
        "either")
    assert "disable_auto_merge" in block


def _source_of(mod) -> str:
    from pathlib import Path

    return Path(mod.__file__).read_text(encoding="utf-8")


# ── WHY `.github/workflows/**` IS NOT ON THE FLOOR, measured ────────────────────────────────────


def _repo_with_a_workflow(tmp_path):
    """A real repository on `main`, carrying a workflow and an application file."""
    at = tmp_path / "repo"
    at.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(at)], check=True, capture_output=True)
    (at / ".github" / "workflows").mkdir(parents=True)
    (at / ".github" / "workflows" / "ci.yml").write_text("name: ci\n", encoding="utf-8")
    (at / "app.py").write_text("x = 1\n", encoding="utf-8")
    run = lambda *a: subprocess.run(["git", "-C", str(at), *a], check=True,  # noqa: E731
                                    capture_output=True)
    run("add", "-A")
    run("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init")
    run("checkout", "-q", "-b", "work")
    return at


def test_a_workflow_change_can_never_reach_this_gate_so_the_floor_does_not_claim_it(tmp_path):
    """MEASURED, NOT ASSERTED, because the entry that used to be here read like protection and was
    not. `_commit` reverts every `.github/workflows/**` change before the commit, and the diff this
    gate is asked about is `base..HEAD` — committed history. So the agent's workflow edit is gone by
    the time anyone can ask, `violations()` sees only `app.py`, and the floor entry gated nothing.

    The case is already handled one layer down: the strip is announced on the ticket and the pull
    request body carries every dropped file as an explicit human to-do. This test exists so the
    entry is not added back by somebody reading the old reasoning."""
    from openfactory.orchestrator.machine import JobRunner

    at = _repo_with_a_workflow(tmp_path)
    (at / ".github" / "workflows" / "ci.yml").write_text("name: ci\non: [push]\n", encoding="utf-8")
    (at / ".github" / "workflows" / "new.yml").write_text("name: new\n", encoding="utf-8")
    (at / "app.py").write_text("x = 2\n", encoding="utf-8")

    sandbox = WorktreeSandbox(root=tmp_path / "wt")
    ws = Workspace(path=at, branch="work", base_branch="main", host_path=at)
    holder = type("_H", (), {
        "sandbox": sandbox,
        "bot": type("_B", (), {"name": "bot", "email": "bot@t"})(),
        "_note_stripped_workflows": lambda self, ws, ticket: None,
    })()

    JobRunner._commit(holder, ws, _TICKET)
    changed = sandbox.diff_paths(workspace=ws)

    assert "app.py" in changed
    assert not any(p.startswith(".github/workflows/") for p in changed), (
        f"a workflow path reached the committed diff — the premise of this section changed: "
        f"{changed}")
    assert protected.violations(changed, Manifest()) == ()
    assert ".github/workflows/**" not in (protected.floor_protected_paths() or ()), (
        "the floor claims a path the diff can never carry, which reads to an operator as "
        "protection and is not")
