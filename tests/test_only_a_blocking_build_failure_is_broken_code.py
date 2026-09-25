"""#184 — only a blocking build failure is broken code; everything else is said, waited on, or asked.

WHAT WAS STILL TRUE AFTER THE TABLE LANDED. `contracts/checks.py::decide` stopped a rejected
OPTIONAL policy from starting a repair, but the port still had one word for two opposite facts and
one log for every red check:

    "none"   meant BOTH "nothing ran on this pull request" and "checks ran, and none of them can
             stop the merge". So the case #184 was found on — a PR one second old, no build, two
             optional policies evaluated — read exactly like a PR nothing had looked at, and the
             one that nothing had looked at read like a green one: the machine's own self-merge
             fired on it, past a forge that had verified nothing.
    the log  `failed_ci_logs` was attached to EVERY blocking red check that could be about code,
             `unknown` ones included. On GitHub it was every failed run on the branch — so a
             required commit STATUS (a Prow job, a CLA bot) red beside some unrelated failed
             workflow was "repaired" from that workflow's log: a blind repair with a log in hand.
    ADO      `mergeable_state` answered `unstable` for a red BLOCKING policy — the word the watch's
             self-heal merges on, with `bypassPolicy` set.
    the card an advisory failure was drawn as a dim chip on the job detail and said nowhere on the
             card a person reads.

WHAT THE PORT SAYS NOW, and every row says it the same way:

    failure    a check that BLOCKS the merge failed — the rows say whether it is a build with a
               log (repaired) or something a person settles (asked)
    advisory   checks ran, and not one of them can stop the merge — said on the card, never acted on
    none       nothing ran — waited on for ten minutes, then said; never merged by the machine
    pending    a blocking check is still running
    success    every blocking check passed

The shapes: Azure DevOps records in Microsoft's documented `PolicyEvaluationRecord` shape, carrying
the values the issue reports from the live deployment (no Azure credential here to record one);
GitHub rows RECORDED with this repository's own `gh pr checks --json name,bucket,state,link,workflow`
against public pull requests on 2026-09-24, trimmed to the rows each case needs and marked where a
row was turned red by hand.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from temporalio import activity
from temporalio.client import Client, WorkflowHandle
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from openfactory.adapters.forge.github import GitHubForge
from openfactory.adapters.forge.local import LocalForge
from openfactory.contracts import JobState, RunResult, checks
from openfactory.contracts.checks import (
    ASK,
    REPAIR,
    WAIT,
    Check,
    CiDecision,
    decide,
    declares_no_checks,
    nothing_ran_note,
)
from openfactory.runtime.temporal.io import (
    CiRepairInput,
    HoldSyncInput,
    JobParams,
    MergeCheckInput,
    RunJobInput,
)
from openfactory.runtime.temporal.workflow import JobWorkflow
from tests.test_the_ado_forge import FX_ADO_REPO, PROJECT_ID, REPO_ID
from tests.test_the_ado_forge import forge as ado_forge

LOG = "FAILED tests/test_export.py::test_it - AssertionError: 3 != 4"

# ═══ the table: five words for four cases ═══════════════════════════════════════════════════════


def _check(name, bucket="fail", *, blocking=True, kind="code", evidence="") -> Check:
    return Check(name=name, bucket=bucket, blocking=blocking, kind=kind, evidence=evidence)


@pytest.mark.parametrize("rows,verdict,action", [
    # NOTHING RAN: no row at all, or only optional rows the forge skipped
    ([], "none", WAIT),
    ([_check("docs", bucket="skip", blocking=False)], "none", WAIT),
    # EVERY BLOCKING CHECK SKIPPED BY THE REPOSITORY'S OWN RULES (a path filter): satisfied, as
    # branch protection reads it, and not a pull request nothing was asked of (review of #320)
    ([_check("e2e", bucket="skip"), _check("docs", bucket="skip", blocking=False)],
     "success", WAIT),
    # CHECKS RAN AND NONE OF THEM GATES THE MERGE — the case #184 was found on
    ([_check("Work item linking", blocking=False, kind="process"),
      _check("Comment requirements", bucket="pass", blocking=False, kind="process")],
     "advisory", WAIT),
    ([_check("e2e", bucket="pass", blocking=False)], "advisory", WAIT),
    # STILL RUNNING
    ([_check("build", bucket="pending"), _check("e2e", blocking=False)], "pending", WAIT),
    # A BLOCKING FAILURE: repaired only with the build's own log, asked otherwise
    ([_check("build", evidence=LOG)], "failure", REPAIR),
    ([_check("build")], "failure", ASK),
    ([_check("Work item linking", kind="process")], "failure", ASK),
    # green gates beside a red advisory one
    ([_check("build", bucket="pass"), _check("e2e", blocking=False)], "success", WAIT),
])
def test_nothing_ran_and_nothing_gates_are_two_answers(rows, verdict, action):
    got = decide(rows)
    assert (got.verdict, got.action) == (verdict, action)


def test_the_advisory_names_travel_with_the_answer():
    got = decide([_check("Work item linking", blocking=False, kind="process"),
                  _check("build", bucket="pass")])
    assert got.advisory == ["Work item linking"] and got.action == WAIT


class _OldAddon:
    """A forge written against the port's aggregate only — no `checks_are_typed`."""

    def __init__(self, verdict):
        self.verdict = verdict

    def pr_ci_status(self, *, pr):
        return self.verdict

    def failed_ci_logs(self, *, pr):
        return ""

    def pr_checks(self, *, pr):
        return []


