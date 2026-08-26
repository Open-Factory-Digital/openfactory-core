"""What Azure Pipelines actually answers, and what the observer makes of it.

EVERY FIXTURE BELOW IS A CAPTURE, not a guess: taken on 2026-08-06 from the live pipeline
`fx-ado-ci` in acme-ai/factory (definition 1, builds 1 and 5, environment `staging`), which
this suite's author created, ran and cancelled to see each shape. Where a field is missing from a
fixture it is missing from the wire too — a running build carries NO `result` key at all, and a
double that helpfully sets `"result": None` would be testing a contract Azure DevOps does not have.

The two guards that matter most here are about ABSENCE:
    a running build must not read as a failed one     (`status` first, `result` only when complete)
    "no pipeline" must not read as "not run yet"      (nothing will ever come vs. it has not come)
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

import httpx
import pytest

from openfactory.adapters.environment.azure_pipelines import AzurePipelinesObserver
from openfactory.adapters.environment.base import EnvironmentObserver
from openfactory.adapters.environment.registry import OBSERVERS, build_observer, observer_kind
from openfactory.contracts.project import Project, ProviderRef

ORG, ADO_PROJECT, REPO = "acme-ai", "factory", "fx-ado"
REPO_ID = "21200617-5ca5-4819-a6e0-68bbec2c964c"
SHA = "8c628eee746b4905e1113d6d3839cb54aefbedc5"
OTHER_SHA = "da8d1f7e5c1f4b3a9d2e6c8b7a5f4e3d2c1b0a99"

#: `GET build/definitions?repositoryId=…&repositoryType=TfsGit` — trimmed to the fields read.
DEFINITION = {
    "id": 1,
    "name": "fx-ado-ci",
    "path": "\\",
    "type": "build",
    "queueStatus": "enabled",
    "_links": {"web": {"href": "https://dev.azure.com/acme-ai/aaa124b6/_build/definition"
                               "?definitionId=1"}},
}

#: `GET build/builds/1` WHILE IT RAN. Note what is not here: no `result` key, no `finishTime`.
BUILD_RUNNING = {
    "id": 1,
    "buildNumber": "20260806.1",
    "status": "inProgress",
    "queueTime": "2026-08-06T09:12:14.0002913Z",
    "startTime": "2026-08-06T09:12:28.8370287Z",
    "sourceBranch": "refs/heads/main",
    "sourceVersion": SHA,
    "reason": "manual",
    "definition": {"id": 1, "name": "fx-ado-ci"},
    "_links": {"web": {"href": "https://dev.azure.com/acme-ai/aaa124b6/_build/results?buildId=1"}},
}

#: The same build after `PATCH {"status": "cancelling"}` landed.
BUILD_CANCELED = {
    **BUILD_RUNNING,
    "status": "completed",
    "result": "canceled",
    "finishTime": "2026-08-06T09:24:01.8373217Z",
}

#: `GET build/builds/5` — queued behind the jammed one, and again carrying no `result`.
BUILD_QUEUED = {
    "id": 5,
    "buildNumber": "20260806.5",
    "status": "notStarted",
    "queueTime": "2026-08-06T09:20:30.5333333Z",
    "sourceBranch": "refs/heads/main",
    "sourceVersion": OTHER_SHA,
    "reason": "individualCI",
    "definition": {"id": 1, "name": "fx-ado-ci"},
    "_links": {"web": {"href": "https://dev.azure.com/acme-ai/aaa124b6/_build/results?buildId=5"}},
}

#: A green build — and the one shape here NOT captured whole from the wire, which is why it says
#: so. `succeeded` is real ADO vocabulary observed in this same pipeline (its `tests` stage and its
#: agent job both landed `completed`/`succeeded` in the build timeline); what could not be observed
#: was a whole BUILD reaching it, because the organisation's hosted agent stopped picking up jobs
#: after the first one. Nothing below pretends otherwise.
BUILD_SUCCEEDED = {**BUILD_QUEUED, "status": "completed", "result": "succeeded",
                   "finishTime": "2026-08-06T09:21:02.1000000Z"}

#: `GET distributedtask/environments?name=staging`
ENVIRONMENT = {"id": 1, "name": "staging", "description": "Automatically created environment"}

#: `GET distributedtask/environments/1/environmentdeploymentrecords` WHILE THE JOB QUEUED. It
#: exists from the moment the deployment job is queued, and carries no `result` until it lands —
#: which is what makes "no records at all" mean "nothing ever targeted this environment".
RECORD_QUEUED = {
    "id": 1,
    "environmentId": 1,
    "stageName": "staging",
    "jobName": "staging",
    "planType": "Build",
    "definition": {"id": 1, "name": "fx-ado-ci"},
    "owner": {"id": 1, "name": "20260806.1"},
    "queueTime": "2026-08-06T09:14:19.442317Z",
    "startTime": "2026-08-06T09:14:19.5759005Z",
}

#: The same record once the build was cancelled.
RECORD_CANCELED = {**RECORD_QUEUED, "result": "canceled",
                   "finishTime": "2026-08-06T09:24:00.7901361Z"}


class _RecordedADO:
    """Answers the routes the live API answered, and remembers what it was asked.

    Anything else raises: a test must not be able to pass by exercising a route nobody has ever
    seen a response from. `params` are recorded because half of this adapter's correctness is in
    the query string — the repository scope pair, and `refs/heads/…` rather than a bare branch.
    """

    def __init__(self, routes: dict[str, object]) -> None:
        self.routes = routes
        self.asked: list[tuple[str, str, dict]] = []

    def __call__(self, method: str, path: str, *, params=None, **_kw) -> dict:
        self.asked.append((method, path, dict(params or {})))
        if path not in self.routes:
            raise AssertionError(
                f"{method} {path} is not a route this fixture ever saw the live API answer"
            )
        answer = self.routes[path]
        return answer(dict(params or {})) if callable(answer) else answer

    def params_for(self, path: str) -> list[dict]:
        return [p for _m, asked, p in self.asked if asked == path]


def _observer(routes: dict[str, object], *, repo: str = REPO) -> tuple[AzurePipelinesObserver,
                                                                      _RecordedADO]:
    obs = AzurePipelinesObserver(organization=ORG, project=ADO_PROJECT, repo=repo, token="a-pat")
    recorded = _RecordedADO({f"git/repositories/{repo}": {"id": REPO_ID, "name": repo}, **routes})
    # ONLY `call` is replaced. `values()` — the ".value array ADO wraps every collection in"
    # unwrapping — stays the shared client's own code, so these tests exercise it rather than a
    # reimplementation of it.
    obs.client.call = recorded  # type: ignore[method-assign]
    return obs, recorded


def _builds(*rows: dict):
    """The builds route: a branch filter answers with the rows, a sha filter answers with all of
    them — because the live API ignores `sourceVersion` entirely (proven in the test below)."""
    return lambda params: {"value": list(rows)}


# ── the two fields ──────────────────────────────────────────────────────────────────────────────

def test_the_fixtures_still_lack_the_field_the_api_does_not_send():
    """The guard on the guards. If someone 'tidies' these captures by adding `result: None`, the
    running-build test below would keep passing while the contract it protects had changed."""
    assert "result" not in BUILD_RUNNING and "result" not in BUILD_QUEUED
    assert "result" not in RECORD_QUEUED
    assert BUILD_CANCELED["result"] == "canceled" and BUILD_CANCELED["status"] == "completed"


def test_a_running_build_is_pending_and_never_a_failure():
    """`{"status": "inProgress"}` with no result at all. Reading `result` first maps every build in
    flight to "not succeeded" — a red light on a build that is still running."""
    obs, _ = _observer({"build/definitions": {"value": [DEFINITION]},
                        "build/builds": _builds(BUILD_RUNNING)})
    assert [c.status for c in obs.ci_status(repo=REPO, ref="main")] == ["pending"]


@pytest.mark.parametrize("status", ["notStarted", "inProgress", "postponed", "cancelling"])
def test_every_unfinished_status_is_pending(status):
    """`cancelling` included: the build has not finished, and it lands on `canceled` → failure a
    moment later. It was observed live, in exactly that order."""
    obs, _ = _observer({"build/definitions": {"value": [DEFINITION]},
                        "build/builds": _builds({**BUILD_RUNNING, "status": status})})
    assert obs.ci_status(repo=REPO, ref="main")[0].status == "pending"


@pytest.mark.parametrize("result,expected", [
    ("succeeded", "success"),
    ("failed", "failure"),
    ("canceled", "failure"),          # a cancelled check must not read as green
    ("partiallySucceeded", "failure"),  # a step failed; the pipeline tolerated it, we do not
])
def test_a_completed_build_reads_its_result(result, expected):
    obs, _ = _observer({"build/definitions": {"value": [DEFINITION]},
                        "build/builds": _builds({**BUILD_CANCELED, "result": result})})
    assert obs.ci_status(repo=REPO, ref="main")[0].status == expected


def test_a_green_build_is_a_green_check_with_a_link_a_human_can_open():
    obs, _ = _observer({"build/definitions": {"value": [DEFINITION]},
                        "build/builds": _builds(BUILD_SUCCEEDED)})
    check = obs.ci_status(repo=REPO, ref="main")[0]
    assert (check.name, check.status) == ("fx-ado-ci", "success")
    assert check.url == BUILD_SUCCEEDED["_links"]["web"]["href"]


def test_a_result_this_adapter_cannot_read_is_unknown_and_says_so(caplog):
    """Neither green nor red by accident — and never silent about it."""
    obs, _ = _observer({"build/definitions": {"value": [DEFINITION]},
                        "build/builds": _builds({**BUILD_CANCELED, "result": "somethingNew"})})
    with caplog.at_level(logging.WARNING, logger="openfactory.environment.azure"):
        assert obs.ci_status(repo=REPO, ref="main")[0].status == "unknown"
    assert "OPENFACTORY_ADO_UNKNOWN_BUILD_RESULT" in caplog.text and "somethingNew" in caplog.text


# ── no pipeline is not the same as no run ───────────────────────────────────────────────────────

def test_no_pipeline_configured_is_an_empty_list():
    """Nothing will ever report on this ref, so a watcher must stop waiting. The trap is that the
    API answers `{"count": 0}` to this and to "the ref has not run" alike."""
    obs, recorded = _observer({"build/definitions": {"value": []}})
    assert obs.ci_status(repo=REPO, ref="main") == []
    # and it did not go on to ask about builds — there is nothing to ask about
    assert recorded.params_for("build/builds") == []


def test_a_pipeline_that_has_not_run_for_this_ref_is_a_pending_row():
    """The other half of the distinction, and the reason it is a row rather than an empty list: a
    verdict IS coming, so the caller keeps waiting instead of merging on nothing."""
    obs, _ = _observer({"build/definitions": {"value": [DEFINITION]},
                        "build/builds": _builds()})
    checks = obs.ci_status(repo=REPO, ref="feature/new")
    assert [(c.name, c.status) for c in checks] == [("fx-ado-ci", "pending")]
    assert checks[0].url == DEFINITION["_links"]["web"]["href"]


# ── the query string is half the correctness ────────────────────────────────────────────────────

def test_a_branch_is_asked_of_the_server_as_a_full_ref():
    """`branchName=main` answers 0 where `branchName=refs/heads/main` answers the build — verified
    against the live API. A bare branch name would have every ref look like it never ran."""
    obs, recorded = _observer({"build/definitions": {"value": [DEFINITION]},
                               "build/builds": _builds(BUILD_RUNNING)})
    obs.ci_status(repo=REPO, ref="main")
    assert recorded.params_for("build/builds")[0]["branchName"] == "refs/heads/main"


def test_a_ref_already_spelled_in_full_is_left_alone():
    obs, recorded = _observer({"build/definitions": {"value": [DEFINITION]},
                               "build/builds": _builds(BUILD_RUNNING)})
    obs.ci_status(repo=REPO, ref="refs/heads/release/1.2")
    assert recorded.params_for("build/builds")[0]["branchName"] == "refs/heads/release/1.2"


def test_every_build_query_is_scoped_to_one_repository():
    """An Azure DevOps project holds many repositories and these routes are project-scoped, so
    without this pair the answer includes other repositories' pipelines. Both halves are required:
    the live API rejects an invalid `repositoryType` outright."""
    obs, recorded = _observer({"build/definitions": {"value": [DEFINITION]},
                               "build/builds": _builds(BUILD_RUNNING)})
    obs.ci_status(repo=REPO, ref="main")
    for path in ("build/definitions", "build/builds"):
        for params in recorded.params_for(path):
            assert params["repositoryId"] == REPO_ID
            assert params["repositoryType"] == "TfsGit"


def test_a_commit_is_matched_here_because_the_server_ignores_sourceVersion():
    """`?sourceVersion=<a sha that does not exist>` returns the build anyway — the parameter is
    accepted and ignored. So it is never sent, and the match happens in Python."""
    obs, recorded = _observer({"build/definitions": {"value": [DEFINITION]},
                               "build/builds": lambda p: {"value": [] if "branchName" in p
                                                          else [BUILD_QUEUED, BUILD_CANCELED]}})
    checks = obs.ci_status(repo=REPO, ref=SHA)
    assert [c.status for c in checks] == ["failure"]  # build 1, the one whose sha this is
    assert not any("sourceVersion" in p for p in recorded.params_for("build/builds"))


def test_a_short_sha_matches_the_build_it_prefixes():
    obs, _ = _observer({"build/definitions": {"value": [DEFINITION]},
                        "build/builds": lambda p: {"value": [] if "branchName" in p
                                                   else [BUILD_CANCELED]}})
    assert obs.ci_status(repo=REPO, ref=SHA[:8])[0].status == "failure"


def test_a_branch_whose_name_looks_like_a_sha_is_still_a_branch():
    """The branch is asked first precisely so this needs no guess: `deadbeef` as a branch answers
    from the server, and the client-side sha scan never runs."""
    hex_branch = {**BUILD_RUNNING, "sourceBranch": "refs/heads/deadbeef"}
    obs, recorded = _observer({"build/definitions": {"value": [DEFINITION]},
                               "build/builds": lambda p: {"value": [hex_branch]
                                                          if "branchName" in p else []}})
    assert obs.ci_status(repo=REPO, ref="deadbeef")[0].status == "pending"
    assert len(recorded.params_for("build/builds")) == 1  # no second, unfiltered scan


def test_running_out_of_window_is_unknown_rather_than_pending(caplog):
    """"Could not read" must never look like "has not happened". Pending would hold a watch on a
    verdict this cannot see; unknown says the truth."""
    from openfactory.adapters.environment.azure_pipelines import BUILD_WINDOW

    window = [{**BUILD_QUEUED, "id": i, "sourceVersion": f"{i:040x}"} for i in range(BUILD_WINDOW)]
    obs, _ = _observer({"build/definitions": {"value": [DEFINITION]},
                        "build/builds": lambda p: {"value": [] if "branchName" in p else window}})
    with caplog.at_level(logging.ERROR, logger="openfactory.environment.azure"):
        assert obs.ci_status(repo=REPO, ref=SHA)[0].status == "unknown"
    assert "OPENFACTORY_ADO_SHA_WINDOW_EXHAUSTED" in caplog.text


def test_a_rerun_decides_the_verdict_not_the_first_attempt():
    """Both attempts stay in the answer. Newest-first is decided here because `queryOrder` is
    accepted-and-ignored when invalid, so a valid one proves nothing."""
    older = {**BUILD_CANCELED, "id": 1, "queueTime": "2026-08-06T09:12:14Z", "result": "failed"}
    newer = {**BUILD_CANCELED, "id": 9, "queueTime": "2026-08-06T10:30:00Z", "result": "succeeded"}
    obs, _ = _observer({"build/definitions": {"value": [DEFINITION]},
                        "build/builds": _builds(older, newer)})  # deliberately oldest-first
    assert obs.ci_status(repo=REPO, ref="main")[0].status == "success"


def test_each_pipeline_gets_its_own_row():
    second = {**DEFINITION, "id": 2, "name": "fx-ado-nightly"}
    ran = {**BUILD_CANCELED, "result": "succeeded", "definition": {"id": 1, "name": "fx-ado-ci"}}
    obs, _ = _observer({"build/definitions": {"value": [DEFINITION, second]},
                        "build/builds": _builds(ran)})
    assert [(c.name, c.status) for c in obs.ci_status(repo=REPO, ref="main")] == [
        ("fx-ado-ci", "success"), ("fx-ado-nightly", "pending")]


# ── deploys: the record does not carry the ref ──────────────────────────────────────────────────

_ENV_ROUTES = {
    "distributedtask/environments": lambda p: {
        "value": [ENVIRONMENT] if p.get("name") in (None, "staging") else []},
    "distributedtask/environments/1/environmentdeploymentrecords": {"value": [RECORD_CANCELED]},
}


def test_a_deploy_is_only_this_refs_when_the_build_that_made_it_is():
    """The record names the environment, the stage and the BUILD — never the ref. Correlating
    through the build is what stops somebody else's commit from confirming this one's deploy."""
    obs, _ = _observer({**_ENV_ROUTES, "build/builds": _builds(BUILD_CANCELED)})
    assert obs.deploy_status(env="staging", ref="main") == "failure"


def test_a_deploy_made_by_another_build_is_not_this_refs_deploy():
    obs, _ = _observer({**_ENV_ROUTES, "build/builds": _builds(BUILD_QUEUED)})  # build 5, not 1
    assert obs.deploy_status(env="staging", ref="main") == "pending"


def test_a_queued_deployment_record_is_pending():
    """Observed live: the record exists from the moment the job is queued, with a `queueTime` and
    no `result`. Reading a missing result as anything but pending would call an unstarted deploy
    broken."""
    obs, _ = _observer({**_ENV_ROUTES, "build/builds": _builds(BUILD_CANCELED),
                        "distributedtask/environments/1/environmentdeploymentrecords":
                            {"value": [RECORD_QUEUED]}})
    assert obs.deploy_status(env="staging", ref="main") == "pending"


def test_the_newest_deployment_of_the_ref_decides():
    old = {**RECORD_CANCELED, "id": 1, "startTime": "2026-08-06T09:14:19Z", "result": "failed"}
    new = {**RECORD_CANCELED, "id": 7, "startTime": "2026-08-06T11:00:00Z", "result": "succeeded"}
    obs, _ = _observer({**_ENV_ROUTES, "build/builds": _builds(BUILD_CANCELED),
                        "distributedtask/environments/1/environmentdeploymentrecords":
                            {"value": [old, new]}})
    assert obs.deploy_status(env="staging", ref="main") == "success"


def test_an_environment_that_does_not_exist_is_unknown_and_names_the_ones_that_do(caplog):
    """A typo in `deploy_ref` must not read as a deploy that has not happened yet — that waits for
    ever. It reads as unknown, with the real names in the log so it can be fixed."""
    obs, _ = _observer({**_ENV_ROUTES, "build/builds": _builds(BUILD_CANCELED)})
    with caplog.at_level(logging.WARNING, logger="openfactory.environment.azure"):
        assert obs.deploy_status(env="stagng", ref="main") == "unknown"
    assert "OPENFACTORY_ADO_NO_ENVIRONMENT" in caplog.text and "staging" in caplog.text


def test_an_environment_nothing_ever_deployed_to_is_unknown_not_pending(caplog):
    """Zero records cannot mean "in flight", because a record appears when the job is QUEUED. It
    means no pipeline targets this environment, and pending would wait on nobody."""
    obs, _ = _observer({**_ENV_ROUTES, "build/builds": _builds(BUILD_CANCELED),
                        "distributedtask/environments/1/environmentdeploymentrecords":
                            {"value": []}})
    with caplog.at_level(logging.WARNING, logger="openfactory.environment.azure"):
        assert obs.deploy_status(env="staging", ref="main") == "unknown"
    assert "OPENFACTORY_ADO_ENVIRONMENT_NEVER_DEPLOYED" in caplog.text


def test_a_deploy_whose_build_cannot_be_found_is_unknown_not_pending(caplog):
    from openfactory.adapters.environment.azure_pipelines import BUILD_WINDOW

    window = [{**BUILD_QUEUED, "id": i, "sourceVersion": f"{i:040x}"} for i in range(BUILD_WINDOW)]
    obs, _ = _observer({**_ENV_ROUTES,
                        "build/builds": lambda p: {"value": [] if "branchName" in p else window}})
    with caplog.at_level(logging.ERROR, logger="openfactory.environment.azure"):
        assert obs.deploy_status(env="staging", ref=SHA) == "unknown"
    assert "OPENFACTORY_ADO_SHA_WINDOW_EXHAUSTED" in caplog.text


def _record_page(n: int, *, since: str = "11") -> list[dict]:
    """`n` deployment records, all newer than the build fixtures above and none owned by them."""
    return [{**RECORD_CANCELED, "id": 500 + i, "owner": {"id": 500 + i}, "result": "succeeded",
             "queueTime": f"2026-08-06T{since}:{i // 60:02d}:{i % 60:02d}Z"} for i in range(n)]


def test_a_full_record_page_that_starts_after_this_ref_is_unknown_not_pending(caplog):
    """THE TWIN OF THE BUILD-WINDOW GUARD, and it was missing. The records route has no ref and no
    build filter, so the only bound on it is `$top`: once a page comes back full and every record
    on it is NEWER than this ref's build, "no record of mine here" cannot be told apart from "mine
    fell off the end". Answering `pending` there is the exact sentence this codebase keeps paying
    for — could not read, reported as has not happened."""
    from openfactory.adapters.environment.azure_pipelines import RECORD_WINDOW

    obs, _ = _observer({**_ENV_ROUTES, "build/builds": _builds(BUILD_CANCELED),  # build 1, 09:12
                        "distributedtask/environments/1/environmentdeploymentrecords":
                            {"value": _record_page(RECORD_WINDOW)}})
    with caplog.at_level(logging.ERROR, logger="openfactory.environment.azure"):
        assert obs.deploy_status(env="staging", ref="main") == "unknown"
    assert "OPENFACTORY_ADO_RECORD_WINDOW_EXHAUSTED" in caplog.text


def test_a_page_that_is_not_full_still_answers_pending():
    """The other half, and the reason the guard is not just "the page is full": a page the server
    did not have to truncate IS the whole history, so a ref missing from it genuinely has not
    deployed. Waiting is right, and degrading every busy environment to `unknown` would be its own
    bug."""
    from openfactory.adapters.environment.azure_pipelines import RECORD_WINDOW

    obs, _ = _observer({**_ENV_ROUTES, "build/builds": _builds(BUILD_CANCELED),
                        "distributedtask/environments/1/environmentdeploymentrecords":
                            {"value": _record_page(RECORD_WINDOW - 1)}})
    assert obs.deploy_status(env="staging", ref="main") == "pending"


def test_a_full_record_page_reaching_back_past_this_ref_still_answers_pending():
    """A full page is not enough on its own either: if the OLDEST record on it is older than this
    ref's build, a deploy of that build would have been on the page. Nothing was lost, so the ref
    is waiting rather than unreadable."""
    from openfactory.adapters.environment.azure_pipelines import RECORD_WINDOW

    page = _record_page(RECORD_WINDOW)
    page[0] = {**page[0], "queueTime": "2026-08-06T08:00:00Z"}  # before build 1's 09:12
    obs, _ = _observer({**_ENV_ROUTES, "build/builds": _builds(BUILD_CANCELED),
                        "distributedtask/environments/1/environmentdeploymentrecords":
                            {"value": page}})
    assert obs.deploy_status(env="staging", ref="main") == "pending"


# ── health, and the read-only promise ───────────────────────────────────────────────────────────

def test_health_is_the_clients_own_url_and_a_dead_probe_is_false(monkeypatch, caplog):
    obs, _ = _observer({})
    monkeypatch.setattr(httpx, "get", lambda *a, **k: (_ for _ in ()).throw(
        httpx.ConnectError("no route to host")))
    with caplog.at_level(logging.WARNING, logger="openfactory.environment.azure"):
        assert obs.health(url="https://fx-ado.example/health") is False
    assert "no route to host" in caplog.text


def test_health_is_true_on_a_2xx(monkeypatch):
    obs, _ = _observer({})
    monkeypatch.setattr(httpx, "get", lambda *a, **k: httpx.Response(204))
    assert obs.health(url="https://fx-ado.example/health") is True


def test_nothing_in_this_adapter_can_deploy():
    """ADR-0005 asserted rather than promised: the platform triggers a merge or a tag and observes;
    the client's pipeline deploys, with the client's own secrets. Every call here is a GET, so the
    worst this axis's credential can do is read build history."""
    src = Path("openfactory/adapters/environment/azure_pipelines.py").read_text()
    tree = ast.parse(src)
    verbs = {
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "call"
        and node.args and isinstance(node.args[0], ast.Constant)
    }
    assert verbs == {"GET"}, f"this observer is not read-only any more: {verbs}"
    assert "values(" in src  # …and the collection reads go through the client's own unwrapping


