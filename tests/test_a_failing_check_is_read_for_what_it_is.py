"""#184 — a failing forge check is read for what it IS, and only a broken build is repaired.

WHAT IT COST. On a live Azure DevOps deployment (2026-09-18) a job opened its pull request and one
second later the merge watch read `failure`. Nothing had been built — no build on the source
branch, none on the merge ref. The only things evaluated were two repository POLICIES, both
optional (`isBlocking: false`): *Work item linking*, rejected because that team links none, and
*Comment requirements*, approved. The watch went straight to a CI repair: it fetched the failing
logs (empty), launched the executor anyway with a brief asserting a failure it could not show,
did it again, and parked the card `CI still failing after 2 repair attempt(s)`. Every card on
that repository would have paid the same two agent passes, over a reviewed diff.

THE CAUSE WAS THE PORT, not the adapter: one four-valued word for "the PR's checks", turned into
an agent run. These cases pin the three questions that word collapsed — does it block, is it
about the code, is there evidence — at every layer that answers one of them:

    the table      `contracts/checks.py::decide`, as a table
    each forge     its own vocabulary mapped into the rows: Azure DevOps, GitHub, the local forge,
                   and an add-on that has never heard of any of this
    the activity   nothing is launched unless the table says repair
    the watch      the real `JobWorkflow`, on a real (time-skipping) engine
    the panel      an advisory check is not drawn as a red gate
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import uuid
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from temporalio import activity
from temporalio.client import Client, WorkflowHandle
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from openfactory.adapters.forge.github import GitHubForge
from openfactory.adapters.forge.local import LocalForge
from openfactory.contracts import JobState, RunResult, checks
from openfactory.contracts.checks import ASK, REPAIR, WAIT, Check, CiDecision, decide
from openfactory.runtime.temporal import activities as acts
from openfactory.runtime.temporal.io import (
    CiRepairInput,
    HoldSyncInput,
    JobParams,
    MergeCheckInput,
    RunJobInput,
)
from openfactory.runtime.temporal.workflow import JobWorkflow
from tests.test_the_ado_forge import FX_ADO_REPO, REPO_ID, forge as ado_forge

ROOT = Path(__file__).resolve().parents[1]

# ═══ the table ══════════════════════════════════════════════════════════════════════════════════

LOG = "FAILED tests/test_export.py::test_it - AssertionError: 3 != 4"


def _check(name="build", bucket="fail", *, blocking=True, kind="code", evidence="", remedy="",
           url="") -> Check:
    return Check(name=name, bucket=bucket, blocking=blocking, kind=kind, evidence=evidence,
                 remedy=remedy, url=url)


@pytest.mark.parametrize("rows,action,verdict,why", [
    # THE CASE SEEN: an optional process policy rejected, nothing else. No repair, nobody asked.
    ([_check("Work item linking", blocking=False, kind="process")], WAIT, "none", ""),
    # a blocking process check: a person, never an agent
    ([_check("Work item linking", kind="process", remedy="Link a work item.")],
     ASK, "failure", "process"),
    # …even if a row hands a log in beside it: what it is ABOUT decides, not what came with it
    ([_check("Work item linking", kind="process", evidence=LOG)], ASK, "failure", "process"),
    # a blocking build, with its log: the one case an agent is for
    ([_check("build", evidence=LOG)], REPAIR, "failure", ""),
    # …and the same build with NO log: a repair would be a guess
    ([_check("build")], ASK, "failure", "no-evidence"),
    # a check the forge cannot classify is repaired only when there is a log to act on
    ([_check("ci/circle", kind="unknown", evidence=LOG)], REPAIR, "failure", ""),
    ([_check("license/cla", kind="unknown")], ASK, "failure", "no-evidence"),
    # an advisory check never changes the path, whatever is beside it
    ([_check("e2e", blocking=False), _check("build", bucket="pass")], WAIT, "success", ""),
    ([_check("e2e", blocking=False), _check("build", bucket="pending")], WAIT, "pending", ""),
    # `skip` is not a gate
    ([_check("docs", bucket="skip")], WAIT, "none", ""),
    ([], WAIT, "none", ""),
])
def test_the_table(rows, action, verdict, why):
    got = decide(rows)
    assert (got.action, got.verdict, got.why) == (action, verdict, why)


def test_what_the_factory_can_fix_is_fixed_before_a_person_is_asked():
    """A red build AND a rejected process policy: the repair costs the machine's time, the
    question a person's — so the person is asked once, afterwards, about what is still red."""
    got = decide([_check("Work item linking", kind="process", remedy="Link a work item."),
                  _check("build", evidence=LOG)])
    assert got.action == REPAIR and got.checks == ["build"] and LOG in got.evidence