@pytest.mark.parametrize("verdict", ["advisory", "none", "pending", "success"])
def test_a_row_that_only_answers_the_aggregate_is_read_in_the_same_five_words(verdict):
    """The port's new word reaches the core from a row that has nothing else to say: `advisory`
    is not a word outside the port (which would read as an unreadable gate, and wait)."""
    assert decide(checks.read(_OldAddon(verdict), "1")).verdict == verdict


# ═══ Azure DevOps ═══════════════════════════════════════════════════════════════════════════════

BUILD = ("0609b952-1397-4640-95ec-e00a01b2c241", "Build")
WORK_ITEMS = ("40e92b44-2fe1-4dd6-b3d8-74a9c21d0c6e", "Work item linking")
COMMENTS = ("c6a1889d-b943-4856-b76f-9e46bb6b0df2", "Comment requirements")
STATUS = ("cbdc66da-9728-4af8-aada-9a5a32e4a226", "Status")

PR_OPEN = {"pullRequestId": 7, "status": "active", "mergeStatus": "succeeded",
           "sourceRefName": "refs/heads/openfactory/12", "targetRefName": "refs/heads/main",
           "repository": FX_ADO_REPO}
PR = "https://dev.azure.com/acme-ai/factory/_git/fx-ado/pullrequest/7"


def _record(policy, status, *, blocking, build_id=None, name="", config_id=1):
    """One `policy/evaluations` record in Microsoft's documented `PolicyEvaluationRecord` shape
    (Policy Evaluations — List, api-version 7.1-preview.1). The values are the issue's: the PR
    opened at 22:27:52 and was evaluated in the same second."""
    type_id, shown = policy
    done = status not in ("queued", "running")
    rec = {
        "artifactId": f"vstfs:///CodeReview/CodeReviewId/{PROJECT_ID}/7",
        "evaluationId": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{type_id}/{config_id}")),
        "startedDate": "2026-09-18T22:27:52.183Z",
        "completedDate": "2026-09-18T22:27:52.457Z" if done else None,
        "status": status,
        "context": None,
        "configuration": {
            "id": config_id, "revision": 1, "isEnabled": True, "isBlocking": blocking,
            "isDeleted": False, "isEnterpriseManaged": False,
            "type": {"id": type_id, "displayName": shown,
                     "url": f"https://dev.azure.com/acme-ai/{PROJECT_ID}/_apis/policy/types/"
                            f"{type_id}"},
            "settings": {"scope": [{"refName": "refs/heads/main", "matchKind": "Exact",
                                    "repositoryId": REPO_ID}]},
        },
    }
    if name:
        rec["configuration"]["settings"]["displayName"] = name
    if build_id:
        rec["context"] = {"buildId": build_id, "buildDefinitionId": 5,
                          "buildDefinitionName": name or "ci", "buildIsNotCurrent": False,
                          "buildStartedUtc": "2026-09-18T22:27:53.001Z", "isExpired": False,
                          "wasAutoRequeued": False}
    return rec


#: THE CASE SEEN: two OPTIONAL policies, one rejected because that team links no work items, and
#: no build on the source branch or the merge ref.
CASE_SEEN = [_record(WORK_ITEMS, "rejected", blocking=False, config_id=1),
             _record(COMMENTS, "approved", blocking=False, config_id=2)]


