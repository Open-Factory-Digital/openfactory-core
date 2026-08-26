"""AzurePipelinesObserver — what Azure Pipelines says about a ref (read-only, ADR-0005 / D-12).

The platform triggers a merge or a tag and then OBSERVES the client's own pipeline; it never
deploys. So there is no queue-a-build call here and no deploy credential — every route below is a
GET, and the worst a stolen credential for this axis could do is read build history.

TWO FIELDS DECIDE A BUILD, AND READING ONE IS A BUG.

    status   notStarted | inProgress | postponed | cancelling | completed
    result   succeeded | partiallySucceeded | failed | canceled — ABSENT until completed

Observed live on a client Azure DevOps project, build 1: while it ran, the object had a `status` of
`inProgress` and NO `result` KEY AT ALL — not `null`, missing. An adapter that reads `result`
alone maps every running build to "not succeeded" — a red CI light on a build that is still
compiling, which on this platform escalates a job that had nothing wrong with it. `result` is read
ONLY once `status == "completed"`, and the same build after cancellation read
`{"status": "completed", "result": "canceled"}`.

THREE QUERY PARAMETERS THAT LIE, all found by asking the live API rather than the documentation:

    sourceVersion   SILENTLY IGNORED by `build/builds`. `?sourceVersion=deadbeef…` (a sha that
                    does not exist) returns the same build as the real one. Commit matching is
                    therefore done here, in Python, over a bounded window.
    branchName      matches ONLY the full ref: `branchName=main` returns 0 where
                    `branchName=refs/heads/main` returns the build. A caller that passes a bare
                    branch name would be told the pipeline never ran.
    queryOrder      `?queryOrder=bananas` is accepted and ignored, so a valid-looking order is not
                    evidence of an ordered answer. Newest-first is decided here.

ONE ADO PROJECT HOLDS MANY REPOSITORIES — unlike GitHub, where the repo IS the scope. Every route
in the Build API is project-scoped, so an unfiltered `build/definitions` in a multi-repo project
answers with pipelines belonging to other repositories too. Each query therefore carries the
`repositoryId` + `repositoryType` pair, and both are required: with a bogus type the server answers
"Repository type is missing/invalid" (an error, not a wrong answer), and without the pair it
answers about the whole project.
"""

from __future__ import annotations

import logging

import httpx

from openfactory.adapters.azure_devops import AzureDevOpsClient, AzureDevOpsError
from openfactory.adapters.environment.base import CheckStatus, EnvironmentObserver, Status

log = logging.getLogger("openfactory.environment.azure")

#: Azure Repos Git, as the Build API spells it in `repositoryType`. Verified rather than assumed:
#: the same route with `repositoryType=NOPE` answers 400 RepositoryInformationInvalidException.
REPO_TYPE = "TfsGit"

#: `result`, read only once the build is `completed`.
#:
#: `canceled` is a FAILURE and not "unknown", matching the forge's own rule ("a cancelled required
#: check must not read as green"). `partiallySucceeded` is a failure for the same reason and it is
#: the one genuinely arguable row: it means a step the pipeline author marked `continueOnError`
#: did fail. Reading it as success would have the platform announce "staging verified" about a
#: build Azure DevOps itself paints amber; reading it as failure stops and asks a human, which is
#: the cheaper mistake of the two and the one this codebase already makes elsewhere.
RESULT: dict[str, Status] = {
    "succeeded": "success",
    "partiallySucceeded": "failure",
    "failed": "failure",
    "canceled": "failure",
}

#: `status` values that mean "no verdict yet". `cancelling` is here on purpose: the build has not
#: finished, and it will land on `canceled` → failure a moment later through the map above.
PENDING_STATUS = frozenset({"notstarted", "inprogress", "postponed", "cancelling"})

#: How many builds to ask for. Generous on purpose, and for two different reasons: matching a
#: commit means scanning them here, and even the branch query is a WINDOW rather than an answer —
#: `$top` truncates, ordering is not guaranteed by the server (see `queryOrder` above), so a small
#: window on a busy repository could hold none of the recent builds.
BUILD_WINDOW = 200