def test_asking_names_the_check_and_carries_the_rows_own_remedy():
    got = decide([_check("Work item linking", kind="process",
                         remedy="Link a work item to the pull request.")])
    assert "'Work item linking'" in got.note
    assert "Link a work item to the pull request." in got.note
    assert got.checks == ["Work item linking"]


def test_a_failing_advisory_check_is_reported_and_not_acted_on():
    got = decide([_check("Work item linking", blocking=False, kind="process"),
                  _check("Comment requirements", bucket="pass", blocking=False, kind="process")])
    assert got.action == WAIT and got.advisory == ["Work item linking"]


def test_a_row_that_does_not_SAY_is_not_read_as_if_it_had():
    """A truthy non-bool is not `blocking: true` and a word outside the three is not a kind —
    and what is missing reads as the conservative side: blocking, unknown."""
    old = checks.from_row({"name": "ci", "bucket": "fail", "state": "FAILURE"})
    assert (old.blocking, old.kind) == (True, "unknown")
    odd = checks.from_row({"name": "ci", "bucket": "cancel", "blocking": "no", "kind": "policy"})
    assert (odd.blocking, odd.kind, odd.bucket) == (True, "unknown", "fail")
    assert checks.from_row("ci") is None


def test_the_table_names_no_forge():
    """The decision is the core's and the vocabulary is the rows'. Parsed, not grepped: string
    constants in the module's CODE (docstrings excluded — they tell the incident, by name)."""
    import ast

    tree = ast.parse((ROOT / "openfactory/contracts/checks.py").read_text())
    docstrings = {id(n.body[0].value) for n in ast.walk(tree)
                  if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef))
                  and n.body and isinstance(n.body[0], ast.Expr)
                  and isinstance(n.body[0].value, ast.Constant)}
    said = " ".join(n.value.lower() for n in ast.walk(tree)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)
                    and id(n) not in docstrings)
    for vendor in ("github", "azure", "gitlab", "work item", "isblocking"):
        assert vendor not in said, f"the core's table says {vendor!r}"


# ═══ Azure DevOps: its policies, mapped ═════════════════════════════════════════════════════════

BUILD = ("0609b952-1397-4640-95ec-e00a01b2c241", "Build")
WORK_ITEMS = ("40e92b44-2fe1-4dd6-b3d8-74a9c21d0c6e", "Work item linking")
COMMENTS = ("c6a1889d-b943-4856-b76f-9e46bb6b0df2", "Comment requirements")
STATUS = ("cbdc66da-9728-4af8-aada-9a5a32e4a226", "Status")

PR_OPEN = {"pullRequestId": 7, "status": "active", "mergeStatus": "succeeded",
           "sourceRefName": "refs/heads/openfactory/12", "targetRefName": "refs/heads/main",
           "repository": FX_ADO_REPO}
PR = "https://dev.azure.com/acme-ai/factory/_git/fx-ado/pullrequest/7"


def _evaluation(policy, status, *, blocking, build_id=None, name=""):
    """One `policy/evaluations` record, in the shape Azure DevOps documents for it."""
    type_id, shown = policy
    ev = {"status": status,
          "configuration": {"isEnabled": True, "isBlocking": blocking,
                            "type": {"id": type_id, "displayName": shown},
                            "settings": {"displayName": name} if name else {}}}
    if build_id:
        ev["context"] = {"buildId": build_id, "buildDefinitionName": name or "ci"}
    return ev


def _ado(evaluations, extra=None):
    return ado_forge({"GET git/pullrequests/7": PR_OPEN,
                      "GET policy/evaluations": {"value": evaluations}, **(extra or {})})


def test_ado_the_case_seen__optional_policies_and_no_build():
    """The reproduction, on the adapter: `none`, no repair, and NO build read at all — the fake
    raises on an unrouted route, and `build/builds` is not routed."""
    f = _ado([_evaluation(WORK_ITEMS, "rejected", blocking=False),
              _evaluation(COMMENTS, "approved", blocking=False)])

    assert f.pr_ci_status(pr=PR) == "none", "an optional policy is still read as a red gate"
    got = decide(checks.read(f, PR))
    assert (got.action, got.verdict) == (WAIT, "none")
    assert got.advisory == ["Work item linking"]
    rows = {r["name"]: r for r in f.pr_checks(pr=PR)}
    assert rows["Work item linking"]["blocking"] is False
    assert rows["Work item linking"]["kind"] == "process"