def _build_routes(build_id, *, failed=True):
    record = {"name": "pytest", "result": "failed" if failed else "succeeded", "log": {"id": 9}}
    return {f"GET build/builds/{build_id}/timeline": {"records": [record]},
            f"GET build/builds/{build_id}/logs/9": {"count": 1, "value": [LOG]}}


def _ado(evaluations, extra=None):
    return ado_forge({"GET git/pullrequests/7": PR_OPEN,
                      "GET policy/evaluations": {"value": evaluations}, **(extra or {})})


RED_BUILD = _record(BUILD, "rejected", blocking=True, build_id=41, name="fx-ado-ci", config_id=3)


@pytest.mark.parametrize("evaluations,verdict", [
    ([], "none"),
    # a blocking policy whose path filter this diff does not match: satisfied (review of #320)
    ([_record(BUILD, "notApplicable", blocking=True, config_id=3)], "success"),
    ([_record(WORK_ITEMS, "notApplicable", blocking=False, config_id=1)], "none"),
    (CASE_SEEN, "advisory"),
    (CASE_SEEN + [_record(BUILD, "queued", blocking=True, build_id=41, config_id=3)],
     "pending"),
    (CASE_SEEN + [_record(BUILD, "approved", blocking=True, build_id=41, config_id=3)],
     "success"),
    (CASE_SEEN + [RED_BUILD], "failure"),
    ([_record(WORK_ITEMS, "rejected", blocking=True)], "failure"),
])
def test_ado_says_which_of_the_four_cases_and_the_table_agrees(evaluations, verdict):
    """The port's word and the core's reading of the rows are the SAME word for the same facts —
    a summary that disagrees with its own detail is a panel somebody spends an afternoon on."""
    f = _ado(evaluations, _build_routes(41))
    assert f.pr_ci_status(pr=PR) == verdict
    assert decide(checks.read(f, PR)).verdict == verdict


def test_ado_the_case_seen_is_advisory__not_nothing():
    f = _ado(CASE_SEEN)
    got = decide(checks.read(f, PR))
    assert (got.verdict, got.action, got.advisory) == ("advisory", WAIT, ["Work item linking"])
    assert "build/builds" not in f.fake.paths("GET"), "a build was looked for on a policy"


@pytest.mark.parametrize("evaluations", [
    [RED_BUILD],
    CASE_SEEN + [RED_BUILD],
    [_record(WORK_ITEMS, "rejected", blocking=True)],
])
def test_ado_a_red_BLOCKING_policy_is_never_offered_to_the_self_merge(evaluations):
    """`clean` and `unstable` are the two words the merge watch's self-heal merges on, and on
    this forge it merges with `bypassPolicy`. A policy that blocks and is red is `blocked`."""
    assert _ado(evaluations, _build_routes(41)).mergeable_state(pr=PR) == "blocked"


def test_ado_only_optional_policies_red_is_still_mergeable():
    assert _ado(CASE_SEEN).mergeable_state(pr=PR) == "clean"


def test_ado_a_builds_log_is_evidence_about_that_build_and_nothing_else():
    """A status some other service posted (`unknown`) is red beside a red build. The log is the
    BUILD's: read into the build's row, and not into the status's — which is then asked about,
    once the build is repaired, instead of being "fixed" from a log that never described it."""
    f = _ado([_record(STATUS, "rejected", blocking=True, name="license/cla", config_id=4),
              RED_BUILD], _build_routes(41))
    got = {c.name: c for c in checks.read(f, PR)}
    assert LOG in got["fx-ado-ci"].evidence
    assert got["license/cla"].evidence == "", "the build's log was handed in as the status's"
    assert decide(list(got.values())).checks == ["fx-ado-ci"]


# ═══ GitHub ═════════════════════════════════════════════════════════════════════════════════════

FIELDS = ("name", "bucket", "state", "link", "workflow")


def _rows(*rows):
    return [dict(zip(FIELDS, r, strict=True)) for r in rows]


#: cli/cli#14474, recorded 2026-09-24: workflows RAN (three of its twelve rows), and the branch
#: requires none of them — `--required` answers with gh's sentence and no JSON.
CLI_14474 = {
    "all": _rows(
        ("close-from-default-branch", "skipping", "SKIPPED",
         "https://github.com/cli/cli/actions/runs/35727536539/job/106744833087", "PR Triaging"),
        ("label-external / label_issues", "pass", "SUCCESS",
         "https://github.com/cli/cli/actions/runs/35403472514/job/105788209802", "PR Triaging"),
        ("check-requirements", "skipping", "SKIPPED",
         "https://github.com/cli/cli/actions/runs/35727536539/job/106744816935", "PR Triaging")),
    "required": "no required checks reported on the 'remove-claude-md' branch",
}