#: How far back to look for a deployment to an environment. Deployment records carry no ref, so
#: this window is scanned and correlated with the builds of the ref (see `deploy_status`) — and
#: being a WINDOW rather than an answer, a full one is treated as possibly-truncated, never as
#: "this ref has not deployed" (`_page_starts_after`).
RECORD_WINDOW = 100


class AzurePipelinesObserver(EnvironmentObserver):
    """Read-only observation of one Azure Repos repository's pipelines.

    `organization`/`project` are ADO coordinates and `repo` is the repository inside that project —
    all three are required, because ADO nests one level deeper than GitHub and a missing repo would
    silently widen every query to the whole project's pipelines.
    """

    def __init__(self, *, organization: str, project: str, repo: str,
                 token: str | None = None, options: dict | None = None) -> None:
        self.repo = _repo_name(repo)
        if not self.repo:
            raise ValueError(
                "Azure Pipelines needs the repository whose pipelines to observe: an Azure DevOps "
                "project holds many repositories and every build route is project-scoped, so "
                "without it this would report another repository's builds as this one's. Set "
                "`forge.repo` for the project."
            )
        self.client = AzureDevOpsClient(
            organization=organization, project=project, token=token, options=options
        )
        self._repo_ids: dict[str, str] = {}

    # ── the port ────────────────────────────────────────────────────────────────────────────────

    def ci_status(self, *, repo: str, ref: str) -> list[CheckStatus]:
        """One row per pipeline configured for the repository, carrying its verdict on `ref`.

        THE EMPTY LIST MEANS ONE THING ONLY: this repository has no pipeline, so nothing will ever
        report on this ref and a watcher must stop waiting. A pipeline that exists but has not run
        for this ref is a `pending` row instead — the two were the same answer in the GitHub
        adapter, and collapsing them is what left a merge watch waiting for a verdict that was
        never coming. Here they are different values, and the ADO API makes the mistake easy: a
        repository with no definitions and a ref with no builds both answer `{"count": 0}`.
        """
        # The port lets the CALLER name the repository, and the same normalisation applies to it:
        # a caller holding `project.forge.repo` may be holding the URL path a client pasted, and
        # `git/repositories/{org}/{project}/fx-ado` is a 404 rather than a repository.
        name = _repo_name(repo) or self.repo
        repo_id = self._repo_id(name)
        definitions = self._definitions(repo_id)
        if not definitions:
            log.info(
                "OPENFACTORY_ADO_NO_PIPELINE repo=%s/%s — no build definition is configured for "
                "this "
                "repository, so no ref of it will ever report a check",
                self.client.project, name,
            )
            return []

        builds, window_exhausted = self._builds_for_ref(repo_id, ref)
        latest: dict[object, dict] = {}
        for build in _newest_first(builds):
            # A definition re-run leaves both builds in the answer. The newest is the verdict —
            # otherwise a failed first attempt keeps the ref red for ever after a green re-run.
            latest.setdefault((build.get("definition") or {}).get("id"), build)

        out: list[CheckStatus] = []
        for definition in definitions:
            build = latest.get(definition.get("id"))
            title = str(definition.get("name") or f"definition {definition.get('id')}")
            if build is not None:
                out.append(CheckStatus(name=title, status=_build_status(build, title),
                                       url=_web_url(build)))
            elif window_exhausted:
                # We looked and could not tell — which must never be reported as "not run yet".
                log.error(
                    "OPENFACTORY_ADO_SHA_WINDOW_EXHAUSTED repo=%s ref=%s — scanned the %d most "
                    "recent "
                    "builds without finding this commit; the pipeline %r may well have run for it. "
                    "Reporting unknown rather than pending so nothing waits on a verdict this "
                    "cannot see", name, ref, BUILD_WINDOW, title,
                )
                out.append(CheckStatus(name=title, status="unknown", url=_web_url(definition)))
            else:
                out.append(CheckStatus(name=title, status="pending", url=_web_url(definition)))
        return out

    def deploy_status(self, *, env: str, ref: str) -> Status:
        """Whether `ref` reached the Azure Pipelines environment `env`.

        A DEPLOYMENT RECORD DOES NOT CARRY THE REF. GitHub's Deployment names its own `ref` and
        `sha`; ADO's record names the environment, the stage, and the BUILD that deployed
        (`owner.id`). So the ref is resolved through the build: the builds of this ref are looked
        up first, and a record counts only when its owner is one of them. Skipping that
        correlation would answer "staging is green" using somebody else's commit.

        All four values are used, and each means something different:
            unknown   no environment by that name, or one nothing has ever deployed to
            pending   the environment receives deployments, but not yet from this ref
            success   the newest deployment of this ref finished green
            failure   it did not
        """
        wanted = (env or "").strip()
        environment = self._environment(wanted)
        if environment is None:
            known = [str(e.get("name")) for e in self.client.values("distributedtask/environments")]
            log.warning(
                "OPENFACTORY_ADO_NO_ENVIRONMENT env=%r project=%s — this project has no such "
                "environment, "
                "so nothing here can confirm a deploy to it; it declares: %s",
                wanted, self.client.project, ", ".join(known) or "none at all",
            )
            return "unknown"

        records = self.client.values(
            f"distributedtask/environments/{environment['id']}/environmentdeploymentrecords",
            # BOTH SPELLINGS, because the wrong one is ignored in silence and this page's size is
            # what `_page_starts_after` reads truncation from. `build/builds` was measured: `$top=2`
            # returns 2 and `top=2` returns all 7 — the unrecognised name is dropped, not rejected.
            # This route documents `top` while its sibling takes `$top`, and with a single record
            # live there was no way to tell which it honours. Sending both costs one query
            # parameter; guessing wrong costs a window that silently is not one.
            params={"$top": RECORD_WINDOW, "top": RECORD_WINDOW},
        )
        if not records:
            # A record is written when the deployment job is QUEUED (observed: a record existed
            # with a queueTime and no result while the job waited for an agent). So "no records at
            # all" cannot mean "in flight" — it means no pipeline has ever targeted this
            # environment, and calling that `pending` would wait for something nobody scheduled.
            log.warning(
                "OPENFACTORY_ADO_ENVIRONMENT_NEVER_DEPLOYED env=%s project=%s — the environment "
                "exists "
                "but no pipeline has ever deployed to it; no ref can be confirmed against it",
                wanted, self.client.project,
            )
            return "unknown"

        repo_id = self._repo_id(self.repo)
        builds, window_exhausted = self._builds_for_ref(repo_id, ref)
        build_ids = {b.get("id") for b in builds if b.get("id") is not None}
        mine = [r for r in records if (r.get("owner") or {}).get("id") in build_ids]
        if not mine:
            if window_exhausted:
                log.error(
                    "OPENFACTORY_ADO_SHA_WINDOW_EXHAUSTED env=%s ref=%s — could not find the build "
                    "for "
                    "this commit within the %d most recent, so whether it reached %s is unread, "
                    "not answered", wanted, ref, BUILD_WINDOW, wanted,
                )
                return "unknown"
            if _page_starts_after(records, builds):
                log.error(
                    "OPENFACTORY_ADO_RECORD_WINDOW_EXHAUSTED env=%s ref=%s — the %d most recent "
                    "deployment records all post-date this ref's newest build, so its own record "
                    "may have fallen off the end of them; reporting unknown rather than pending, "
                    "which would wait for a deploy that may already have happened",
                    wanted, ref, len(records),
                )
                return "unknown"
            log.info("OPENFACTORY_ADO_DEPLOY_PENDING env=%s ref=%s — the environment has "
                     "deployments, "
                     "none of them from this ref yet", wanted, ref)
            return "pending"
        return _record_status(_newest_record(mine), wanted)

    def health(self, *, url: str, timeout: int = 10) -> bool:
        """Probe the client's own health endpoint. Provider-independent by nature — it is their
        URL, not Azure's — and identical to every other observer's on purpose."""
        try:
            return httpx.get(url, timeout=timeout).is_success
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            # InvalidURL is NOT an HTTPError in httpx, so a malformed `health_url` in a client's
            # manifest would otherwise escape as an unhandled exception and take the whole
            # promotion with it — a typo in a URL failing a release that worked.
            log.warning("health probe %s failed: %s", url, exc)
            return False

    # ── internals ───────────────────────────────────────────────────────────────────────────────

    def _repo_id(self, name: str) -> str:
        """The repository's GUID, which is what the Build API's filters take. Cached per process.

        The route accepts the NAME (`git/repositories/fx-ado` → its id), and a name that does not
        exist raises out of the client — the caller learns the repository is wrong instead of
        being told its pipelines do not exist."""
        if name not in self._repo_ids:
            got = self.client.call("GET", f"git/repositories/{name}")
            found = str(got.get("id") or "")
            if not found:
                # An empty id would be sent as `repositoryId=` — which is not an error, it is the
                # WHOLE PROJECT: every other repository's pipelines answering as if they were this
                # one's. A 200 without an id is not something to carry on from.
                raise AzureDevOpsError(
                    f"GET git/repositories/{name} answered without an id, so there is no way to "
                    f"scope a build query to this repository; refusing to query the whole project"
                )
            self._repo_ids[name] = found
        return self._repo_ids[name]

    def _definitions(self, repo_id: str) -> list[dict]:
        return self.client.values(
            "build/definitions",
            params={"repositoryId": repo_id, "repositoryType": REPO_TYPE},
        )

    def _builds_for_ref(self, repo_id: str, ref: str) -> tuple[list[dict], bool]:
        """The builds of `ref`, and whether a sha scan ran out of window without finding it.

        A BRANCH IS ASKED OF THE SERVER, A SHA IS MATCHED HERE, and the branch is tried first for
        both: `branchName` is a real filter, `sourceVersion` is not (a nonexistent sha returns
        every build), so a wrong guess about which kind of ref this is would either miss builds or
        invent them. Trying the branch first also removes the guess entirely — a branch whose name
        happens to be hexadecimal answers correctly."""
        scope = {
            "repositoryId": repo_id,
            "repositoryType": REPO_TYPE,
            "$top": BUILD_WINDOW,
            # Sent because it is honoured when it is valid, and re-sorted below because an invalid
            # one is ignored in silence — so asking for an order is not evidence of getting one.
            "queryOrder": "queueTimeDescending",
        }
        wanted = (ref or "").strip()
        branch = wanted if wanted.startswith("refs/") else f"refs/heads/{wanted}"
        rows = self.client.values("build/builds", params={**scope, "branchName": branch})
        if rows or not _looks_like_sha(wanted):
            return rows, False

        window = self.client.values("build/builds", params=scope)
        needle = wanted.lower()
        hits = [b for b in window if str(b.get("sourceVersion") or "").lower().startswith(needle)]
        return hits, (not hits and len(window) >= BUILD_WINDOW)

    def _environment(self, name: str) -> dict | None:
        """The environment by exact name. The server's `name` filter is exact too (`name=stag`
        finds nothing when `staging` exists), but the comparison is repeated here so a difference
        in case cannot turn a real environment into "no such environment"."""
        rows = self.client.values("distributedtask/environments", params={"name": name})
        for row in rows:
            if str(row.get("name") or "").strip().lower() == name.lower():
                return row
        return None