def test_ado_a_BLOCKING_work_item_policy_asks_a_person_with_its_remedy():
    """"Not the fix": reading `isBlocking` alone. A blocking work-item policy is red for a reason
    no agent can touch — it is asked about, with what to do, and no log is fetched for it."""
    f = _ado([_evaluation(WORK_ITEMS, "rejected", blocking=True)])

    assert f.pr_ci_status(pr=PR) == "failure"
    got = decide(checks.read(f, PR))
    assert (got.action, got.why) == (ASK, "process")
    assert "'Work item linking'" in got.note and "Link a work item" in got.note
    assert f.failed_ci_logs(pr=PR) == "", "a log was produced for a gate that is not a build"


def _build_routes(build_id, *, failed=True):
    record = {"name": "pytest", "result": "failed" if failed else "succeeded", "log": {"id": 9}}
    return {f"GET build/builds/{build_id}/timeline": {"records": [record]},
            f"GET build/builds/{build_id}/logs/9": {"count": 1, "value": [LOG]}}


def test_ado_a_failing_blocking_build_is_repaired_from_THAT_builds_log():
    """The verdict and the log come from the same rows: the build the red evaluation names
    (`context.buildId`) is the one whose timeline is read — a validation build runs on
    `refs/pull/7/merge`, where the old source-branch read never looked."""
    f = _ado([_evaluation(BUILD, "rejected", blocking=True, build_id=41, name="fx-ado-ci"),
              _evaluation(WORK_ITEMS, "rejected", blocking=False)], _build_routes(41))

    got = decide(checks.read(f, PR))
    assert got.action == REPAIR and got.checks == ["fx-ado-ci"]
    assert LOG in got.evidence
    assert "build/builds" not in f.fake.paths("GET"), "the branch's builds were listed anyway"
    row = next(r for r in f.pr_checks(pr=PR) if r["name"] == "fx-ado-ci")
    assert row["kind"] == "code" and row["url"].endswith("/_build/results?buildId=41")


def test_ado_a_failing_blocking_build_with_no_log_asks_and_says_so():
    f = _ado([_evaluation(BUILD, "rejected", blocking=True, build_id=41, name="fx-ado-ci")],
             _build_routes(41, failed=False))

    got = decide(checks.read(f, PR))
    assert (got.action, got.why) == (ASK, "no-evidence")
    assert "'fx-ado-ci'" in got.note and "buildId=41" in got.note


def test_ado_a_red_build_policy_that_names_no_build_looks_on_the_merge_ref_first():
    f = _ado([_evaluation(BUILD, "rejected", blocking=True)],
             {"GET git/repositories/fx-ado": FX_ADO_REPO,
              "GET build/builds": lambda params: {"value": (
                  [{"id": 52, "status": "completed", "result": "failed"}]
                  if params["branchName"] == "refs/pull/7/merge" else [])},
              **_build_routes(52)})

    assert LOG in f.failed_ci_logs(pr=PR)
    asked = [q["branchName"] for m, p, _b, q in f.fake.calls if p == "build/builds"]
    assert asked == ["refs/pull/7/merge"] and REPO_ID


def test_ado_a_status_policy_does_not_claim_to_know_what_it_is():
    f = _ado([_evaluation(STATUS, "rejected", blocking=True, name="license/cla")])
    assert f.pr_checks(pr=PR)[0]["kind"] == "unknown"
    assert decide(checks.read(f, PR)).why == "no-evidence"


# ═══ GitHub: required or not, a workflow of this repository or somebody's status ════════════════

GH_PR = "https://github.com/acme/x/pull/2"


def _github(monkeypatch, all_checks, required, *, runs=(), log=""):
    """A `GitHubForge` whose `gh` answers from these rows. `required` is the names `--required`
    lists, or None for a repository with workflows and no branch protection (F-02)."""
    f = GitHubForge("acme/x")
    calls: list[list[str]] = []

    def gh(args, timeout=120):
        calls.append(args)
        out = SimpleNamespace(returncode=0, stdout="", stderr="")
        if args[:2] == ["pr", "checks"]:
            if "--required" in args:
                if required is None:
                    out.returncode, out.stderr = 8, "no required checks reported on the branch"
                else:
                    out.stdout = json.dumps([{"name": n, "bucket": "fail"} for n in required])
            else:
                out.stdout = json.dumps(all_checks)
        elif args[:2] == ["pr", "view"]:
            out.stdout = json.dumps({"headRefName": "openfactory/12"})
        elif args[:2] == ["run", "list"]:
            out.stdout = json.dumps(list(runs))
        elif args[:2] == ["run", "view"]:
            out.stdout = log
        return out

    monkeypatch.setattr(f, "_gh", gh)
    f.calls = calls
    return f