#: The same recording, its SKIPPED rows only: every check the forge reported, it skipped.
CLI_14474_SKIPPED = {"all": [r for r in CLI_14474["all"] if r["bucket"] == "skipping"],
                     "required": CLI_14474["required"]}

#: The same skipped rows, on a branch that REQUIRES both: a path filter left them out of this diff.
#: GitHub's branch protection reads a skipped required check as satisfied and says `clean`.
CLI_14474_REQUIRED_SKIPPED = {"all": CLI_14474_SKIPPED["all"],
                              "required": ["close-from-default-branch", "check-requirements"]}

#: kubernetes/kubernetes#142359, recorded 2026-09-24: every check is a commit STATUS (Prow, the
#: EasyCLA bot) — `workflow` empty, the link wherever the posting app points. A REQUIRED status is
#: red: a real build, run by a CI this forge cannot read a log from.
K8S_142359 = {
    "all": _rows(
        ("pull-kubernetes-integration", "fail", "FAILURE",
         "https://prow.k8s.io/view/gs/kubernetes-ci-logs/pr-logs/pull/142359/"
         "pull-kubernetes-integration/2102857020058112000", ""),
        ("tide", "pending", "PENDING",
         "https://prow.k8s.io/pr?query=is%3Apr+repo%3Akubernetes%2Fkubernetes+author%3Acici37"
         "+head%3Ajsonv2adoption", ""),
        ("EasyCLA", "pass", "SUCCESS", "https://easycla.lfx.linuxfoundation.org/#/?version=2", ""),
        ("pull-kubernetes-unit", "pass", "SUCCESS",
         "https://prow.k8s.io/view/gs/kubernetes-ci-logs/pr-logs/pull/142359/"
         "pull-kubernetes-unit/2102857020397850624", "")),
    "required": ["pull-kubernetes-integration", "EasyCLA", "pull-kubernetes-unit"],
}

#: cli/cli#14485, recorded 2026-09-24 — and TWO ROWS TURNED RED BY HAND, both passed on the live
#: pull request: `build (ubuntu-latest)`, which the branch requires, and `ready-for-review`, a
#: workflow it does not require (and whose run is a newer failed run on the same branch). The rest
#: is as recorded, including `CodeQL`, a check RUN that is not a workflow of this repository
#: (another app's, linked at `/runs/<id>`, no `workflow`).
_UBUNTU_RUN = "35609532741"
CLI_14485_RED = {
    "all": _rows(
        ("ready-for-review / ready-for-review", "fail", "FAILURE",
         "https://github.com/cli/cli/actions/runs/35759594147/job/106853993520", "PR Triaging"),
        ("CodeQL", "pass", "SUCCESS", "https://github.com/cli/cli/runs/106365150997", ""),
        ("build (macos-latest)", "pass", "SUCCESS",
         f"https://github.com/cli/cli/actions/runs/{_UBUNTU_RUN}/job/106364884174",
         "Unit and Integration Tests"),
        ("build (ubuntu-latest)", "fail", "FAILURE",
         f"https://github.com/cli/cli/actions/runs/{_UBUNTU_RUN}/job/106364884287",
         "Unit and Integration Tests"),
        ("lint", "pass", "SUCCESS",
         "https://github.com/cli/cli/actions/runs/35609532793/job/106364884090", "Lint")),
    "required": ["build (macos-latest)", "build (ubuntu-latest)"],
}