# ── shape readers, kept pure so the recorded fixtures exercise exactly what the API sends ───────

def _repo_name(repo: str) -> str:
    """The repository's own name. A client may register it as `fx-ado` or as the path they copied
    out of the browser (`{org}/{project}/fx-ado`); ADO repository names cannot contain a
    slash, so the last segment is the name in both cases."""
    return (repo or "").strip().rstrip("/").rsplit("/", 1)[-1]


def _looks_like_sha(ref: str) -> bool:
    candidate = (ref or "").strip()
    return 7 <= len(candidate) <= 40 and all(c in "0123456789abcdefABCDEF" for c in candidate)


def _newest_first(builds: list[dict]) -> list[dict]:
    """Newest first, decided here because `queryOrder` is accepted-and-ignored when invalid and so
    proves nothing when valid. `id` is the tiebreaker: ADO build ids increase within a project."""
    return sorted(builds, key=lambda b: (str(b.get("queueTime") or ""), int(b.get("id") or 0)),
                  reverse=True)


def _page_starts_after(records: list[dict], builds: list[dict]) -> bool:
    """Whether the record page came back full AND begins after this ref's newest build.

    THE TWIN OF THE BUILD WINDOW, and the reason it needs two conditions rather than one. The
    records route takes no ref and no build filter — `$top` is the only bound on it — so "none of
    these records is mine" has two causes that look identical: the ref has not deployed, or its
    record scrolled off a page the server truncated. Only the first deserves `pending`.

    A full page whose OLDEST record still post-dates this ref's build is the unreadable case: a
    deploy of that build would sit before everything visible here. A page the server did not have
    to truncate is the whole history and answers honestly, which is why the length is checked too —
    without it every environment past its hundredth deploy would degrade to `unknown` for ever.
    """
    if len(records) < RECORD_WINDOW:
        return False
    newest_build = max((str(b.get("queueTime") or "") for b in builds), default="")
    oldest_record = min((str(r.get("queueTime") or r.get("startTime") or "")
                         for r in records), default="")
    return bool(newest_build and oldest_record and newest_build < oldest_record)