def _gh_row(name, bucket, *, workflow="", link=""):
    return {"name": name, "bucket": bucket, "state": bucket.upper(), "workflow": workflow,
            "link": link}


def test_github_an_advisory_check_failing_changes_nothing(monkeypatch):
    f = _github(monkeypatch, [_gh_row("e2e", "fail", workflow="e2e"),
                              _gh_row("lint", "pass", workflow="ci")], ["lint"])
    got = decide(checks.read(f, GH_PR))
    assert (got.action, got.verdict, got.advisory) == (WAIT, "success", ["e2e"])
    assert not [c for c in f.calls if c[:2] == ["run", "list"]], "logs were fetched for nothing"


def test_github_no_branch_protection_means_every_row_is_advisory(monkeypatch):
    """F-02, said per row: workflows exist, nothing is required, nothing gates the merge."""
    f = _github(monkeypatch, [_gh_row("pytest", "fail", workflow="ci")], None)
    assert [r["blocking"] for r in f.pr_checks(pr=GH_PR)] == [False]
    assert decide(checks.read(f, GH_PR)).verdict == "none"


def test_github_a_required_workflow_failing_is_repaired_from_its_log(monkeypatch):
    f = _github(monkeypatch, [_gh_row("pytest", "fail", workflow="ci", link="https://x/run/1")],
                ["pytest"], runs=[{"databaseId": 1, "conclusion": "failure"}], log=LOG)
    got = decide(checks.read(f, GH_PR))
    assert got.action == REPAIR and LOG in got.evidence


def test_github_a_required_status_from_another_app_is_asked_about_not_repaired(monkeypatch):
    """A required CLA/DCO status read the same as a failing test. It has no workflow run, so there
    is no log — and the row says `unknown` rather than claiming it is about the code."""
    f = _github(monkeypatch, [_gh_row("license/cla", "fail", link="https://cla.example/2")],
                ["license/cla"])
    assert f.pr_checks(pr=GH_PR)[0]["kind"] == "unknown"
    got = decide(checks.read(f, GH_PR))
    assert (got.action, got.why) == (ASK, "no-evidence")
    assert "'license/cla'" in got.note and "https://cla.example/2" in got.note


def test_github_an_unreadable_answer_raises_instead_of_reading_as_no_checks(monkeypatch):
    f = GitHubForge("acme/x")
    monkeypatch.setattr(f, "_gh", lambda args, timeout=120: SimpleNamespace(
        returncode=1, stdout="", stderr="API rate limit exceeded"))
    with pytest.raises(RuntimeError, match="gh pr checks failed"):
        checks.read(f, GH_PR)


# ═══ the local forge, and a row that has never heard of this ════════════════════════════════════

def test_the_local_forge_says_nothing_gates_the_merge_from_its_rows(tmp_path):
    f = LocalForge("p", str(tmp_path), db_path=tmp_path / "board.db")
    f.pr_ci_status = lambda **_kw: pytest.fail("a typed forge was asked for its aggregate")
    assert checks.read(f, "1") == [] and decide([]).verdict == "none"


class _OldAddon:
    """A forge written against the port as it was: the aggregate, the log, `{name, bucket,
    state}` rows — and no `checks_are_typed`."""

    def __init__(self, verdict, log="", rows=()):
        self.verdict, self.log, self.rows = verdict, log, list(rows)

    def pr_ci_status(self, *, pr):
        return self.verdict

    def failed_ci_logs(self, *, pr):
        return self.log

    def pr_checks(self, *, pr):
        return self.rows