def _github(monkeypatch, recorded, *, repo="cli/cli", runs=(), logs=None):
    """A `GitHubForge` whose `gh` answers from a recording, the way `gh` does: `--json <fields>`
    returns only those fields, `--required` only the required rows, and a branch that requires
    none answers with a sentence on stderr and nothing on stdout. `runs` and `logs` are what the
    branch's workflow runs would say if anybody asked — a newer failed run of ANOTHER workflow is
    exactly what a reader of "every failed run on the branch" picks up."""
    f = GitHubForge(repo)
    calls: list[list[str]] = []
    logs = logs or {}

    def gh(args, timeout=120):
        calls.append(list(args))
        out = SimpleNamespace(returncode=0, stdout="", stderr="")
        if args[:2] == ["pr", "checks"]:
            fields = args[args.index("--json") + 1].split(",")
            rows = recorded["all"]
            if "--required" in args:
                if isinstance(recorded["required"], str):
                    out.returncode, out.stderr = 1, recorded["required"]
                    return out
                rows = [r for r in rows if r["name"] in recorded["required"]]
            if not rows:
                out.returncode, out.stderr = 1, "no checks reported on the 'openfactory/12' branch"
                return out
            out.stdout = json.dumps([{k: r.get(k) for k in fields} for r in rows])
        elif args[:2] == ["pr", "view"]:
            out.stdout = json.dumps({"headRefName": "openfactory/12"})
        elif args[:2] == ["run", "list"]:
            out.stdout = json.dumps(list(runs))
        elif args[:2] == ["run", "view"]:
            out.stdout = logs.get(args[2], "")
        return out

    monkeypatch.setattr(f, "_gh", gh)
    f.calls = calls
    return f


GH_PR = "https://github.com/cli/cli/pull/14485"
NOTHING = {"all": [], "required": "no required checks reported on the 'openfactory/12' branch"}


@pytest.mark.parametrize("recorded,verdict", [
    (NOTHING, "none"),
    (CLI_14474_SKIPPED, "none"),
    (CLI_14474_REQUIRED_SKIPPED, "success"),
    (CLI_14474, "advisory"),
    (K8S_142359, "failure"),
    (CLI_14485_RED, "failure"),
])
def test_github_says_which_of_the_four_cases_and_the_table_agrees(monkeypatch, recorded, verdict):
    f = _github(monkeypatch, recorded, logs={_UBUNTU_RUN: LOG})
    assert f.pr_ci_status(pr=GH_PR) == verdict
    assert decide(checks.read(f, GH_PR)).verdict == verdict


def test_github_workflows_that_ran_and_are_not_required_are_advisory__not_nothing(monkeypatch):
    """F-02's repository: CI exists and nothing requires it. That is checks that RAN and gate
    nothing — not a pull request nothing looked at, which is what `none` now means."""
    f = _github(monkeypatch, CLI_14474)
    got = decide(checks.read(f, GH_PR))
    assert (got.verdict, got.action) == ("advisory", WAIT)
    assert not [c for c in f.calls if c[0] == "run"], "a log was read for checks that gate nothing"


def test_github_a_required_STATUS_is_asked_about__never_repaired_from_another_runs_log(
        monkeypatch):
    """A Prow job posts a commit status: a real build, and no log this forge can read. A failed
    workflow run of some OTHER workflow sits on the same branch. Handing its log in as this
    status's evidence is a blind repair with a log in hand."""
    f = _github(monkeypatch, K8S_142359, repo="kubernetes/kubernetes",
                runs=[{"databaseId": 77, "conclusion": "failure"}],
                logs={"77": "an unrelated workflow's failure"})
    got = decide(checks.read(f, "https://github.com/kubernetes/kubernetes/pull/142359"))
    assert (got.action, got.why) == (ASK, "no-evidence")
    assert "'pull-kubernetes-integration'" in got.note and "prow.k8s.io" in got.note
    assert not [c for c in f.calls if c[:2] == ["run", "view"]], "another run's log was read"


def test_github_a_status_that_LINKS_to_an_actions_run_is_not_read_as_one(monkeypatch):
    """A status's link is whatever the app that posted it wrote. One pointing at a workflow run
    is not that run's check, and its "log" is not evidence about it."""
    posted = {"all": _rows(("ci/external", "fail", "FAILURE",
                            "https://github.com/cli/cli/actions/runs/999/job/1", "")),
              "required": ["ci/external"]}
    f = _github(monkeypatch, posted, runs=[{"databaseId": 999, "conclusion": "failure"}],
                logs={"999": "text somebody else chose"})
    got = decide(checks.read(f, GH_PR))
    assert (got.action, got.why) == (ASK, "no-evidence")
    assert f.failed_ci_logs(pr=GH_PR) == "", "the port answered a status's link as a build's log"
    assert not [c for c in f.calls if c[:2] == ["run", "view"]]