def _newest_record(records: list[dict]) -> dict:
    return sorted(records, key=lambda r: (str(r.get("startTime") or r.get("queueTime") or ""),
                                          int(r.get("id") or 0)), reverse=True)[0]


def _build_status(build: dict, title: str) -> Status:
    """`status` first, `result` only when completed — the whole point of this adapter."""
    status = str(build.get("status") or "").strip()
    if status.lower() != "completed":
        if status.lower() in PENDING_STATUS:
            return "pending"
        log.warning(
            "OPENFACTORY_ADO_UNKNOWN_BUILD_STATUS build=%s pipeline=%s status=%r — not a status "
            "this "
            "adapter knows; reporting unknown rather than guessing at a verdict",
            build.get("id"), title, status,
        )
        return "unknown"
    result = str(build.get("result") or "").strip()
    verdict = RESULT.get(result)
    if verdict is None:
        log.warning(
            "OPENFACTORY_ADO_UNKNOWN_BUILD_RESULT build=%s pipeline=%s result=%r — a completed "
            "build "
            "whose result this adapter cannot read; reporting unknown so it is neither green nor "
            "red by accident", build.get("id"), title, result,
        )
        return "unknown"
    return verdict


def _record_status(record: dict, env: str) -> Status:
    """A deployment record's verdict. Same two-field rule as a build, different spelling: the
    record carries `result` once it lands and nothing but timestamps while it runs."""
    result = str(record.get("result") or "").strip()
    if not result:
        return "pending"
    verdict = RESULT.get(result)
    if verdict is None:
        log.warning(
            "OPENFACTORY_ADO_UNKNOWN_DEPLOY_RESULT env=%s record=%s result=%r — reporting unknown; "
            "a "
            "deploy nobody can read must not pass as one that worked",
            env, record.get("id"), result,
        )
        return "unknown"
    return verdict


def _web_url(row: dict) -> str | None:
    """The `_links.web.href` ADO puts on builds, definitions and records — what a human opens."""
    return ((row.get("_links") or {}).get("web") or {}).get("href")