def test_an_addon_that_only_answers_the_aggregate_keeps_working__and_is_never_repaired_blind():
    red = [{"name": "unit", "bucket": "fail", "state": "failed"},
           {"name": "docs", "bucket": "pass", "state": "ok"}]
    with_log = decide(checks.read(_OldAddon("failure", LOG, red), "1"))
    assert with_log.action == REPAIR and with_log.checks == ["unit"]

    blind = decide(checks.read(_OldAddon("failure", "", red), "1"))
    assert (blind.action, blind.why) == (ASK, "no-evidence") and "'unit'" in blind.note

    assert decide(checks.read(_OldAddon("none"), "1")).verdict == "none"
    assert decide(checks.read(_OldAddon("success"), "1")).verdict == "success"
    # `tests/stranger_addon.py` answers a word outside the port's four: unread, so it waits.
    assert decide(checks.read(_OldAddon("unknown"), "1")).verdict == "pending"


def test_a_test_double_is_not_a_declaration():
    assert checks.declares_typed_checks(MagicMock()) is False
    assert checks.declares_typed_checks(GitHubForge("acme/x")) is True


# ═══ the activity: nothing is launched unless the table says repair ═════════════════════════════

class _Forge:
    checks_are_typed = True

    def __init__(self, rows, log=""):
        self.rows, self.log = rows, log

    def pr_checks(self, *, pr):
        return self.rows

    def failed_ci_logs(self, *, pr):
        return self.log


@pytest.fixture
def worker_side(monkeypatch):
    """The worker's seams: a project, its forge, and a runner that records being built."""
    built: list[tuple] = []
    project = SimpleNamespace(name="p")
    monkeypatch.setattr(acts, "ProjectRegistry", lambda: SimpleNamespace(get=lambda _n: project))
    monkeypatch.setattr(acts, "_ref_repo", lambda _p, _i: ("acme/x", ""))
    monkeypatch.setattr(acts, "_runner_view", lambda _p, _i: (project, ""))
    monkeypatch.setattr(acts, "_resolved_image", lambda _p, sandbox: "")
    monkeypatch.setattr(acts, "installed_box_traits",
                        lambda _s: SimpleNamespace(remote=False))
    monkeypatch.setattr(acts.time, "sleep", lambda _s: None)

    def runner(*a, **kw):
        def repair_ci(issue, ci_log, pr_url=""):
            built.append((issue, ci_log))
            return RunResult(ticket_id=issue, state=JobState.PR_OPEN, pr_url=pr_url)
        return SimpleNamespace(repair_ci=repair_ci)

    monkeypatch.setattr(acts, "build_runner", runner)

    def use(forge):
        monkeypatch.setattr(acts, "_forge_for", lambda _p: forge)
        return built
    return use


REPAIR_INPUT = CiRepairInput(project="p", issue="12", pr_url=PR, sandbox="worktree")


def test_the_repair_launches_nothing_for_a_check_only_a_person_settles(worker_side):
    built = worker_side(_Forge([{"name": "Work item linking", "bucket": "fail", "blocking": True,
                                 "kind": "process", "remedy": "Link a work item."}]))
    got = acts._run_ci_repair(REPAIR_INPUT)  # noqa: SLF001 — the activity's own body
    assert built == [], "an agent was launched at a policy no code change can satisfy"
    assert got.state == JobState.ON_HOLD and got.merge_refused is True
    assert "'Work item linking'" in got.note and "Link a work item." in got.note


def test_the_repair_launches_nothing_without_a_failure_log(worker_side):
    built = worker_side(_Forge([{"name": "build", "bucket": "fail", "blocking": True,
                                 "kind": "code"}], log=""))
    got = acts._run_ci_repair(REPAIR_INPUT)  # noqa: SLF001
    assert built == [] and got.state == JobState.ON_HOLD
    assert "no failure log" in got.note


def test_the_repair_runs_with_the_log_the_decision_was_made_from(worker_side):
    built = worker_side(_Forge([{"name": "build", "bucket": "fail", "blocking": True,
                                 "kind": "code"}], log=LOG))
    acts._run_ci_repair(REPAIR_INPUT)  # noqa: SLF001
    assert built == [("12", LOG)]


def test_the_repair_goes_back_to_watching_when_nothing_blocking_is_red_any_more(worker_side):
    built = worker_side(_Forge([{"name": "Work item linking", "bucket": "fail",
                                 "blocking": False, "kind": "process"}]))
    got = acts._run_ci_repair(REPAIR_INPUT)  # noqa: SLF001
    assert built == [] and got.state == JobState.PR_OPEN and got.code_changed is False


def test_an_unreadable_forge_is_held_and_says_so__not_repaired_blind(worker_side):
    class Down(_Forge):
        def pr_checks(self, *, pr):
            raise RuntimeError("503 from the forge")

    built = worker_side(Down([]))
    got = acts._run_ci_repair(REPAIR_INPUT)  # noqa: SLF001
    assert built == [] and got.state == JobState.ON_HOLD and "503 from the forge" in got.note