def test_github_a_run_of_ANOTHER_repository_is_not_this_pull_requests_build(monkeypatch):
    """C-18 on the link: `gh run` does not resolve a URL, and a red check that links to some
    other repository's run is not a build of the pull request's own."""
    elsewhere = {"all": _rows(("pytest", "fail", "FAILURE",
                               "https://github.com/someone-else/cli/actions/runs/5/job/1", "ci")),
                 "required": ["pytest"]}
    f = _github(monkeypatch, elsewhere, logs={"5": LOG})
    assert f.failed_ci_logs(pr=GH_PR) == ""
    assert not [c for c in f.calls if c[:2] == ["run", "view"]]


def test_github_the_log_is_the_run_the_red_required_check_names(monkeypatch):
    """Not "the two newest failed runs on the branch": the run the failing REQUIRED workflow
    check links to, in the pull request's own repository. A newer failed run of a workflow that
    gates nothing is on the branch too, and is not this failure."""
    f = _github(monkeypatch, CLI_14485_RED,
                runs=[{"databaseId": 35759594147, "conclusion": "failure"},
                      {"databaseId": int(_UBUNTU_RUN), "conclusion": "failure"}],
                logs={"35759594147": "PR Triaging: label step exploded", _UBUNTU_RUN: LOG})
    got = decide(checks.read(f, GH_PR))
    assert got.action == REPAIR and got.checks == ["build (ubuntu-latest)"]
    assert LOG in got.evidence and "PR Triaging" not in got.evidence, (
        "another workflow's failure was handed to the repair as this build's")
    viewed = [c for c in f.calls if c[:2] == ["run", "view"]]
    assert [(c[2], c[c.index("--repo") + 1]) for c in viewed] == [(_UBUNTU_RUN, "cli/cli")]


def test_the_local_forge_is_nothing_ran_in_both_words(tmp_path):
    f = LocalForge("p", str(tmp_path), db_path=tmp_path / "board.db")
    assert f.pr_ci_status(pr="1") == "none" == decide(checks.read(f, "1")).verdict


async def test_the_local_forge_s_nothing_is_its_whole_answer__and_no_other_forge_s(tmp_path,
                                                                                   monkeypatch):
    """A directory on this machine has no CI, and says so the way its `merge_gates` does: its
    `none` is the whole answer, so the decision the watch records says nothing was expected. A
    forge that has CI and heard nothing yet does not get to say it (review of #320)."""
    from openfactory.runtime.temporal import activities

    local = LocalForge("p", str(tmp_path), db_path=tmp_path / "board.db")
    monkeypatch.setattr(activities, "ProjectRegistry", lambda: SimpleNamespace(get=lambda n: n))
    monkeypatch.setattr(activities, "_forge_for", lambda project: local)
    got = await activities.read_ci_checks(MergeCheckInput(project="p", pr_url="1"))
    assert declares_no_checks(local) and (got.verdict, got.nothing_expected) == ("none", True)

    hosted = _github(monkeypatch, NOTHING)
    monkeypatch.setattr(activities, "_forge_for", lambda project: hosted)
    got = await activities.read_ci_checks(MergeCheckInput(project="p", pr_url=GH_PR))
    assert (got.verdict, got.nothing_expected) == ("none", False)


def test_a_grace_under_a_minute_is_said_in_seconds():
    """`_NOTHING_RAN_GRACE` rendered as whole minutes read "0 minutes" below one."""
    said = nothing_ran_note(timedelta(seconds=45), timedelta(seconds=30))
    assert "in 30 seconds" in said and "0 minutes" not in said


# ═══ the watch: the real workflow, on a real (time-skipping) engine ═════════════════════════════

TQ = "test-only-a-blocking-build-failure"

#: THIS FILE STARTS ITS OWN ENGINE for the cases marked with it and throws it away — the declared
#: exception to the suite's no-live-engine rule (`conftest.OWNS_ITS_ENGINE`).
engine = pytest.mark.owns_its_engine

NOTHING_RAN = CiDecision(verdict="none", action=WAIT)
_CI: list[CiDecision] = [NOTHING_RAN]
_MSTATE = ["clean"]
_AUTO = [True]
_FORCED: list[str] = []
_MERGED: list[str] = []
_CLOSED: list[str] = []
_REPAIRS: list[CiRepairInput] = []
WATCHED = "https://x/pr/1"


@activity.defn(name="run_job")
async def mock_run_job(inp: RunJobInput) -> RunResult:
    return RunResult(ticket_id=inp.issue, state=JobState.PR_OPEN, pr_url=WATCHED,
                     branch="openfactory/12", auto_merge=_AUTO[0])