# ── reachability: a capability nothing reaches is not a capability ──────────────────────────────

def _ado_project(**options) -> Project:
    opts = {"organization": ORG, "project": ADO_PROJECT, **options}
    return Project(name="fx-ado", repo_path="/tmp/fx-ado",
                   tracker=ProviderRef(kind="azure_devops", repo=ADO_PROJECT),
                   forge=ProviderRef(kind="azure_devops", repo=REPO, options=opts))


def test_the_registry_row_is_what_reaches_this_observer():
    """The guard against this codebase's signature defect. `build_observer` is what the factory and
    the action catalog call; if this row were missing, every line above would be dead code."""
    assert "azure_devops" in OBSERVERS and "azure_pipelines" in OBSERVERS
    built = build_observer(_ado_project())
    assert isinstance(built, AzurePipelinesObserver)
    assert isinstance(built, EnvironmentObserver)  # the Protocol, checked at runtime


def test_the_ci_follows_the_forge_so_one_value_configures_both():
    assert observer_kind(_ado_project()) == "azure_devops"
    assert isinstance(build_observer(_ado_project(ci="azure_pipelines")), AzurePipelinesObserver)


def test_the_registry_carries_the_coordinates_from_the_projects_options():
    built = build_observer(_ado_project())
    assert (built.client.organization, built.client.project, built.repo) == (ORG, ADO_PROJECT, REPO)