def test_a_persons_adjust_is_not_asked_about_ci(worker_side):
    """The human path hands prose in, and a green pull request has no red check to find."""
    built = worker_side(_Forge([]))
    acts._run_ci_repair(REPAIR_INPUT, ci_log="make the button blue")  # noqa: SLF001
    assert built == [("12", "make the button blue")]


async def test_the_old_activity_answers_from_the_same_table(worker_side):
    """Jobs already in the watch replay `check_ci_status` by name — and stop reading an optional
    policy as a red build too."""
    worker_side(_Forge([{"name": "Work item linking", "bucket": "fail", "blocking": False,
                         "kind": "process"}]))
    assert await acts.check_ci_status(MergeCheckInput(project="p", pr_url=PR)) == "none"


# ═══ the watch: the real workflow, on a real engine ═════════════════════════════════════════════

TQ = "test-checks-are-read"

#: What the table answers, in order; the last one repeats. Set per test.
_READS: list[CiDecision] = []
_REPAIRS: list[CiRepairInput] = []
_RUNS: list[RunJobInput] = []
_LEGACY: list[str] = []
#: how many status polls say "open" before the pull request lands
_OPEN_FOR = [0]
_POLLS = [0]


@activity.defn(name="run_job")
async def mock_run_job(inp: RunJobInput) -> RunResult:
    _RUNS.append(inp)
    return RunResult(ticket_id=inp.issue, state=JobState.PR_OPEN, pr_url="https://x/pr/1",
                     branch="openfactory/12")


@activity.defn(name="check_pr_status")
async def mock_status(inp: MergeCheckInput) -> str:
    _POLLS[0] += 1
    return "open" if _POLLS[0] <= _OPEN_FOR[0] else "merged"


@activity.defn(name="read_ci_checks")
async def mock_read(inp: MergeCheckInput) -> CiDecision:
    return _READS.pop(0) if len(_READS) > 1 else _READS[0]


@activity.defn(name="check_ci_status")
async def mock_legacy(inp: MergeCheckInput) -> str:
    _LEGACY.append(inp.pr_url)
    return "pending"


@activity.defn(name="repair_ci")
async def mock_repair(inp: CiRepairInput) -> RunResult:
    _REPAIRS.append(inp)
    return RunResult(ticket_id=inp.issue, state=JobState.PR_OPEN, pr_url=inp.pr_url)


@activity.defn(name="pr_mergeable_state")
async def mock_blocked(inp: MergeCheckInput) -> str:
    return "blocked"


@activity.defn(name="settle_ticket")
async def mock_settle(inp: HoldSyncInput) -> str:
    return inp.state


@activity.defn(name="mark_needs_action")
async def mock_mark(inp: HoldSyncInput) -> str:
    return "somebody"


@activity.defn(name="diagnose_impediment")
async def mock_diagnose(inp: HoldSyncInput) -> bool:
    return False


@activity.defn(name="fetch_ticket_title")
async def mock_title(inp) -> str:
    return "a ticket"


@activity.defn(name="refresh_knowledge")
async def mock_refresh(inp) -> str:
    return "published"


@activity.defn(name="notify_coordinator_say")
async def mock_say(inp) -> None:
    return None


@activity.defn(name="notify_coordinator")
async def mock_notify(inp) -> None:
    return None


MOCKS = [mock_run_job, mock_status, mock_read, mock_legacy, mock_repair, mock_blocked,
         mock_settle, mock_mark, mock_diagnose, mock_title, mock_refresh, mock_say, mock_notify]

#: THIS FILE STARTS ITS OWN ENGINE and throws it away — the declared exception to the suite's
#: no-live-engine rule (`conftest.OWNS_ITS_ENGINE`). Marked per test: most of this file needs none.
engine = pytest.mark.owns_its_engine


@pytest.fixture
async def env():
    e = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
    try:
        yield e
    finally:
        await e.shutdown()


def _reset(*reads: CiDecision, open_for: int) -> None:
    _READS[:] = list(reads)
    _REPAIRS.clear(), _RUNS.clear(), _LEGACY.clear()
    _OPEN_FOR[0], _POLLS[0] = open_for, 0


async def _start(client: Client) -> WorkflowHandle:
    return await client.start_workflow(
        JobWorkflow.run,
        JobParams(project="p", issue="12", promote=False, merge_deadline_days=3650),
        id=f"wf-{uuid.uuid4()}", task_queue=TQ)