@activity.defn(name="check_pr_status")
async def mock_open(inp: MergeCheckInput) -> str:
    return "open"


@activity.defn(name="read_ci_checks")
async def mock_read(inp: MergeCheckInput) -> CiDecision:
    return _CI[0]


@activity.defn(name="check_ci_status")
async def mock_legacy(inp: MergeCheckInput) -> str:
    return _CI[0].verdict


@activity.defn(name="pr_mergeable_state")
async def mock_mstate(inp: MergeCheckInput) -> str:
    return _MSTATE[0]


@activity.defn(name="force_merge_pr")
async def mock_force(inp: MergeCheckInput) -> bool:
    _FORCED.append(inp.pr_url)
    return True


@activity.defn(name="merge_pr_saying_why")
async def mock_merge(inp: MergeCheckInput) -> str:
    _MERGED.append(inp.pr_url)
    return ""


@activity.defn(name="close_pr")
async def mock_close(inp: MergeCheckInput) -> None:
    _CLOSED.append(inp.pr_url)


@activity.defn(name="repair_ci")
async def mock_repair(inp: CiRepairInput) -> RunResult:
    _REPAIRS.append(inp)
    return RunResult(ticket_id=inp.issue, state=JobState.PR_OPEN, pr_url=inp.pr_url)


@activity.defn(name="update_pr_branch")
async def mock_update(inp: MergeCheckInput) -> bool:
    return True


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


MOCKS = [mock_run_job, mock_open, mock_read, mock_legacy, mock_mstate, mock_force, mock_merge,
         mock_close, mock_repair, mock_update, mock_settle, mock_mark, mock_diagnose, mock_title,
         mock_refresh, mock_say, mock_notify]


@pytest.fixture
async def env():
    e = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
    try:
        yield e
    finally:
        await e.shutdown()


@pytest.fixture(autouse=True)
def _fresh():
    _CI[0], _MSTATE[0], _AUTO[0] = NOTHING_RAN, "clean", True
    _FORCED.clear(), _MERGED.clear(), _CLOSED.clear(), _REPAIRS.clear()


async def _start(client: Client, *, deadline_days: int = 3650) -> WorkflowHandle:
    return await client.start_workflow(
        JobWorkflow.run,
        JobParams(project="p", issue="12", promote=False, merge_deadline_days=deadline_days),
        id=f"wf-{uuid.uuid4()}", task_queue=TQ)


async def _card(h: WorkflowHandle, what: str, says, *, tries: int = 400) -> dict:
    """The merge wait the card is drawn from, once it `says` what is looked for. Polled in REAL
    time: the time-skipping engine only leaps while a result is awaited or `env.sleep` runs."""
    for _ in range(tries):
        gate = await h.query(JobWorkflow.awaiting_merge)
        if gate and says(gate):
            return gate
        await asyncio.sleep(0.05)
    raise AssertionError(f"the card never said {what}; last: {gate!r}")


@engine
async def test_nothing_ran_is_waited_on_then_said__and_the_machine_never_merges_it(env):
    """A pull request one second old on the machine-merge path, mergeable, with nothing reported
    on it. The self-heal merged it at once — "mergeable NOW, every required check passed", of a
    pull request no check had looked at. Now the watch waits ten minutes for a check to report,
    then says nothing ran and hands the merge to a person; the machine never merges it itself."""
    async with Worker(env.client, task_queue=TQ, workflows=[JobWorkflow], activities=MOCKS):
        h = await _start(env.client)
        waiting = await _card(h, "that no check has reported yet",
                              lambda g: "no check has reported" in (g.get("note") or ""))
        assert waiting["auto"] is True and _FORCED == [], "merged on a reading of nothing"

        await env.sleep(timedelta(minutes=11))
        said = await _card(h, "that nothing ran, after the bound",
                           lambda g: "no check has run" in (g.get("note") or ""))
        assert "10 minutes" in said["note"] and "nothing on the forge has verified it" in (
            said["note"])
        assert said["auto"] is False, "the card still says the machine is merging it"
        assert _FORCED == [], "the machine merged a pull request nothing verified"

        await h.signal(JobWorkflow.human_merge_gate, args=["merge", "", "a-person"])
        result = await h.result()

    assert result.state == JobState.MERGED and _MERGED == [WATCHED] and _FORCED == []


