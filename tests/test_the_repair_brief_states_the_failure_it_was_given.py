"""#184 — the repair brief states the failure it was given, or the repair does not run.

WHAT THE AGENT WAS TOLD. "The GitHub CI for this PR is FAILING. Make it pass." and then whatever
`ci_log` held. On the deployment that reported this the forge was Azure DevOps, the red "check"
was an optional work-item policy, no build had run — so the log was empty, and an agent holding
the checkout, the push remote and a reviewed diff was told a failure existed and shown none.

THREE DOORS LEAD TO THAT BRIEF, and the rule has to hold at each:

    the worker   `_run_ci_repair`, for a local box — hands over the log the decision was made from
    the box      `boxed_job.run_ci_repair`, inside a remote task — fetched its OWN log and ran the
                 agent whatever came back; it now goes through the same gate as the worker
    the machine  `JobRunner.repair_ci`, the last door — refuses an empty failure before the card
                 moves or a workspace is prepared, and names the forge by its row

And a person's review comment (#68) shares the machinery: it is not announced as a red build.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from openfactory.adapters.forge.azure_devops import AzureReposForge
from openfactory.adapters.forge.base import display_name
from openfactory.adapters.forge.github import GitHubForge
from openfactory.contracts import AgentRunResult, JobState, Manifest, RunResult
from openfactory.runtime import boxed_job, repairable
from openfactory.runtime.temporal import activities as acts
from openfactory.runtime.temporal.io import CiRepairInput
from tests.test_walking_skeleton import (
    FakeForge,
    FakeTracker,
    _git,
    _runner,
    _sizing_ticket_id,
    repo,  # noqa: F401 — the fixture: a real repository with a bare origin to push to
)

ROOT = Path(__file__).resolve().parents[1]
LOG = "FAILED tests/test_export.py::test_it - AssertionError: 3 != 4"
PR = "https://forge/pr/1"


# ═══ the forge's name comes from its row ════════════════════════════════════════════════════════

def test_each_shipped_forge_says_what_it_is_called_and_a_stranger_is_named_neutrally():
    assert display_name(GitHubForge("acme/x")) == "GitHub"
    assert display_name(AzureReposForge("x", organization="o", project="p")) == "Azure DevOps"
    assert display_name(object()) == "the forge"
    assert display_name(MagicMock()) == "the forge", "a test double is not a declaration"
    assert display_name(SimpleNamespace(display_name="  ")) == "the forge"


# ═══ the machine: the last door ═════════════════════════════════════════════════════════════════

class _Agent:
    """Records the brief it was handed, and fixes something so the pass has a diff to push."""

    def __init__(self):
        self.briefs: list[str] = []

    def repair(self, *, sandbox, workspace, context, failure_log):
        self.briefs.append(failure_log)
        (workspace.path / "ci_fix.py").write_text("FIXED = True\n")
        return AgentRunResult(ok=True, summary="fixed", cost_usd=0.01, actions=[])


def _an_open_pull_request(repo: Path) -> None:  # noqa: F811 — the fixture's value, by its name
    _git(["checkout", "-b", "openfactory/9"], repo)
    (repo / "broken.py").write_text("x\n")
    _git(["add", "-A"], repo)
    _git(["commit", "-m", "wip"], repo)
    _git(["push", "-u", "origin", "openfactory/9"], repo)
    _git(["checkout", "main"], repo)
    _git(["branch", "-D", "openfactory/9"], repo)


def _machine(repo: Path, tmp_path: Path, *, forge_name: str | None):  # noqa: F811
    forge = FakeForge()
    if forge_name is not None:
        forge.display_name = forge_name
    agent, tracker = _Agent(), FakeTracker(_sizing_ticket_id("#9"))
    runner = _runner(repo, tracker, Manifest(validate={"test": "true"}), tmp_path,
                     agent=agent, forge=forge)
    return runner, agent, tracker


def test_the_brief_names_the_forge_by_its_row_and_carries_the_log(repo, tmp_path):  # noqa: F811
    _an_open_pull_request(repo)
    runner, agent, _ = _machine(repo, tmp_path, forge_name="Azure DevOps")

    runner.repair_ci("#9", LOG, pr_url=PR)

    (brief,) = agent.briefs
    assert "FAILING on Azure DevOps" in brief and LOG in brief
    assert "GitHub" not in brief, "the brief names a vendor this forge is not"


def test_a_forge_that_declares_no_name_is_not_given_somebody_elses(repo, tmp_path):  # noqa: F811
    _an_open_pull_request(repo)
    runner, agent, _ = _machine(repo, tmp_path, forge_name=None)
    runner.repair_ci("#9", LOG, pr_url=PR)
    assert "FAILING on the forge" in agent.briefs[0] and "GitHub" not in agent.briefs[0]


@pytest.mark.parametrize("nothing", ["", "  \n "])
def test_with_no_failure_to_show_the_machine_launches_nothing(repo, tmp_path, nothing):  # noqa: F811
    """BEFORE the card moves to *repairing* and before a workspace exists — there is no open
    branch in this repository at all, so reaching `prepare` would raise rather than hold."""
    runner, agent, tracker = _machine(repo, tmp_path, forge_name="Azure DevOps")

    got = runner.repair_ci("#9", nothing, pr_url=PR)

    assert agent.briefs == [], "an agent was told a failure exists and shown none"
    assert got.state is JobState.ON_HOLD and got.pr_url == PR
    assert got.merge_refused is True and got.code_changed is False
    assert "Azure DevOps shows no failing log" in got.note
    assert JobState.REPAIRING not in tracker.states


def test_a_persons_comment_is_not_announced_as_a_red_build(repo, tmp_path):  # noqa: F811
    _an_open_pull_request(repo)
    runner, agent, _ = _machine(repo, tmp_path, forge_name="GitHub")
    asked = "A HUMAN REVIEWED THIS PULL REQUEST… This is not a build failure.\nmake it blue"

    runner.repair_ci("#9", asked, pr_url=PR, human=True)

    assert agent.briefs == [asked], "the person's words were wrapped in a CI failure sentence"


def test_the_machines_repair_names_no_vendor():
    """Parsed, not grepped: string constants in `repair_ci`'s CODE, its docstring excluded (the
    docstring tells the incident, by name)."""
    tree = ast.parse((ROOT / "openfactory/orchestrator/machine.py").read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "repair_ci")
    doc = fn.body[0].value if isinstance(fn.body[0], ast.Expr) else None
    said = " ".join(n.value for n in ast.walk(fn)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str) and n is not doc)
    for vendor in ("GitHub", "Azure", "GitLab"):
        assert vendor not in said, f"the generic repair path says {vendor!r}"


# ═══ the gate both callers go through ═══════════════════════════════════════════════════════════

class _Forge:
    checks_are_typed = True

    def __init__(self, rows, log=""):
        self.rows, self.log, self.reads = rows, log, 0

    def pr_checks(self, *, pr):
        self.reads += 1
        return self.rows

    def failed_ci_logs(self, *, pr):
        return self.log


RED_BUILD = [{"name": "build", "bucket": "fail", "blocking": True, "kind": "code"}]
PROCESS = [{"name": "Work item linking", "bucket": "fail", "blocking": True, "kind": "process",
            "remedy": "Link a work item."}]


def test_the_gate_hands_back_the_log_the_decision_was_made_from():
    held, log = repairable.what_to_repair(lambda: _Forge(RED_BUILD, LOG), "12", PR)
    assert held is None and log == LOG


# ═══ the box: the door the worker's check does not cover ════════════════════════════════════════

@pytest.fixture
def in_the_box(monkeypatch, tmp_path):
    """`run_ci_repair` with its three seams replaced: the project, its forge, the runner."""
    ran: list[dict] = []

    def use(forge, *, env: dict[str, str]):
        monkeypatch.setattr(boxed_job, "_register", lambda cfg, workdir, token: object())
        monkeypatch.setattr("openfactory.adapters.forge.registry.build_forge",
                            lambda project, **kw: forge)
        monkeypatch.setattr("openfactory.observability.registry.journal_for",
                            lambda *a, **kw: None)
        monkeypatch.setattr("openfactory.paths.events_file", lambda *a: tmp_path / "events")

        def runner(*a, **kw):
            def repair_ci(issue, ci_log, pr_url="", human=False):
                ran.append({"log": ci_log, "human": human, "pr": pr_url})
                return RunResult(ticket_id=issue, state=JobState.PR_OPEN, pr_url=pr_url)
            return SimpleNamespace(repair_ci=repair_ci)

        monkeypatch.setattr("openfactory.factory.build_runner", runner)
        for key in ("OPENFACTORY_PR", "OPENFACTORY_ADJUST_TEXT"):
            monkeypatch.delenv(key, raising=False)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        return ran

    return use


CFG = SimpleNamespace(issue="12", review=False)


def test_the_box_launches_nothing_for_a_check_only_a_person_settles(in_the_box, tmp_path):
    ran = in_the_box(_Forge(PROCESS), env={"OPENFACTORY_PR": PR})
    got = boxed_job.run_ci_repair(CFG, workdir=tmp_path, token=None)
    assert ran == [], "the box ran an agent at a policy no code change can satisfy"
    assert got.state is JobState.ON_HOLD and got.merge_refused is True
    assert "'Work item linking'" in got.note and "Link a work item." in got.note


def test_the_box_launches_nothing_without_a_failing_log(in_the_box, tmp_path):
    """THE DEFECT, ON THIS DOOR: it fetched its own log and ran whatever came back, `""` too."""
    ran = in_the_box(_Forge(RED_BUILD, log=""), env={"OPENFACTORY_PR": PR})
    got = boxed_job.run_ci_repair(CFG, workdir=tmp_path, token=None)
    assert ran == [] and got.state is JobState.ON_HOLD and "no failure log" in got.note


def test_the_box_repairs_a_red_build_with_the_log_the_decision_was_made_from(in_the_box,
                                                                             tmp_path):
    ran = in_the_box(_Forge(RED_BUILD, LOG), env={"OPENFACTORY_PR": PR})
    boxed_job.run_ci_repair(CFG, workdir=tmp_path, token=None)
    assert ran == [{"log": LOG, "human": False, "pr": PR}]


def test_the_box_does_not_ask_the_forge_about_a_persons_comment(in_the_box, tmp_path):
    forge = _Forge([])
    ran = in_the_box(forge, env={"OPENFACTORY_PR": PR, "OPENFACTORY_ADJUST_TEXT": "make it blue"})
    boxed_job.run_ci_repair(CFG, workdir=tmp_path, token=None, human=True)
    assert ran == [{"log": "make it blue", "human": True, "pr": PR}] and forge.reads == 0


# ═══ the worker: which words it hands the machine ═══════════════════════════════════════════════

@pytest.fixture
def on_the_worker(monkeypatch):
    ran: list[dict] = []
    project = SimpleNamespace(name="p")
    monkeypatch.setattr(acts, "ProjectRegistry", lambda: SimpleNamespace(get=lambda _n: project))
    monkeypatch.setattr(acts, "_ref_repo", lambda _p, _i: ("acme/x", ""))
    monkeypatch.setattr(acts, "_runner_view", lambda _p, _i: (project, ""))
    monkeypatch.setattr(acts, "_resolved_image", lambda _p, sandbox: "")
    monkeypatch.setattr(acts, "installed_box_traits", lambda _s: SimpleNamespace(remote=False))

    def runner(*a, **kw):
        def repair_ci(issue, ci_log, pr_url="", human=False):
            ran.append({"log": ci_log, "human": human})
            return RunResult(ticket_id=issue, state=JobState.PR_OPEN, pr_url=pr_url)
        return SimpleNamespace(repair_ci=repair_ci)

    monkeypatch.setattr(acts, "build_runner", runner)
    monkeypatch.setattr(acts, "_forge_for", lambda _p: _Forge(RED_BUILD, LOG))
    return ran


INPUT = CiRepairInput(project="p", issue="12", pr_url=PR, sandbox="worktree")


def test_the_worker_says_whose_words_fill_the_slot(on_the_worker):
    acts._run_ci_repair(INPUT)  # noqa: SLF001 — the activity's own body
    acts._run_ci_repair(INPUT, ci_log="make it blue")  # noqa: SLF001
    assert on_the_worker == [{"log": LOG, "human": False},
                             {"log": "make it blue", "human": True}]