async def _wait_for_park(h: WorkflowHandle, env: WorkflowEnvironment) -> dict:
    for _ in range(60):
        parked = await h.query(JobWorkflow.awaiting_action)
        if parked:
            return parked
        await env.sleep(timedelta(seconds=1))
    raise AssertionError("the job never asked a person about the check")


ADVISORY_ONLY = CiDecision(verdict="none", action=WAIT, advisory=["Work item linking"])
ASK_PROCESS = decide([_check("Work item linking", kind="process", remedy="Link a work item.")])
RED_BUILD = decide([_check("build", evidence=LOG)])
GREEN = CiDecision(verdict="success", action=WAIT)


@engine
async def test_the_case_seen__no_repair_and_the_watch_keeps_waiting_for_the_merge(env):
    """ACCEPTANCE 1. A rejected non-blocking policy and no builds: the watch polls on, no agent
    runs, the pull request lands when a person merges it."""
    _reset(ADVISORY_ONLY, open_for=3)
    async with Worker(env.client, task_queue=TQ, workflows=[JobWorkflow], activities=MOCKS):
        result = await (await _start(env.client)).result()

    assert result.state == JobState.MERGED
    assert _REPAIRS == [], f"{len(_REPAIRS)} repair pass(es) ran on an advisory policy"
    assert _LEGACY == [], "a new job still reads the one-word aggregate"


@engine
async def test_a_blocking_process_check_asks_a_person_and_no_agent_runs(env):
    """ACCEPTANCE 2. The card parks with the policy's name and remedy; the answer goes back to
    reading the checks — and the agent runs exactly once in the whole job."""
    _reset(ASK_PROCESS, GREEN, open_for=1)
    async with Worker(env.client, task_queue=TQ, workflows=[JobWorkflow], activities=MOCKS):
        h = await _start(env.client)
        parked = await _wait_for_park(h, env)
        assert "'Work item linking'" in parked["note"] and "Link a work item." in parked["note"]
        keys = [o["key"] for o in parked["decision"]["options"]]
        assert keys == ["resume", "skip"]
        assert await h.query(JobWorkflow.awaiting_merge) is None, (
            "a merge gate is still offered on a job that is asking about a check")

        await h.signal(JobWorkflow.act_on_impediment, args=["resume", "resume"])
        result = await h.result()

    assert result.state == JobState.MERGED
    assert _REPAIRS == [] and len(_RUNS) == 1


@engine
async def test_skipping_the_question_frees_the_floor(env):
    _reset(ASK_PROCESS, open_for=99)
    async with Worker(env.client, task_queue=TQ, workflows=[JobWorkflow], activities=MOCKS):
        h = await _start(env.client)
        await _wait_for_park(h, env)
        await h.signal(JobWorkflow.act_on_impediment, args=["skip", "skip"])
        result = await h.result()
    assert result.state != JobState.MERGED and _REPAIRS == []


@engine
async def test_a_failing_blocking_build_with_its_log_gets_one_repair(env):
    """ACCEPTANCE 3."""
    _reset(RED_BUILD, GREEN, open_for=1)
    async with Worker(env.client, task_queue=TQ, workflows=[JobWorkflow], activities=MOCKS):
        result = await (await _start(env.client)).result()
    assert result.state == JobState.MERGED and len(_REPAIRS) == 1


@engine
async def test_a_hold_the_repair_itself_returned_resumes_into_the_watch(env):
    """The checks moved between the watch's read and the repair's: the repair launched nothing
    and handed back a hold with the mark. A resume re-enters the MERGE watch — one agent pass in
    the whole job, not two."""
    _reset(RED_BUILD, GREEN, open_for=1)

    @activity.defn(name="repair_ci")
    async def held(inp: CiRepairInput) -> RunResult:
        return RunResult(ticket_id=inp.issue, state=JobState.ON_HOLD, pr_url=inp.pr_url,
                         merge_refused=True, note="'Work item linking' must pass …")

    mocks = [m for m in MOCKS if m is not mock_repair] + [held]
    async with Worker(env.client, task_queue=TQ, workflows=[JobWorkflow], activities=mocks):
        h = await _start(env.client)
        await _wait_for_park(h, env)
        await h.signal(JobWorkflow.act_on_impediment, args=["resume", ""])
        result = await h.result()
    assert result.state == JobState.MERGED and len(_RUNS) == 1