@engine
async def test_an_advisory_failure_is_said_on_the_card_and_starts_no_repair(env):
    """ACCEPTANCE 1, to the card: the Azure DevOps case, read through the real row and the real
    table, on the human path. The person is told what is red and that nothing will act on it."""
    _CI[0] = decide(checks.read(_ado(CASE_SEEN), PR))
    _MSTATE[0], _AUTO[0] = "blocked", False
    async with Worker(env.client, task_queue=TQ, workflows=[JobWorkflow], activities=MOCKS):
        h = await _start(env.client)
        gate = await _card(h, "which advisory check is failing",
                           lambda g: "'Work item linking'" in (g.get("note") or ""))
        assert "advisory" in gate["note"] and "cannot stop this merge" in gate["note"]
        assert "no check has" not in gate["note"], "checks that ran were called nothing"
        await h.signal(JobWorkflow.human_merge_gate, args=["discard", "", "a-person"])
        await h.result()
    assert _REPAIRS == [] and _CLOSED == [WATCHED]


@engine
async def test_checks_that_ran_and_gate_nothing_still_let_the_machine_land_it(env, monkeypatch):
    """The other side of the line, so it is not drawn too far: a repository whose own rules
    require nothing, with CI that ran (F-02, recorded), is landed by the self-heal as before."""
    _CI[0] = decide(checks.read(_github(monkeypatch, CLI_14474), GH_PR))
    async with Worker(env.client, task_queue=TQ, workflows=[JobWorkflow], activities=MOCKS):
        h = await _start(env.client)
        for _ in range(100):
            if _FORCED:
                break
            await asyncio.sleep(0.05)
        if not _FORCED:
            await h.terminate()
            pytest.fail("checks that ran but gate nothing were treated as if nothing ran")
        result = await h.result()
    assert result.state == JobState.MERGED and _FORCED == [WATCHED]


@engine
async def test_a_forge_with_no_ci_is_not_waited_on_and_the_machine_lands_it(env):
    """The local forge's `none` is its whole answer (`nothing_expected`): a local job on the
    machine-merge path still lands itself, as it did before #184 (review of #320)."""
    _CI[0] = CiDecision(verdict="none", action=WAIT, nothing_expected=True)
    async with Worker(env.client, task_queue=TQ, workflows=[JobWorkflow], activities=MOCKS):
        h = await _start(env.client)
        for _ in range(100):
            if _FORCED:
                break
            await asyncio.sleep(0.05)
        if not _FORCED:
            await h.terminate()
            pytest.fail("a forge with no CI was waited on as if checks might still report")
        result = await h.result()
    assert result.state == JobState.MERGED and _FORCED == [WATCHED]


MARKER = "nothing-ran-is-not-green"


def _patched_as(monkeypatch, answer: bool):
    """`workflow.patched`, answering `answer` for THIS marker and the truth for every other."""
    from temporalio import workflow as tw

    real = tw.patched
    monkeypatch.setattr(tw, "patched", lambda name: answer if name == MARKER else real(name))


@engine
async def test_a_job_recorded_before_the_marker_replays_what_it_recorded(env, monkeypatch):
    """A job already in the watch recorded the self-merge on a reading of nothing; its history
    must replay on this code. Recorded on the arm `patched()` selects for it, replayed through
    the real `patched()` — and, to prove the replay can tell, through the new arm, which must
    diverge.

    A ONE-DAY DEADLINE, so that on the day the marker stops gating the new arm this case ends —
    on the watch's own `not merged within 1d` — instead of time-skipping through ten years of
    polls against the very defect it names."""
    with monkeypatch.context() as m:
        _patched_as(m, False)
        async with Worker(env.client, task_queue=TQ, workflows=[JobWorkflow], activities=MOCKS):
            h = await _start(env.client, deadline_days=1)
            result = await h.result()
        history = await h.fetch_history()
    assert result.state == JobState.MERGED and _FORCED == [WATCHED], (
        "the recording is not the pre-marker arm it claims to be")

    await Replayer(workflows=[JobWorkflow],
                   data_converter=pydantic_data_converter).replay_workflow(history)

    _patched_as(monkeypatch, True)
    with pytest.raises(Exception) as caught:
        await Replayer(workflows=[JobWorkflow],
                       data_converter=pydantic_data_converter).replay_workflow(history)
    said = str(caught.value)
    assert "determinis" in said.lower() or "TMPRL1100" in said, (
        f"the ungated replay failed for another reason: {said[:400]}")