def test_the_ado_project_is_read_the_way_every_other_axis_reads_it():
    """`tracker/registry.py` documents the ADO project as `options.project` OR the tracker's own
    `repo`, and the forge and board registries both honour that. This one did not — so a row
    spelled the documented way built a working tracker, board and forge, and then raised
    ValueError here. `openfactory/factory.py:399` builds this observer for EVERY PromotionRunner, so that
    is a promotion dying at construction, before a single pipeline is read."""
    p = Project(name="fx-ado", repo_path="/tmp/fx-ado",
                tracker=ProviderRef(kind="azure_devops", repo=ADO_PROJECT),
                forge=ProviderRef(kind="azure_devops", repo=REPO,
                                  options={"organization": ORG}))  # no `project` here
    built = build_observer(p)
    assert (built.client.organization, built.client.project) == (ORG, ADO_PROJECT)


def test_a_non_azure_trackers_repo_is_never_borrowed_as_the_ado_project():
    """A Jira tracker's `repo` is a Jira key. Inheriting it would point this at a project that does
    not exist while looking configured — an ADO 404 blamed on the pipeline."""
    p = Project(name="fx-ado", repo_path="/tmp/fx-ado",
                tracker=ProviderRef(kind="jira", repo="FX"),
                forge=ProviderRef(kind="azure_devops", repo=REPO, options={"organization": ORG}))
    with pytest.raises(ValueError, match="organization and a project"):
        build_observer(p)