# ── jobs already in the watch replay what they recorded ─────────────────────────────────────────

MARKER = "checks-are-read-for-what-they-are"


def _patched_as(monkeypatch, answer: bool):
    """`workflow.patched`, answering `answer` for THIS marker and the truth for every other.
    `temporalio` is passed through the workflow sandbox, so the workflow sees this one."""
    from temporalio import workflow as tw

    real = tw.patched
    monkeypatch.setattr(tw, "patched", lambda name: answer if name == MARKER else real(name))


@engine
async def test_a_job_recorded_BEFORE_the_marker_replays_on_this_code(env, monkeypatch):
    """A history with no marker is what a job already in the watch carries. Recorded by running
    the arm `patched()` selects for it, then replayed through the real `patched()`: it answers
    False on a history without its marker, and the old activity is what the engine is handed."""
    _reset(ADVISORY_ONLY, open_for=2)
    with monkeypatch.context() as m:
        _patched_as(m, False)
        async with Worker(env.client, task_queue=TQ, workflows=[JobWorkflow], activities=MOCKS):
            h = await _start(env.client)
            assert (await h.result()).state == JobState.MERGED
        history = await h.fetch_history()
    assert _LEGACY, "the recording did not take the pre-marker arm it claims to be"

    await Replayer(workflows=[JobWorkflow],
                   data_converter=pydantic_data_converter).replay_workflow(history)

    # VERIFY THE VERIFIER: the same history through the new arm is a non-deterministic replay,
    # so the green replay above is the marker working and not a replayer that cannot tell.
    _patched_as(monkeypatch, True)
    with pytest.raises(Exception) as caught:
        await Replayer(workflows=[JobWorkflow],
                       data_converter=pydantic_data_converter).replay_workflow(history)
    assert "determinis" in str(caught.value).lower() or "TMPRL1100" in str(caught.value), (
        f"the ungated replay failed for another reason: {caught.value!r}")


# ═══ the panel ══════════════════════════════════════════════════════════════════════════════════

def test_the_panels_rows_say_which_checks_are_advisory():
    rows = checks.as_rows([checks.from_row({"name": "Work item linking", "bucket": "fail",
                                            "blocking": False, "kind": "process",
                                            "evidence": "never sent to a browser"})])
    assert rows[0]["advisory"] is True and "evidence" not in rows[0]


async def test_the_job_detail_reads_the_rows_the_way_the_watch_does(monkeypatch):
    """The panel's own reader (`view._pr_checks`), over a forge answering the case seen."""
    from openfactory.runtime.temporal import view

    forge = _Forge([{"name": "Work item linking", "bucket": "fail", "state": "rejected",
                     "blocking": False, "kind": "process"}])
    monkeypatch.setattr("openfactory.registry.ProjectRegistry",
                        lambda: SimpleNamespace(get=lambda _n: SimpleNamespace(name="p")))
    monkeypatch.setattr("openfactory.credentials.forge_token_for", lambda _p: "tok")
    monkeypatch.setattr("openfactory.adapters.forge.registry.build_forge", lambda *a, **kw: forge)

    rows = await view._pr_checks("p", PR)  # noqa: SLF001 — the reader the detail view calls
    assert rows == [{"name": "Work item linking", "bucket": "fail", "state": "rejected",
                     "blocking": False, "advisory": True, "kind": "process", "url": "",
                     "remedy": ""}]


def test_the_panel_does_not_draw_an_advisory_check_as_a_red_gate():
    """Executed, not read: the page's own `_ciChips`, fed one advisory and one blocking row."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on PATH")
    page = (ROOT / "openfactory/api/panel.html").read_text()
    consts = re.search(r"const _CIB=[^\n]*\n", page)
    body = page[page.index("function _ciChips("):page.index("\nfunction _sev(")]
    rows = [{"name": "Work item linking", "bucket": "fail", "advisory": True, "kind": "process"},
            {"name": "build", "bucket": "fail", "advisory": False, "kind": "code"}]
    script = ("const esc=s=>String(s);\n" + consts.group(0) + body
              + f"\nconsole.log(JSON.stringify(_ciChips({json.dumps(rows)}).split('</span>')));")
    got = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60)
    assert got.returncode == 0, got.stderr[:400]
    advisory, blocking = json.loads(got.stdout)[:2]
    assert "b-err" not in advisory and "advisory" in advisory
    assert "b-err" in blocking and "advisory" not in blocking