def test_the_github_token_the_call_sites_pass_never_reaches_azure(monkeypatch):
    """Both call sites hand this axis a GitHub credential, because until now every observer was
    GitHub's. Using it against dev.azure.com would surface as 401 — a configuration that is right
    reported as a permissions problem, the most expensive shape a mistake can take."""
    monkeypatch.delenv("AZURE_DEVOPS_PAT", raising=False)
    built = build_observer(_ado_project(), token="ghs_a_github_app_token")
    assert built.client.token is None


def test_the_observer_refuses_to_be_built_without_a_repository():
    """An ADO project holds many repositories, so an empty one would widen every query to the whole
    project and report another repository's builds as this one's. It fails at construction."""
    with pytest.raises(ValueError, match="repository"):
        AzurePipelinesObserver(organization=ORG, project=ADO_PROJECT, repo="")


def test_the_repository_may_be_registered_as_the_url_a_client_copied():
    obs = AzurePipelinesObserver(organization=ORG, project=ADO_PROJECT,
                                 repo=f"{ORG}/{ADO_PROJECT}/{REPO}", token="a-pat")
    assert obs.repo == REPO


def test_the_caller_may_pass_that_url_shaped_repo_too():
    """`ci_status(repo=…)` takes whatever the caller holds, which is the same registry value —
    normalising it in the constructor only would 404 on `git/repositories/org/project/repo`."""
    obs, recorded = _observer({"build/definitions": {"value": [DEFINITION]},
                               "build/builds": _builds(BUILD_RUNNING)})
    assert obs.ci_status(repo=f"{ORG}/{ADO_PROJECT}/{REPO}", ref="main")[0].status == "pending"
    assert [path for _m, path, _p in recorded.asked][0] == f"git/repositories/{REPO}"


def test_a_repository_without_an_id_refuses_to_widen_to_the_whole_project():
    """`repositoryId=` is not an error to Azure DevOps — it is every pipeline in the project. A 200
    that carries no id must stop here rather than answer about another repository's builds."""
    from openfactory.adapters.azure_devops import AzureDevOpsError

    obs, _ = _observer({f"git/repositories/{REPO}": {"name": REPO}})
    with pytest.raises(AzureDevOpsError, match="without an id"):
        obs.ci_status(repo=REPO, ref="main")


def test_a_malformed_health_url_is_false_rather_than_an_exception(monkeypatch):
    """`httpx.InvalidURL` is not an `HTTPError`, so catching only the latter lets a typo in a
    manifest abort the promotion it was meant to verify."""
    obs, _ = _observer({})
    monkeypatch.setattr(httpx, "get", lambda *a, **k: (_ for _ in ()).throw(
        httpx.InvalidURL("no host")))
    assert obs.health(url="http:///no-host") is False
