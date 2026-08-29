"""AzureReposForge — branches, pull requests, merges and tags in Azure Repos.

The second vendor on the forge axis, written against the live API of a client Azure DevOps project
rather than against the reference docs. Four things it observed there are load-bearing, and each
one is a place where the GitHub shape would have produced a wrong adapter:

    A PR ID IS PROJECT-WIDE, NOT PER-REPOSITORY.  Proven: PR 2 was opened in one repository of
        the project and the next PR opened in `fx-ado` came back as 3 — one counter for the whole
        project. So a bare number is an unambiguous ref, and `git/pullrequests/{id}` (no repository
        segment) resolves it. But every WRITE route is repository-scoped, and asking the wrong
        repository for a valid id gives `404 TF401180`, not another PR. Hence `_pr`: resolve once
        through the project-scoped route, then address every write at the repository the PR itself
        names — never at `self.repo`. This is github.py's C-18 lesson (`update_branch` silently
        updating a same-numbered PR in the default repo) arriving before it could cost anything.

    COMPLETION IS ASYNCHRONOUS.  Proven: the PATCH that sets `status: completed` came back with
        `status: "active"` and `closedDate: null`; six seconds later the PR read `completed`. So
        `merge_pr` must not verify its own result, and a `pr_merged` immediately after a merge is
        legitimately False. The durable merge-watch already expects exactly that.

    `lastMergeCommit` IS NOT A MERGE.  Proven: PR 4 was abandoned without ever merging and still
        carried `lastMergeCommit.commitId: 15d18232…`; on PR 3 the value CHANGED at completion
        (807defdb… → 73531f4f…). Azure Repos publishes a speculative preview merge there to tell
        you whether the PR *would* merge. Reading it unconditionally would hand the post-merge
        deploy (ADR-0005) a commit that exists on no branch. `merge_commit_sha` therefore returns
        None unless the PR is `completed`.

    "CI EXISTS BUT NOTHING GATES THE MERGE" IS AZURE DEVOPS'S DEFAULT, NOT ITS EDGE CASE.  Proven:
        `fx-ado` has a real pipeline (`fx-ado-ci`) that builds `main`, and `policy/configurations`
        for the project is `[]`, so `policy/evaluations` for a live PR is `[]` too. Unlike GitHub
        Actions, a YAML `pr:` trigger does nothing for an Azure Repos repository — PR validation
        IS a branch policy. That makes the live defect github.py's `pr_ci_status` records ("a repo
        with CI but no branch protection must read `none`, not hang the merge watch") the NORMAL
        state here rather than a misconfiguration, so `none` is the answer this adapter gives most
        often and the merge watch must never wait on it.

Everything else follows the sibling. Where a decision was ours to make — merge strategy, what
happens to the source branch, who owns the work item's state — the reason is on the line.
"""

from __future__ import annotations

import logging
import re
import urllib.parse

from openfactory.adapters.azure_devops import AzureDevOpsClient, AzureDevOpsError
from openfactory.adapters.forge.base import ForgeAdapter, ReviewEvent
from openfactory.adapters.forge.base import truncated as _truncated

log = logging.getLogger("openfactory.forge.azure_devops")

#: The `policy/evaluations` route is preview-only at 7.1 and says so out loud — a plain
#: `api-version=7.1` answers `400: The requested version "7.1" … is under preview`. Pinned here
#: rather than bumping the client's global version, because every other route this adapter uses is
#: GA at 7.1 and dragging them all onto a preview contract to satisfy one of them is how a whole
#: adapter breaks on somebody else's release day.
POLICY_API_VERSION = "7.1-preview.1"

#: Azure Repos reviewer votes. The vocabulary is numeric and the middle values are real positions
#: a human takes, so the mapping from our three-valued `ReviewEvent` is lossy in one direction only.
VOTE_APPROVE = 10
VOTE_NO_VOTE = 0
VOTE_REJECT = -10

#: Clearing `autoCompleteSetBy` is done by writing the empty identity, not by writing null —
#: Azure DevOps ignores a null there. Verified live: the PATCH is accepted on a PR that was never
#: armed, which is what makes `disable_auto_merge` a safe no-op.
_NO_IDENTITY = "00000000-0000-0000-0000-000000000000"

_POLICY_BUCKET = {
    "approved": "pass",
    "rejected": "fail",
    "broken": "fail",       # the policy itself could not run — a gate we cannot read is not green
    "queued": "pending",
    "running": "pending",
    "notApplicable": "skip",
}


def _redact(text: str) -> str:
    """Strip any token embedded in an authenticated URL before it reaches a log or an error."""
    return re.sub(r"(https://)[^@/\s]+@", r"\1***@", text or "")


def _qualified(project: str, repo: str) -> str:
    """`project/repo` when the answer named a project, else the bare repo — for LINKS only."""
    return f"{project}/{repo}" if project else repo


def _branch_ref(name: str) -> str:
    """`refs/heads/<branch>`. Azure Repos rejects a bare branch name in a PR's
    source/targetRefName, and the platform passes bare names everywhere else."""
    n = (name or "").strip()
    return n if n.startswith("refs/") else f"refs/heads/{n}"


def _ci_status_from_evaluations(evaluations: list[dict]) -> str:
    """Aggregate branch-policy evaluations into the port's four-valued CI state.

    Same precedence as the GitHub sibling — fail beats pending beats pass — so a deployment that
    switches vendors sees the same decisions from the same facts. `notApplicable` is dropped
    rather than counted: it is Azure DevOps saying the policy does not apply to this PR at all,
    which is not evidence of anything.

    An EMPTY list is `none`, and that is the important case: it means no policy gates this merge,
    which in Azure DevOps is true of every project that has not explicitly configured build
    validation — including ones with a working pipeline.
    """
    buckets = [_POLICY_BUCKET.get(str(e.get("status") or ""), "pending") for e in evaluations]
    gating = [b for b in buckets if b != "skip"]
    if not gating:
        return "none"
    if "fail" in gating:
        return "failure"
    if "pending" in gating:
        return "pending"
    return "success"


class AzureReposForge(ForgeAdapter):
    """One Azure DevOps organisation/project/repository triple, as the forge axis."""

    def __init__(self, repo: str, *, organization: str, project: str,
                 token: str | None = None, token_provider=None,
                 options: dict | None = None) -> None:
        # A deployment that filled the generic "owner/name" field gets the repository out of it.
        # Safe because an Azure Repos repository name cannot contain a slash, so there is nothing
        # this can silently truncate.
        self.repo = (repo or "").strip().strip("/").rsplit("/", 1)[-1]
        self.organization = (organization or "").strip()
        self.project = (project or "").strip()
        self._options = dict(options or {})
        self._static_token = token
        self._token_provider = token_provider
        self._repo_guid = ""  # filled by `_repository_id`, which explains why it is cacheable
        if not self.repo:
            raise ValueError(
                "Azure Repos needs a repository name — set `forge.repo` (or the tracker's, which "
                "it falls back to). Without one every route below would be built against an empty "
                "path segment and answer 404 as if the repository had been deleted."
            )

    # ---- credential + client ------------------------------------------------------------------

    @property
    def token(self) -> str | None:
        """Resolved at each use, like the GitHub sibling: an `az account get-access-token` JWT
        lasts about an hour and a job can outlive it, so a token captured at construction is a
        job that pushes fine and then cannot open its PR."""
        return self._token_provider() if self._token_provider else self._static_token

    def _client(self) -> AzureDevOpsClient:
        """A client carrying the CURRENT credential. Constructed per call and never cached: the
        object would hold a token from before the last refresh, and a cache that goes stale at its
        own write is a defect this codebase has already paid for once. Construction is pure —
        string handling, no I/O — so there is nothing to save by keeping one."""
        return AzureDevOpsClient(organization=self.organization, project=self.project,
                                 token=self.token, options=self._options)

    def _client_for(self, repo: str) -> AzureDevOpsClient:
        """A client scoped to the PROJECT the ref names, falling back to this adapter's own.

        Every repository route on this vendor is project-scoped, and `_repo_or_self` throws the
        qualifier away — right for C-18, whose refs qualify with this adapter's own project, and
        wrong for the one caller that legitimately points elsewhere: the CONTEXT repository. A
        client may keep documentation in a shared project of the same organisation, and a
        deployment has both shapes at once — measured on a real enterprise organisation, where
        some projects keep a documentation repository and others do not. Aimed at the wrong
        project the call answers 404 — a repository somebody
        can see in their browser, reported missing."""
        where = (repo or "").strip().strip("/").rpartition("/")[0].strip() or self.project
        if where == self.project:
            return self._client()
        return AzureDevOpsClient(organization=self.organization, project=where,
                                 token=self.token, options=self._options)

    # ---- refs ---------------------------------------------------------------------------------

    def push_remote(self) -> str | None:
        """An HTTPS remote carrying the credential, for the FRAMEWORK's own push.

        ONE SCHEME FOR BOTH TOKEN SHAPES. Over git, Azure DevOps reads the credential out of the
        Basic-auth password field whether it is a PAT or an AAD JWT — the `Bearer` vs `Basic`
        distinction the REST client makes has no equivalent on the git wire, where there is only
        Basic. Verified live against `fx-ado` with a JWT: clone, then two pushes, one with the
        organisation as the username and one with the username empty; both were accepted.

        The username is the organisation because that is what Azure DevOps itself puts in the
        `remoteUrl` it returns for a repository — so this URL, with the token redacted, is byte
        for byte the one a human would copy out of the portal.
        """
        token = self.token
        if not token:
            return None
        # Percent-encoded because the credential lands in the userinfo of a URL: a PAT is opaque
        # and a deployment may paste one containing a character that would otherwise end the field
        # early and produce a "repository not found" instead of an auth error.
        cred = urllib.parse.quote(token, safe="")
        org = urllib.parse.quote(self.organization, safe="")
        proj = urllib.parse.quote(self.project, safe="")
        # The repository is quoted like every other path segment here: Azure DevOps allows spaces
        # in a repository name, and a raw space in the remote URL ends the argument `git push`
        # sees — a repository "not found" for a repository that is right there.
        return (f"https://{org}:{cred}@dev.azure.com/{org}/{proj}/_git/"
                f"{urllib.parse.quote(self.repo)}")

    @staticmethod
    def _project_of(pr_data: dict) -> str:
        """Which ADO project the pull request lives in, as the answer reports it — or "".

        SEPARATE FROM `_repo_of` BECAUSE THEY ARE READ IN DIFFERENT PLACES. That one is a path
        SEGMENT on every write (`git/repositories/{name}/…`), so it must stay a bare name — a
        qualified value there produces a route with a slash in it, which two existing guards
        caught the moment it was tried. This one is only ever composed into the human-facing
        page, where the project is exactly what was missing for a context repository living in
        another project of the same organisation (pre-commit review, 2026-08-12)."""
        return (((pr_data.get("repository") or {}).get("project") or {}).get("name") or "").strip()

    def _web_url(self, *, repo: str, pr_id: int) -> str:
        """The PR's page. Composed from the shape Azure DevOps returns as `repository.webUrl`
        (`https://dev.azure.com/{org}/{project}/_git/{repo}`), because the `url` on a PR is the
        REST resource and putting that in front of a human is a JSON dump, not a pull request.

        THE PROJECT COMES FROM THE REF WHEN THE REF CARRIES ONE. A context repository may live in
        another project of the same organisation, and composing its page from this adapter's own
        project hands somebody a 404 for a pull request that exists — the link being the ONE
        thing they were given to act on (pre-commit review, 2026-08-12)."""
        org = urllib.parse.quote(self.organization, safe="")
        qualifier, _, leaf = (repo or "").strip().strip("/").rpartition("/")
        proj = urllib.parse.quote(qualifier.strip() or self.project, safe="")
        return (f"https://dev.azure.com/{org}/{proj}/_git/{urllib.parse.quote(leaf or repo)}"
                f"/pullrequest/{pr_id}")

    # ---- addressing a pull request, and a repository -------------------------------------------

    def _pr_id(self, pr: str) -> int:
        """The numeric id out of a PR URL or a bare number.

        RAISES on anything else rather than defaulting. Every caller of this is about to decide
        whether a client's work merged; a ref we cannot parse is not a PR we can report on, and
        guessing zero would ask about a PR that does not exist and read the 404 as "not merged"."""
        raw = str(pr or "").strip()
        candidate = urllib.parse.urlsplit(raw).path.rstrip("/").rsplit("/", 1)[-1] if "/" in raw \
            else raw
        if not candidate.isdigit():
            raise ValueError(
                f"{pr!r} is not an Azure Repos pull request ref — expected a number or a URL "
                f"ending in /pullrequest/<id>"
            )
        return int(candidate)

    def _pr(self, pr: str, *, repo: str = "") -> dict:
        """The PR, read through the PROJECT-scoped route so it resolves whichever repository in
        the project it actually lives in. Ids are project-wide (proven live), and this is the only
        route that does not need to be told the repository up front.

        `repo` IS ACCEPTED AND DOES NOT ADDRESS ANYTHING, WHICH IS WORTH A PARAGRAPH RATHER THAN
        A SHRUG. The port gives `pr_status`/`merge_pr` a `repo` so the product path can name the
        documentation repository it means; on this vendor the id already answers that. Measured
        on a live client project (2026-08-06), by opening PR 13 in another repository of that same
        project (`{other-repo}`) from an adapter configured for `fx-ado`:

            GET git/pullrequests/13   project-scoped   → repository.name = "{other-repo}"
            GET git/repositories/fx-ado/pullrequests/13 → 404 TF401180, the WRONG repository
            GET git/pullrequests/13   wrong project    → 404 TF401019

        That last code contains "401" and is a 404 about a repository — it has already been read
        once this week as a refused credential, so it is written down here rather than rediscovered
        at 2am. The repository-scoped route is the one that cannot resolve a valid id, so this uses
        the project-scoped one and the PR's own `repository.name` decides every write.

        A DISAGREEMENT IS LOGGED, NEVER ACTED ON. If a caller names a repository the PR does not
        live in, the pull request wins — the caller identified the PR by id, and that id is
        unambiguous across the project — but the mismatch is a caller holding a false belief and
        must not be silent. GitHub does the same thing without telling anybody: `gh pr view <url>
        --repo <other>` answers the URL's repository and never mentions the flag."""
        data = self._client().call("GET", f"git/pullrequests/{self._pr_id(pr)}")
        wanted = (repo or "").strip().strip("/").rsplit("/", 1)[-1]
        if wanted:
            actual = ((data.get("repository") or {}).get("name") or "").strip()
            if actual and actual.lower() != wanted.lower():
                log.warning("PR %s lives in %s, not in %s as the caller said — acting on %s, "
                            "because a project-wide id is what identifies a pull request here "
                            "and the repository name is not", pr, actual, wanted, actual)
        return data

    @staticmethod
    def _repo_of(pr_data: dict) -> str:
        """The repository the PR belongs to, as the PR itself reports it.

        Not `self.repo`: one Azure DevOps project holds many repositories and one deployment may
        drive several of them, so a PR handed to this adapter is not guaranteed to live in the one
        it was configured with. Addressing a write at the wrong repository answers 404 TF401180
        (verified), which is survivable — but only because we never write blind."""
        name = ((pr_data.get("repository") or {}).get("name") or "").strip()
        if not name:
            raise AzureDevOpsError(
                "the pull request came back without a repository — refusing to fall back to the "
                "configured one, because a write aimed at the wrong repository in the same "
                "project is exactly the mistake this lookup exists to prevent"
            )
        return name

    def authenticated_url(self, url: str) -> str:
        """`url` with the credential in the Basic password field, if it is on dev.azure.com.

        THE USERNAME IS THE ORGANISATION, as in `push_remote` and for the same reason: it is what
        Azure DevOps itself returns in a repository's `remoteUrl`, so the result is byte for byte
        what a human would copy out of the portal. GitHub's `x-access-token` spelling happens to
        be accepted here — Azure ignores the username — which is exactly why the neutral helper
        this replaces looked like it worked on an Azure deployment while sending the wrong
        system's token whenever the right one was absent."""
        from openfactory.adapters.forge.base import carries_credentials, host_of

        token = self.token
        if not token or carries_credentials(url) or host_of(url) != "dev.azure.com":
            return url
        cred = urllib.parse.quote(token, safe="")
        org = urllib.parse.quote(self.organization, safe="")
        return url.replace("https://", f"https://{org}:{cred}@", 1)

    def clone_url(self, repo: str, *, token: str | None) -> str:
        """`https://<user>:<token>@dev.azure.com/{org}/{project}/_git/{repo}`.

        THREE COORDINATES, NOT TWO. GitHub's `owner/name` addresses a repository completely; Azure
        DevOps nests `organization / project / repository`, so a clone URL built from the repo name
        alone points at nothing. That is why `repo` is reduced to its LAST segment here: C-18 hands
        this a qualified `project/repo` ref, and the project is already in the URL from this
        adapter's own coordinates.

        The user half of the credential is ignored by Azure DevOps — any non-empty value works —
        but it cannot be EMPTY, which is the shape `push_remote` already settled and the reason
        this does not simply reuse GitHub's `x-access-token` spelling by accident."""
        # VALIDATED, because a missing coordinate here is silent. The shared client raises on an
        # empty organization or project; this method builds the URL by hand and did not, so a row
        # with no `organization` produced `https://dev.azure.com//{project}/_git/fx-ado` — a
        # double slash and a 404 that reads like a repository somebody forgot to create. Found by
        # a test written for a different defect, which is the usual way.
        if not self.organization or not self.project:
            raise ValueError(
                "cannot build an Azure Repos clone URL without both an organization and a project "
                f"— its paths nest organization/project/_git/repository. Got "
                f"organization={self.organization!r}, project={self.project!r}; declare them under "
                f"the forge's `options`."
            )
        # A QUALIFIER THAT NAMES ANOTHER PROJECT IS OBEYED, NOT DROPPED. C-18 hands this
        # `project/repo` where the project IS this adapter's, so reducing to the leaf was right
        # for every caller that existed — until the product module asked for a CONTEXT
        # repository, which a client may well keep in a different project of the same
        # organisation — an enterprise deployment has both shapes at once, projects with a docs
        # repository and projects without. Dropping the qualifier there clones a same-named one in
        # the wrong project, or 404s as if somebody forgot to create it.
        wanted = (repo or self.repo or "").strip().strip("/")
        head, _, leaf = wanted.rpartition("/")
        name = leaf or wanted
        # THE QUALIFIER IS OBEYED ONLY WHEN IT ADDRESSES A DIFFERENT REPOSITORY. A registry row
        # that filled the generic `owner/name` field on an Azure axis — a misconfiguration this
        # adapter's own constructor tolerates by reducing to the leaf — would otherwise have its
        # OWNER read as an ADO project and every clone aimed somewhere that does not exist.
        # Cross-project addressing is a real need (a shared documentation project); silently
        # re-reading the adapter's own coordinates is not.
        where = head.strip() if (head.strip() and name != self.repo) else self.project
        base = (f"dev.azure.com/{urllib.parse.quote(self.organization)}"
                f"/{urllib.parse.quote(where)}/_git/{urllib.parse.quote(name)}")
        if token:
            return f"https://openfactory:{token}@{base}"
        return f"https://{base}"

    # ---- reading an ARBITRARY repository -------------------------------------------------------

    def _repo_or_self(self, repo: str) -> str:
        """The repository name the caller meant. "" is this adapter's own.

        REDUCED TO ITS LAST SEGMENT, exactly as `clone_url` does and for the same reason: C-18
        hands qualified `project/repo` refs around, and the project is already one of this
        adapter's own coordinates. An Azure Repos repository name cannot contain a slash, so
        there is nothing here that a legitimate name could lose."""
        return (repo or "").strip().strip("/").rsplit("/", 1)[-1] or self.repo

    def list_branches(self, repo: str = "", *, prefix: str = "") -> list[str] | None:
        """Bare branch names, filtered server-side. `[]` = none match; `None` = could not read.

        `filter` IS A PREFIX AND IT REALLY DOES NARROW SERVER-SIDE — verified live on `fx-ado`:
        `filter=heads/` returned all seven heads, `filter=heads/probe/` returned exactly the three
        under it, and `filter=heads/nosuch/` returned `{"value": [], "count": 0}`. That last one
        is what makes the empty answer trustworthy: an unmatched prefix is an empty COLLECTION,
        not an error, while a repository that does not exist is `404 TF401019` — so the two
        answers this method has to keep apart are already kept apart by the server.

        The `refs/heads/` prefix is stripped because the port hands bare names everywhere; on this
        adapter `_branch_ref` is the one place that puts it back.

        THE SHAPE IS CHECKED HERE RATHER THAN LEFT TO `values()`, and that is the only reason this
        does not go through the client's collection helper like everything else in this file.
        `AzureDevOpsClient.values()` ends `return out if isinstance(out, list) else []` — so an
        answer whose `value` is missing or is not a list arrives as an EMPTY COLLECTION, which is
        this port's word for "I read the repository and there is nothing in it". `call()` already
        raises on a non-JSON body and on every HTTP error, but a 200 or 204 carrying no body at all
        comes back as `{}` and lands squarely in that hole. The GitHub sibling answers None for
        exactly these shapes and has a named test for it; a port whose two providers disagree about
        which answer means "unreadable" is not a port, and the caller that believes the empty one
        mints a requirement number a live `req/*` branch already claims.
        """
        target = self._repo_or_self(repo)
        try:
            answer = self._client_for(repo).call(
                "GET", f"git/repositories/{urllib.parse.quote(target)}/refs",
                params={"filter": f"heads/{(prefix or '').lstrip('/')}"})
        except (AzureDevOpsError, ValueError) as exc:
            log.warning("could not list the branches of %s (%s)", target, str(exc)[:200])
            return None
        refs = answer.get("value")
        if not isinstance(refs, list):
            log.warning("the refs of %s came back without a `value` collection (%s) — reporting "
                        "the repository as unreadable rather than as empty", target,
                        type(refs).__name__)
            return None
        names = [str(r.get("name") or "").removeprefix("refs/heads/")
                 for r in refs if isinstance(r, dict)]
        return [n for n in names if n]

    def delete_branch(self, name: str, *, repo: str = "") -> bool:
        """True when the branch is gone, False when it may still be there. See the port.

        A DELETE IS A REF UPDATE TO FORTY ZEROES, and the live API answers three different words
        for what looks like one outcome. All three were produced against `fx-ado` on 2026-08-06,
        by creating a scratch ref and taking it apart again:

            succeeded               the ref was there at the object id we named, and is gone
            succeededCorruptRef     the ref was there at a DIFFERENT id, and is gone anyway
            succeededNonExistentRef there was no such ref; nothing was deleted

        `oldObjectId` IS SENT AS ZEROES ON PURPOSE, and the middle line above is why that is a
        decision rather than laziness. Azure Repos would happily do a compare-and-swap if we read
        the branch's head first and named it — it answers `succeededCorruptRef` precisely because
        we did not. But GitHub's `DELETE git/refs/heads/<b>` has no conditional form at all, so
        making this one conditional would give the SAME port call two different meanings on two
        vendors: on Azure a branch that moved since we read it survives, on GitHub it does not.
        A provider is configuration; a provider that quietly changes whether work can be lost is
        not. One unconditional delete, both vendors, and the difference stays in this comment
        instead of in a client's repository.

        THE HTTP STATUS IS NOT THE VERDICT. All of the above come back as `200 OK` with the real
        answer in `value[0].success` — a provider that trusted the status code would report a
        `permissionDenied` as a successful cleanup. Anything that is not an explicit success is
        False, with the server's own word in the log so the refusal is findable.
        """
        branch = (name or "").strip().strip("/")
        if not branch:
            log.warning("refusing to delete an unnamed branch in %s", self._repo_or_self(repo))
            return False
        target = self._repo_or_self(repo)
        zero = "0" * 40
        try:
            answer = self._client().call(
                "POST", f"git/repositories/{urllib.parse.quote(target)}/refs",
                body=[{"name": _branch_ref(branch), "oldObjectId": zero, "newObjectId": zero}])
        except (AzureDevOpsError, ValueError) as exc:
            log.warning("could not delete %s in %s (%s)", branch, target, str(exc)[:200])
            return False
        rows = answer.get("value") if isinstance(answer.get("value"), list) else []
        if not rows:
            # An empty result is not an act. Reporting it as gone would drop the branch out of the
            # sweep's attention on no evidence whatsoever.
            log.warning("the ref update for %s in %s came back with no result — reporting it as "
                        "still there", branch, target)
            return False
        row = rows[0] or {}
        status = str(row.get("updateStatus") or "")
        if not row.get("success"):
            log.warning("Azure DevOps refused to delete %s in %s: %s", branch, target,
                        status or "no updateStatus")
            return False
        if status == "succeededNonExistentRef":
            log.info("%s was already gone from %s — nothing to delete", branch, target)
        return True

    def pr_for_head(self, head: str, *, repo: str = "") -> str | None:
        """The newest pull request opened from `head`, any state. "" = none; None = unreadable.

        `searchCriteria.status=all` IS NOT OPTIONAL, and leaving it out is a silent wrong answer
        rather than an error. The route defaults to ACTIVE: asked about `probe/abandon` on
        `fx-ado` with no status it answered `count: 0`, and with `status=all` it answered three
        pull requests — 7 abandoned, 6 completed, 4 abandoned. A caller checking "was this branch
        ever proposed" would have been told no about a branch proposed three times.

        The bare branch name is ALSO a silent zero: `sourceRefName=probe/abandon` answers
        `count: 0` where `refs/heads/probe/abandon` answers three. Hence `_branch_ref`.

        Newest by pull request id, which is monotonic across the project (the adapter's own module
        docstring proves it) — and the server already returned them 7, 6, 4, so this agrees with
        its ordering rather than overriding it.

        The shape is checked here rather than left to `values()`, for the reason `list_branches`
        argues at length: that helper turns an answer it cannot recognise into an empty list, and
        an empty list here becomes `""` — "this branch was never proposed" — which is the one
        answer that makes the caller open a second pull request for work already in flight.
        """
        target = self._repo_or_self(repo)
        try:
            answer = self._client_for(repo).call(
                "GET", f"git/repositories/{urllib.parse.quote(target)}/pullrequests",
                params={"searchCriteria.sourceRefName": _branch_ref(head),
                        "searchCriteria.status": "all"})
        except (AzureDevOpsError, ValueError) as exc:
            log.warning("could not look up the pull requests for %s in %s (%s)",
                        head, target, str(exc)[:200])
            return None
        found = answer.get("value")
        if not isinstance(found, list):
            log.warning("the pull requests for %s in %s came back without a `value` collection "
                        "(%s) — unreadable, not absent", head, target, type(found).__name__)
            return None
        if not found:
            return ""
        rows = [p for p in found if isinstance(p, dict)]
        if not rows:
            # Rows we cannot even index are not an absence of pull requests.
            log.warning("the pull requests for %s in %s came back as %d rows this adapter cannot "
                        "read", head, target, len(found))
            return None
        try:
            newest = max(rows, key=lambda p: int(p.get("pullRequestId") or 0))
            return self._web_url(
                repo=_qualified(self._project_of(newest), self._repo_of(newest)),
                pr_id=int(newest["pullRequestId"]))
        except (AzureDevOpsError, KeyError, TypeError, ValueError) as exc:
            # A pull request we cannot address is not an absent one — "" here would send the
            # caller off to open a duplicate.
            log.warning("the pull requests for %s in %s came back in a shape this adapter cannot "
                        "address (%s)", head, target, str(exc)[:200])
            return None

    # ---- pull requests ------------------------------------------------------------------------

    def open_pr(self, *, head: str, base: str, title: str, body: str, repo: str = "") -> str:
        """Open a PR in `repo` ("" = this adapter's own) and return its URL. Idempotent (D-16): an
        ACTIVE PR already open from this branch is returned instead of a second one — a retried
        activity must not double-file.

        `repo` IS LOAD-BEARING HERE IN A WAY IT IS NOT ON `pr_status`, and the difference is that
        this is a CREATE: there is no id yet to resolve the repository from, so the route has to be
        told. `POST git/repositories/{repo}/pullrequests` is repository-scoped and so is the
        idempotency lookup below it — both follow `repo`, because a check aimed at `self.repo`
        would answer "no PR" about every proposal in the documentation repository and this method
        would file a second one every time.

        THE BODY IS STORED VERBATIM, AND THAT WAS MEASURED RATHER THAN ASSUMED. Azure Boards
        HTML-sanitises every long-text write, so `System.Description` silently truncates at the
        first unterminated `<` — the tracker adapter carries a converter for exactly that. The Git
        API is a different resource and the question was open, which mattered: a code-review
        comment saying `if (a<b) { x }` losing everything after the `<` is the shape a reviewer
        would never think to check, because the ticket path had already taught them the opposite.

        Probed live on fx-ado PR #8 (2026-08-06): a description and a thread comment each carrying
        a fenced java block, a bare `<placeholder>` and `List<String>` both round-tripped
        byte-identical. So no conversion here — and none should be added, because converting text
        that is already stored as written is how the `<` gets lost by our own hand."""
        target = self._repo_or_self(repo)
        client = self._client_for(repo)
        existing = self._open_pr_for_head(head, repo=repo or target)
        if existing:
            return existing
        payload = {
            "sourceRefName": _branch_ref(head),
            "targetRefName": _branch_ref(base),
            "title": title,
            # THE VENDOR'S CEILING, ON THE PATH THAT RUNS FIRST. See `_fit_description`.
            "description": self._fit_description(body),
        }
        try:
            created = client.call(
                "POST", f"git/repositories/{urllib.parse.quote(target)}/pullrequests",
                body=payload)
        except AzureDevOpsError as exc:
            # Lost a race with a concurrent create? Azure DevOps refuses the second PR for a
            # branch pair, so the winner is findable — and returning it is the whole point of
            # idempotency. If the recovery lookup ALSO fails we raise the original, because the
            # caller treating this as "no PR" is the one path that files a duplicate.
            try:
                recovered = self._open_pr_for_head(head, repo=repo or target)
            except (AzureDevOpsError, ValueError) as look:
                log.warning("could not recover the PR for %s after a failed create (%s)",
                            head, str(look)[:160])
                recovered = None
            if recovered:
                log.info("the create was refused for %s (%s) and an active PR already exists — "
                         "using it", head, _redact(str(exc))[:160])
                return recovered
            raise
        return self._web_url(
                repo=_qualified(self._project_of(created), self._repo_of(created)),
                pr_id=int(created["pullRequestId"]))

    def _open_pr_for_head(self, head: str, *, repo: str = "") -> str | None:
        """The ACTIVE PR opened from `head` in `repo` ("" = this adapter's own), or None. A FAILED
        lookup raises rather than answering None: "I could not read" and "there is none" lead to
        opposite actions here.

        RENAMED AWAY FROM `_pr_for_head` when the public `pr_for_head` arrived. The two differ by
        one underscore and disagree on both axes: this one asks only about ACTIVE pull requests
        (an abandoned PR must not stop a fresh one being opened) and raises when it cannot read;
        the public one asks about every state and returns None when it cannot read. Neighbouring
        methods with inverted sentinels get told apart by a duplicate PR in production, so they
        are told apart by their names instead.

        THE SHAPE IS CHECKED HERE RATHER THAN LEFT TO `values()`, and this is the method where
        getting it wrong actually costs something. `list_branches` and `pr_for_head` each argue
        the point at length two screens up and both hand-roll the check; THIS one — the gate that
        decides whether `open_pr` CREATES a pull request — went through the helper, and the helper
        ends `return out if isinstance(out, list) else []`. `call()` raises on every HTTP error and
        on a non-JSON body, but a 200 or 204 carrying no body at all comes back as `{}`, so an
        answer this adapter could not read arrived as an empty COLLECTION and this returned None:
        "no pull request is open from that branch". That is the single answer that makes `open_pr`
        POST a second one. Driven against the real adapter with a client returning `{}`, `open_pr`
        created a pull request off an idempotency lookup that had read nothing.

        SO IT RAISES, which is this method's stated contract and also what the sibling provider
        already does — `gh pr list --jq '.[0].url'` exits 1 with "expected an array but got:
        object" (measured), and GitHub's `_open_pr_for_head` turns that into a RuntimeError. The
        port's own `_gh_read` docstring says two providers behind one port must fail in the same
        vocabulary; here they did not, and only the vendor that hosts the client's documentation
        repository was the lenient one."""
        answer = self._client_for(repo).call(
            "GET", f"git/repositories/{urllib.parse.quote(self._repo_or_self(repo))}/pullrequests",
            params={"searchCriteria.status": "active",
                    "searchCriteria.sourceRefName": _branch_ref(head)},
        )
        found = answer.get("value")
        if not isinstance(found, list):
            raise AzureDevOpsError(
                f"the active pull requests for {head} in "
                f"{self._repo_or_self(repo)} came back without a `value` collection "
                f"({type(found).__name__}) — refusing to read that as 'nothing is open', because "
                f"the only thing this lookup is for is deciding whether to open another one"
            )
        if not found:
            return None
        pr = found[0]
        return self._web_url(
                repo=_qualified(self._project_of(pr), self._repo_of(pr)),
                pr_id=int(pr["pullRequestId"]))

    def review_pr(self, *, pr: str, event: ReviewEvent, body: str) -> None:
        """The reviewer's verdict as a real review: a comment thread, plus a vote when the verdict
        is one.

        TWO CALLS BECAUSE AZURE DEVOPS SPLITS WHAT GITHUB JOINS. A GitHub review carries a body
        and a state together; here the prose is a thread and the position is a number on the
        reviewer row, and there is no route that writes both.

        The thread is left ACTIVE for `request-changes` and closed otherwise, so an unresolved
        comment is visibly unresolved — an approval that leaves an open thread reads, in the
        Azure DevOps UI, as an objection nobody answered.

        A plain `comment` casts NO vote at all. Voting 0 would add the bot to the PR's reviewer
        list with no position, which shows up as a reviewer who never answered — worse than
        silence, because it looks like a person who is still deciding.
        """
        client = self._client()
        pr_data = self._pr(pr)
        repo = urllib.parse.quote(self._repo_of(pr_data))
        pr_id = int(pr_data["pullRequestId"])
        client.call(
            "POST", f"git/repositories/{repo}/pullrequests/{pr_id}/threads",
            body={"comments": [{"parentCommentId": 0, "content": body, "commentType": "text"}],
                  "status": "active" if event == "request-changes" else "closed"},
        )
        vote = {"approve": VOTE_APPROVE, "request-changes": VOTE_REJECT}.get(event)
        if vote is None:
            return
        client.call(
            "PUT", f"git/repositories/{repo}/pullrequests/{pr_id}/reviewers/{self._me(client)}",
            body={"vote": vote},
        )

    def _me(self, client: AzureDevOpsClient) -> str:
        """The identity id of whoever this credential is. Needed to cast a vote and to arm
        auto-complete: Azure DevOps records both against a person, and will not let one identity
        set them on behalf of another. `connectionData` is preview-only at 7.1, like the policy
        route."""
        data = client.call("GET", "connectionData", project_scoped=False,
                           api_version=POLICY_API_VERSION)
        me = ((data.get("authenticatedUser") or {}).get("id") or "").strip()
        if not me:
            raise AzureDevOpsError(
                "could not read which identity this Azure DevOps credential belongs to "
                "(connectionData returned no authenticatedUser) — a vote and an auto-complete "
                "arming both have to be attributed to somebody, so this cannot proceed silently"
            )
        return me

    def request_reviewers(self, *, pr: str, reviewers: list[str]) -> None:
        """Add human reviewers — the default human-on-PR path.

        AZURE DEVOPS ADDRESSES PEOPLE BY GUID, NOT BY LOGIN, so a name has to be resolved first.
        Every reviewer is resolved BEFORE anything is written: a partial application would leave
        the PR with some of the humans it was supposed to have and raise anyway, and the one thing
        worse than nobody being asked to review is thinking somebody was.
        """
        wanted = [r.strip() for r in (reviewers or []) if r and r.strip()]
        if not wanted:
            return
        client = self._client()
        ids = self._resolve_identities(client, wanted)
        pr_data = self._pr(pr)
        repo = urllib.parse.quote(self._repo_of(pr_data))
        pr_id = int(pr_data["pullRequestId"])
        for identity in ids:
            client.call(
                "PUT", f"git/repositories/{repo}/pullrequests/{pr_id}/reviewers/{identity}",
                body={"vote": VOTE_NO_VOTE, "isRequired": True},
            )

    def _resolve_identities(self, client: AzureDevOpsClient, names: list[str]) -> list[str]:
        """Reviewer names → identity GUIDs, via the project's teams.

        A GUID passes through untouched. Anything else is matched, case-insensitively, against the
        `uniqueName` (the sign-in address) and the `displayName` of every member of every team in
        the project — the only membership route that lives on `dev.azure.com` alongside the rest
        of this adapter, rather than on the separate `vssps` identity host.

        AN UNRESOLVED NAME RAISES, naming what the project does offer. The alternative is a
        reviewer request that quietly asks nobody, which is the silent failure the whole
        human-on-PR path exists to avoid.
        """
        guid = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
        pending = [n for n in names if not guid.match(n)]
        if not pending:
            return list(names)
        directory: dict[str, str] = {}
        for team in client.values(f"projects/{urllib.parse.quote(self.project)}/teams",
                                  project_scoped=False):
            members = client.values(
                f"projects/{urllib.parse.quote(self.project)}/teams/{team['id']}/members",
                project_scoped=False)
            for member in members:
                identity = member.get("identity") or {}
                ident_id = (identity.get("id") or "").strip()
                if not ident_id:
                    continue
                for key in (identity.get("uniqueName"), identity.get("displayName")):
                    if key:
                        directory[str(key).strip().lower()] = ident_id
        resolved, missing = [], []
        for name in names:
            if guid.match(name):
                resolved.append(name)
                continue
            found = directory.get(name.lower())
            (resolved if found else missing).append(found or name)
        if missing:
            raise AzureDevOpsError(
                f"cannot request a review from {', '.join(missing)} — Azure DevOps identifies "
                f"reviewers by identity id and no member of this project's teams matches that "
                f"sign-in address or display name. Known: {', '.join(sorted(directory)) or 'none'}"
            )
        return resolved

    def _completion_options(self, *, bypass: str = "") -> dict:
        """What a completed PR does to the repository. Three deliberate choices:

        SQUASH, because the GitHub sibling merges `--squash`. A provider is configuration, and a
        configuration change must not silently rewrite what a client's history looks like. It also
        keeps `merge_commit_sha` honest: one commit lands on the base, and that is the exact
        commit the post-merge deploy runs on (ADR-0005).

        THE SOURCE BRANCH SURVIVES, for the same reason `close_pr` leaves it: the work has to be
        recoverable, so nothing here deletes.

        WORK ITEMS ARE NOT TRANSITIONED. Azure DevOps will happily move every work item linked to
        the PR when it completes, and the platform's tracker adapter is already the thing that
        moves cards. Two writers to one state machine is a card that jumps a column nobody asked
        for, at a moment nobody is watching.
        """
        opts = {
            "mergeStrategy": "squash",
            "deleteSourceBranch": False,
            "transitionWorkItems": False,
            "bypassPolicy": bool(bypass),
        }
        if bypass:
            opts["bypassReason"] = bypass
        return opts

    def merge_pr(self, *, pr: str, repo: str = "") -> None:
        """Trigger the merge, on the `auto` policy only.

        `repo` NAMES THE CALLER'S INTENT AND THE PR'S OWN REPOSITORY STILL DECIDES — see `_pr`,
        which measured why: a project-wide id resolves the repository by itself here, and a
        mismatch is logged rather than obeyed. Merging into a repository the caller named but the
        pull request does not live in is not something this vendor can even express.

        ARMS AUTO-COMPLETE, which is Azure DevOps's `gh pr merge --auto` and carries the fallback
        inside it: with policies outstanding the PR completes when they pass; with none — the
        common case here — it completes immediately. Verified live on PR 3: the arming PATCH came
        back `active` with `autoCompleteSetBy` set, and the PR read `completed` six seconds later.

        If the arming itself is refused we fall back to a direct completion, mirroring the
        sibling's `--auto`-then-plain sequence rather than inventing a second behaviour.

        NOTHING HERE VERIFIES THE MERGE. Completion is asynchronous (proven above), so a check
        immediately after would report an honest merge as a failure. The durable merge-watch polls
        `pr_status` and is the only thing entitled to that verdict.
        """
        client = self._client()
        pr_data = self._pr(pr, repo=repo)
        target = urllib.parse.quote(self._repo_of(pr_data))
        pr_id = int(pr_data["pullRequestId"])
        path = f"git/repositories/{target}/pullrequests/{pr_id}"
        try:
            client.call("PATCH", path, body={"autoCompleteSetBy": {"id": self._me(client)},
                                             "completionOptions": self._completion_options()})
        except AzureDevOpsError as exc:
            log.warning("could not arm auto-complete on PR %s (%s) — completing directly",
                        pr_id, _redact(str(exc))[:200])
            client.call("PATCH", path, body={
                "status": "completed",
                "lastMergeSourceCommit": pr_data.get("lastMergeSourceCommit") or {},
                "completionOptions": self._completion_options(),
            })

    def force_merge(self, *, pr: str) -> None:
        """Merge NOW, past the policies — the executable option a human picks on a PR that keeps
        starving. The analogue of `gh pr merge --admin`: `bypassPolicy` with a reason, which is
        what Azure DevOps records in the PR's history so the override is not anonymous.

        Raises if even this is refused (the PR then stays parked, and the caller turns the refusal
        into a question rather than a silent stall)."""
        client = self._client()
        pr_data = self._pr(pr)
        repo = urllib.parse.quote(self._repo_of(pr_data))
        pr_id = int(pr_data["pullRequestId"])
        client.call("PATCH", f"git/repositories/{repo}/pullrequests/{pr_id}", body={
            "status": "completed",
            "lastMergeSourceCommit": pr_data.get("lastMergeSourceCommit") or {},
            "completionOptions": self._completion_options(
                bypass="merged by the delivery platform on an operator's explicit instruction"),
        })

    #: What this vendor accepts in a pull request's description. Azure DevOps refuses a longer
    #: one outright (400), where GitHub takes essentially anything — so the bound lives HERE, on
    #: the vendor that has it, rather than in the caller composing the text.
    _DESCRIPTION_MAX = 4000

    #: The note a cut description ends with. A body that stops mid-sentence with no marker reads
    #: as one that ends there.
    _CUT_NOTE = "\n\n[cut to fit this forge's description limit]"

    @classmethod
    def _fit_description(cls, body: str) -> str:
        """A description this vendor will accept, cut with a marker when it must be.

        A METHOD RATHER THAN TWO COPIES, because the two copies is what shipped. `set_pr_body`
        (the UPDATE) capped correctly and `open_pr` (the CREATE) did not — so the vendor's own
        rule, written down and enforced right here, was missing from the one path that runs on
        EVERY job before any other. Found live on the first Azure DevOps ticket to reach the PR
        station (2026-08-27): every station green, then `400 Bad Request: Invalid argument value.
        Parameter name: A description for a pull request must not be longer than 4000
        characters.` — a job that did all of its work and could not hand it in.

        NOT `truncated()`, which is this port's DIFF cutter: its note says "this diff was cut" and
        it appends that note ON TOP of the limit, which on this vendor turns a long body into a
        400 rather than a short one."""
        if len(body) <= cls._DESCRIPTION_MAX:
            return body
        return body[: cls._DESCRIPTION_MAX - len(cls._CUT_NOTE)] + cls._CUT_NOTE

    def pr_body(self, *, pr: str, repo: str = "") -> str | None:
        """The PR's description, or None when the read failed (#187).

        `description` IS THE FIELD, and an absent one is genuinely empty rather than unreadable:
        this vendor omits the key for a pull request opened without a description. None is
        reserved for the call not answering at all, which is the option type this port keeps."""
        try:
            return str(self._pr(pr, repo=repo).get("description") or "")
        except (AzureDevOpsError, KeyError, ValueError) as exc:
            log.warning("could not read the description of PR %s (%s)", pr, str(exc)[:160])
            return None

    def set_pr_body(self, *, pr: str, body: str, repo: str = "") -> bool:
        """Replace the PR's description — True when Azure DevOps took it.

        TRUNCATED TO THE VENDOR'S OWN CEILING rather than refused: the caller is annotating a
        review that is no longer current, and losing the annotation because the body is long is
        the worse of the two outcomes. It says in the text that it cut — a description that stops
        mid-sentence with no marker reads as one that ends there.

        NOT `truncated()`, which is this port's DIFF cutter: its note says "this diff was cut",
        and it appends the note ON TOP of the limit — which on this vendor is the one thing that
        turns a long body into a 400 rather than a short one."""
        body = self._fit_description(body)
        try:
            pr_data = self._pr(pr, repo=repo)
            client = self._client()  # the PR's own repository, in this adapter's project
            target = urllib.parse.quote(self._repo_of(pr_data))
            pr_id = int(pr_data["pullRequestId"])
            client.call("PATCH", f"git/repositories/{target}/pullrequests/{pr_id}",
                        body={"description": body})
            return True
        except (AzureDevOpsError, KeyError, ValueError) as exc:
            log.warning("could not update the description of PR %s (%s)", pr, str(exc)[:160])
            return False

    def close_pr(self, *, pr: str, reason: str = "") -> None:
        """Abandon the PR — Azure DevOps's close-without-merging (#68).

        NOTHING IS DELETED: verified live that an abandoned PR's source branch is still there
        afterwards, so a discard stays reversible. The reason, when there is one, is posted as a
        comment BEFORE the abandon, because a thread on an abandoned PR is harder to add and the
        person reading it later wants to know why more than when."""
        client = self._client()
        pr_data = self._pr(pr)
        repo = urllib.parse.quote(self._repo_of(pr_data))
        pr_id = int(pr_data["pullRequestId"])
        if reason.strip():
            client.call(
                "POST", f"git/repositories/{repo}/pullrequests/{pr_id}/threads",
                body={"comments": [{"parentCommentId": 0, "content": reason.strip()[:500],
                                    "commentType": "text"}], "status": "closed"})
        client.call("PATCH", f"git/repositories/{repo}/pullrequests/{pr_id}",
                    body={"status": "abandoned"})

    def pr_merged(self, *, pr: str) -> bool:
        """Whether the PR has actually merged. `completed` is the only status that means it."""
        return str(self._pr(pr).get("status") or "").lower() == "completed"

    def pr_status(self, *, pr: str, repo: str = "") -> str:
        """"merged" | "closed" | "open" for the durable merge-watch.

        `repo` names the caller's intent; the id resolves the repository by itself on this vendor
        (`_pr`), so a disagreement is logged and the pull request wins.

        `abandoned` is the "closed" case — a human ended the PR without merging, so the watch has
        to stop and hand back instead of polling to the merge deadline (ADR-0007). An unexpected
        status is reported as "open", which keeps the watch alive rather than declaring a PR dead
        on a word we do not recognise — but it is LOGGED, because a status this adapter has never
        seen is news."""
        raw = str(self._pr(pr, repo=repo).get("status") or "")
        status = raw.lower()
        if status == "completed":
            return "merged"
        if status == "abandoned":
            return "closed"
        if status != "active":
            # the SERVER'S spelling, not our normalised one — somebody grepping their own Azure
            # DevOps logs for this word has to be able to find it
            log.warning("PR %s is in Azure DevOps status %r, which this adapter does not know — "
                        "treating it as open so the merge-watch keeps running", pr, raw)
        return "open"

    def mergeable_state(self, *, pr: str) -> str:
        """The PR's mergeability in the sibling's vocabulary, so the merge-watch's self-heal reads
        the same words from either vendor.

        "BEHIND" NEVER HAPPENS HERE, and that is a genuine difference rather than a gap. GitHub's
        `behind` comes from branch protection's "require branches to be up to date"; Azure Repos
        performs a real three-way merge and does not care how far the source has fallen back. The
        nearest equivalent — a build-validation policy that expires when the base moves — surfaces
        as an unapproved policy evaluation, which this reports as `blocked`. So the watch waits
        for the policy instead of rebasing, which is what a developer would do here too.

        Best-effort: `unknown` on any read failure, so the loop degrades to plain polling."""
        try:
            pr_data = self._pr(pr)
        except (AzureDevOpsError, ValueError) as exc:
            log.warning("could not read mergeability for PR %s (%s)", pr, str(exc)[:160])
            return "unknown"
        merge_status = str(pr_data.get("mergeStatus") or "").lower()
        if merge_status == "conflicts":
            return "dirty"
        if merge_status == "rejectedbypolicy":
            return "blocked"
        if merge_status in ("queued", "notset", ""):
            return "unknown"  # Azure DevOps has not finished computing the preview merge
        if merge_status == "failure":
            # Not a textual conflict — the server could not produce a merge for another reason.
            # Reported as `blocked` rather than `dirty` so the watch waits and asks a human at the
            # gate, instead of announcing a conflict that a person would open the PR and not find.
            return "blocked"
        try:
            # the SAME `pr_data` the merge status came from, not a second fetch: two reads of a
            # PR that is moving can disagree, and the disagreement would be invisible here
            ci = _ci_status_from_evaluations(self._evaluations(pr_data))
        except (AzureDevOpsError, ValueError) as exc:
            log.warning("could not read the policies for PR %s (%s)", pr, str(exc)[:160])
            return "unknown"
        if ci in ("pending",):
            return "blocked"
        if ci == "failure":
            return "unstable"
        return "clean"

    def update_branch(self, *, pr: str) -> bool:
        """Azure DevOps has NO update-branch API — nothing corresponds to GitHub's
        `PUT /pulls/{n}/update-branch`, because nothing in Azure Repos requires a PR to be up to
        date before it merges.

        Returns False, the port's documented "could not", rather than raising: this is only ever
        called after `mergeable_state` reports `behind`, which the method above explains can never
        happen here — so a raise would turn an unreachable branch into a retrying activity, and a
        silent True would tell the watch a self-heal happened that did not. False plus this line
        in the log is the honest answer."""
        log.warning("update_branch is not available in Azure Repos (there is no update-branch "
                    "route, and no policy requires an up-to-date source) — PR %s is unchanged", pr)
        return False

    def disable_auto_merge(self, *, pr: str) -> None:
        """Disarm a previously-armed auto-complete, by writing the empty identity into
        `autoCompleteSetBy`. Verified live to be accepted on a PR that was never armed, which is
        what makes this safe to call unconditionally after a CI-repair pass."""
        pr_data = self._pr(pr)
        repo = urllib.parse.quote(self._repo_of(pr_data))
        self._client().call(
            "PATCH", f"git/repositories/{repo}/pullrequests/{int(pr_data['pullRequestId'])}",
            body={"autoCompleteSetBy": {"id": _NO_IDENTITY}})

    def merge_commit_sha(self, *, pr: str) -> str | None:
        """The commit the PR landed on the base as — the exact commit the post-merge deploy runs
        on (ADR-0005). None until the PR is actually merged.

        THE STATUS GATE IS THE WHOLE METHOD. `lastMergeCommit` is populated on PRs that never
        merged and never will: it is the speculative merge Azure DevOps computes to answer "would
        this merge?". Verified live — PR 4 was abandoned without merging and still reported
        `lastMergeCommit.commitId: 15d18232…`, and on PR 3 the value CHANGED when it completed.
        Returning that would send the deploy watch after a commit that is on no branch, and it
        would look like a real sha the whole way down."""
        pr_data = self._pr(pr)
        if str(pr_data.get("status") or "").lower() != "completed":
            return None
        return (str((pr_data.get("lastMergeCommit") or {}).get("commitId") or "").strip()
                or None)

    # ---- policies (the CI gate) ---------------------------------------------------------------

    def _evaluations(self, pr_data: dict) -> list[dict]:
        """The branch-policy evaluations for this PR.

        The artifact id is `vstfs:///CodeReview/CodeReviewId/{projectId}/{pullRequestId}` and the
        PROJECT GUID in it is not optional — the project's NAME is rejected. It is read off the PR
        itself (`repository.project.id`) rather than looked up, so this costs no extra round trip
        and cannot drift from the repository the PR is actually in."""
        project_id = (((pr_data.get("repository") or {}).get("project") or {}).get("id") or "")
        if not project_id:
            raise AzureDevOpsError(
                "the pull request came back without its project id, so the policy artifact id "
                "cannot be built — reporting this rather than answering 'no checks', which would "
                "let an unread gate look like an absent one"
            )
        artifact = f"vstfs:///CodeReview/CodeReviewId/{project_id}/{pr_data['pullRequestId']}"
        return self._client().values("policy/evaluations", params={"artifactId": artifact},
                                     api_version=POLICY_API_VERSION)

    def pr_ci_status(self, *, pr: str) -> str:
        """"none" | "pending" | "success" | "failure" for the PR's gates.

        POLICY EVALUATIONS ARE THE RIGHT SOURCE, and the reason is structural. In Azure DevOps a
        pipeline does not gate a PR by existing; it gates by being named in a build-validation
        POLICY. A YAML `pr:` trigger — the thing that would make a GitHub reader expect otherwise
        — is not supported for Azure Repos at all. So policy evaluations are precisely GitHub's
        `gh pr checks --required`: the checks that actually block the merge.

        `[]` therefore means "nothing gates this merge" and must read `none`. Verified live on a
        project whose `fx-ado-ci` pipeline really does build `main`: `policy/configurations` is
        empty, so an active PR evaluates to nothing. Answering `pending` there would hang the
        merge watch on a repository that is perfectly healthy — the fx-jira defect, one vendor
        over."""
        return _ci_status_from_evaluations(self._evaluations(self._pr(pr)))

    def pr_checks(self, *, pr: str) -> list[dict]:
        """Every gate on the PR as {name, bucket, state} — the per-check detail behind the
        aggregate, for the panel.

        Built from the SAME evaluations `pr_ci_status` aggregates, deliberately. A detail view fed
        from a different source than its own summary is a panel that contradicts the decision the
        platform made, and somebody spends an afternoon on the discrepancy."""
        rows: list[dict] = []
        for ev in self._evaluations(self._pr(pr)):
            config = ev.get("configuration") or {}
            state = str(ev.get("status") or "unknown")
            rows.append({
                "name": (config.get("settings") or {}).get("displayName")
                        or (config.get("type") or {}).get("displayName")
                        or "policy",
                "bucket": _POLICY_BUCKET.get(state, "pending"),
                "state": state,
            })
        return rows

    # ---- pipelines ----------------------------------------------------------------------------

    def _definition_id(self, workflow: str) -> int | None:
        """A pipeline's numeric id from what the manifest called it. None when nothing matches —
        verified live that the name filter answers `[]` for an unknown name rather than
        everything, which is what makes a None here mean "not there" and not "could not read".

        THREE SPELLINGS, BECAUSE THE MANIFEST KEY IS SHARED AND THE PROVIDERS ARE NOT (sweep S3,
        2026-08-16). `post_merge_deploy.workflow` is documented — and demonstrated in
        `docs/project.yaml.example` and ONBOARDING §13 — as `deploy.yml`, which is exactly right
        for GitHub, where `gh run list --workflow` takes the FILE NAME. Azure Pipelines has no file
        name in its API: a definition has a display name and an id. So an ADO client following the
        documentation declared `deploy.yml`, matched no definition, and every green deploy was
        announced as a **timeout** — the failure wearing the costume of an answer, on the first
        merge of their first day.

        A numeric string is an id (`build/definitions/12`), a name matches by name, and a
        `something.yml` also tries its stem — so one documented key means the same thing on both
        vendors without asking a client to learn ours."""
        wanted = str(workflow or "").strip()
        if not wanted:
            return None
        if wanted.isdigit():
            # An id was declared. Confirmed rather than trusted: a definition that does not exist
            # must answer "not there", not 404 later inside the watch.
            found = self._client().values("build/definitions", params={"definitionIds": wanted})
            return int(wanted) if found else None
        found = self._client().values("build/definitions", params={"name": wanted})
        if found:
            return int(found[0]["id"])
        stem = wanted.rsplit("/", 1)[-1]
        stem = stem[:-4] if stem.lower().endswith(".yml") else (
            stem[:-5] if stem.lower().endswith(".yaml") else "")
        if stem:
            found = self._client().values("build/definitions", params={"name": stem})
            if found:
                log.info("Azure Pipelines has no definition named %r; matched %r by its stem — "
                         "declare the definition's own name or id to make this exact", wanted, stem)
                return int(found[0]["id"])
        return None

    @staticmethod
    def _build_state(build: dict) -> str:
        """A build's state in the port's vocabulary. Anything short of `completed` is still
        running, so it is pending and not yet judged."""
        if str(build.get("status") or "").lower() != "completed":
            return "pending"
        result = str(build.get("result") or "").lower()
        # `partiallySucceeded` is a build with a failed non-blocking step. Green would hide a
        # failure the client can see in their own portal.
        return "success" if result == "succeeded" else "failure"

    @staticmethod
    def _build_url(build: dict) -> str | None:
        return ((build.get("_links") or {}).get("web") or {}).get("href")

    def _repository_id(self) -> str:
        """The repository's GUID.

        THE BUILD API WILL NOT TAKE A NAME. Every git route in this adapter accepts
        `git/repositories/fx-ado/...`, so the name looks universal — and then
        `build/builds?repositoryId=fx-ado&repositoryType=TfsGit` answers `400: Repository ID for a
        tfsgit repository should be a GUID`. Found by running the adapter against the live API;
        no amount of reading the two route families side by side would have suggested it.

        Cached for the object's life, which is one job. A repository's id is immutable for as long
        as the repository exists, and nothing in this adapter creates or renames repositories — so
        there is no write this cache can go stale at."""
        if not self._repo_guid:
            found = self._client().call(
                "GET", f"git/repositories/{urllib.parse.quote(self.repo)}")
            self._repo_guid = str(found.get("id") or "")
            if not self._repo_guid:
                raise AzureDevOpsError(
                    f"{self.repo} came back without an id, so no pipeline query can be scoped to "
                    f"it — reported rather than left unscoped, because an unscoped build query "
                    f"answers about every repository in the project"
                )
        return self._repo_guid

    def _builds(self, **params) -> list[dict]:
        base = {"repositoryId": self._repository_id(), "repositoryType": "TfsGit",
                "queryOrder": "queueTimeDescending"}
        return self._client().values("build/builds", params={**base, **params})

    def deploy_run_status(self, *, sha: str, workflow: str) -> tuple[str, str | None]:
        """The deploy pipeline's run ON this commit — ("success"|"failure"|"pending"|"none", url).

        `none` means no run exists for that pipeline and commit yet, which is a real answer here:
        the platform triggers a deploy and only OBSERVES it (ADR-0005), so "not dispatched yet"
        and "failed" must never collapse into one word. A pipeline name that matches no definition
        is also `none` — with a log line, because that is a configuration mistake and not a
        pipeline that has not run."""
        definition = self._definition_id(workflow)
        if definition is None:
            log.warning("no Azure Pipelines definition named %r in %s/%s — the deploy watch has "
                        "nothing to observe", workflow, self.organization, self.project)
            return "none", None
        for build in self._builds(definitions=str(definition), **{"$top": "50"}):
            if str(build.get("sourceVersion") or "") == sha:
                return self._build_state(build), self._build_url(build)
        return "none", None

    def dispatch_workflow(self, *, workflow: str, ref: str) -> None:
        """Queue a pipeline run on `ref` — the on-demand e2e an `e2e`-labelled ticket kicks off
        (ADR-0008). Verified live: `POST build/builds` with the definition id and a
        `refs/heads/...` source branch comes back as a queued build."""
        definition = self._definition_id(workflow)
        if definition is None:
            raise AzureDevOpsError(
                f"no Azure Pipelines definition named {workflow!r} in {self.organization}/"
                f"{self.project} — nothing was queued"
            )
        self._client().call("POST", "build/builds",
                            body={"definition": {"id": definition},
                                  "sourceBranch": _branch_ref(ref)})

    def latest_run(self, *, workflow: str) -> dict | None:
        """The most recent run of `workflow` as {id, status, conclusion, url, created_at}, so the
        e2e ticket can pin the run that existed BEFORE its dispatch and then watch for a different
        id. None when the pipeline has never run; raises when the pipeline does not exist, because
        those two are different problems and the caller's fallback for the first would hide the
        second.

        `conclusion` IS TRANSLATED, and that is the whole reason this is not a passthrough. The
        one caller — `machine._run_e2e_check` — decides the verdict with
        `(run["conclusion"] or "").lower() == "success"`, which is GitHub's word. Azure DevOps
        says `succeeded`, so a GREEN e2e suite scored False: every Azure e2e ticket would announce
        "e2e suite is RED", park on a human and hand back a passing run. A port satisfied in shape
        and not in meaning is worse than one missing a method, because the missing method raises.
        `status` needs no such translation — both vendors spell the terminal state `completed`,
        which is what that same loop waits for — and `None` while the build is still running is
        exactly what GitHub reports for a run that has not concluded."""
        definition = self._definition_id(workflow)
        if definition is None:
            raise AzureDevOpsError(
                f"no Azure Pipelines definition named {workflow!r} in {self.organization}/"
                f"{self.project} — there is no run to watch"
            )
        runs = self._builds(definitions=str(definition), **{"$top": "1"})
        if not runs:
            return None
        build = runs[0]
        state = self._build_state(build)
        return {"id": build.get("id"), "status": build.get("status"),
                "conclusion": None if state == "pending" else
                ("success" if state == "success" else "failure"),
                "url": self._build_url(build), "created_at": build.get("queueTime")}

    def pr_diff(self, *, pr: str, repo: str = "", max_chars: int = 60000) -> str | None:
        """The PR's changes as a unified diff — or None when the read failed.

        THREE CALLS, BECAUSE THIS VENDOR HAS NO `pr diff`. Azure DevOps answers a diff as a LIST
        of changed paths (`diffs/commits`, base → head), and the content of a file is a separate
        read. So this renders a diff-SHAPED digest: the change kind and path for every entry, and
        that is deliberately where it stops — pulling every blob would be one call per file on a
        credential this deployment has exhausted before, to produce something larger than the
        prompt it feeds.

        A DIGEST IS NOT A DIFF, AND THE TEXT SAYS SO. A reader handed a list of paths under a
        header saying "diff" would answer as if it had read the change; the header names what this
        is, so the tech-lead can say "I can see WHICH files changed, not what changed in them".

        None when the read failed, "" when the pull request genuinely changes nothing — the
        option type this port keeps everywhere, and the difference between "I could not look" and
        "there is nothing there".
        """
        try:
            pr_data = self._pr(pr, repo=repo)
            client = self._client_for(self._repo_of(pr_data))
            base = (pr_data.get("lastMergeTargetCommit") or {}).get("commitId") or ""
            head = (pr_data.get("lastMergeSourceCommit") or {}).get("commitId") or ""
            if not base or not head:
                log.warning("PR %s carries no merge commits to diff between", pr)
                return None
            answer = client.call(
                "GET", f"git/repositories/{urllib.parse.quote(self._repo_of(pr_data))}/diffs/"
                       f"commits",
                params={"baseVersion": base, "targetVersion": head,
                        "baseVersionType": "commit", "targetVersionType": "commit"})
        except AzureDevOpsError as exc:
            log.warning("could not read the diff of %s (%s)", pr, _redact(str(exc))[:200])
            return None
        entries = [e for e in (answer or {}).get("changes") or [] if isinstance(e, dict)]
        rows = []
        for entry in entries:
            item = entry.get("item") or {}
            if item.get("isFolder"):
                continue
            rows.append(f"{str(entry.get('changeType') or 'edit'):<10} {item.get('path') or '?'}")
        if not rows:
            return ""
        body = ("# Changed files (Azure DevOps answers a diff as a list of paths; the contents of "
                "each file are a separate read this does NOT make)\n" + "\n".join(rows))
        return _truncated(body, max_chars)

    def failed_ci_logs(self, *, pr: str, max_chars: int = 6000) -> str:
        """The tail of the FAILING build logs for this PR's source branch, as the repair input.

        Walks the build's timeline for the records that actually failed and fetches only their
        logs — the whole build log is mostly agent provisioning, and a repair pass fed 4,000 lines
        of that spends its context on nothing. The log route answers `{"count": n, "value": [
        lines ]}` when asked for JSON, which is what the shared client asks for.

        Empty when nothing is failing OR when no build ran at all — and in Azure DevOps the second
        is the common case, because without a build-validation policy no pipeline runs on a PR
        branch (verified: zero builds for a live PR's source branch). That agrees with
        `pr_ci_status` reporting `none`: no gate, no failure, no logs."""
        try:
            pr_data = self._pr(pr)
        except (AzureDevOpsError, ValueError) as exc:
            # Every read below derives from this one, so an unreadable PR would otherwise come out
            # as "CI is fine" — the shape of failure this codebase names as the expensive one.
            log.warning("could not read PR %s to collect its CI logs (%s)", pr, str(exc)[:160])
            return ""
        branch = str(pr_data.get("sourceRefName") or "")
        if not branch:
            return ""
        client = self._client()
        failed = [b for b in self._builds(branchName=branch, **{"$top": "20"})
                  if self._build_state(b) == "failure"]
        chunks: list[str] = []
        for build in failed[:2]:  # the newest failing runs
            build_id = build.get("id")
            try:
                timeline = client.call("GET", f"build/builds/{build_id}/timeline")
            except AzureDevOpsError as exc:
                log.warning("could not read the timeline of build %s (%s)",
                            build_id, str(exc)[:160])
                continue
            for record in timeline.get("records") or []:
                if str(record.get("result") or "").lower() != "failed":
                    continue
                log_id = (record.get("log") or {}).get("id")
                if not log_id:
                    continue
                try:
                    lines = client.values(f"build/builds/{build_id}/logs/{log_id}")
                except AzureDevOpsError as exc:
                    log.warning("could not read log %s of build %s (%s)",
                                log_id, build_id, str(exc)[:160])
                    continue
                chunks.append(f"### {record.get('name') or 'step'}\n" + "\n".join(
                    str(line) for line in lines))
        return _redact("\n".join(chunks))[-max_chars:]

    # ---- tags ---------------------------------------------------------------------------------

    def _tags(self) -> list[dict]:
        return self._client().values(f"git/repositories/{urllib.parse.quote(self.repo)}/refs",
                                     params={"filter": "tags/"})

    #: `queueStatus` values that mean the definition will not run. `enabled` is the live one.
    #: Listed rather than inverted, for the reason the GitHub sibling states: a value Microsoft
    #: adds later must not silently demote a working gate into a question.
    _DEAD_QUEUE = frozenset({"disabled", "paused"})

    def disabled_ci_paths(self, repo: str = "") -> list[str] | None:
        """YAML pipeline files this project reports as disabled or paused. None when unreadable.

        THE PATH IS THE POINT, not the definition. `infer` cites evidence as a repo-relative file,
        so the answer has to come back in that vocabulary — `configuration.path` on a YAML
        definition is exactly it. A CLASSIC (designer) pipeline has no file at all and is skipped:
        it cannot be the source of a command `infer` read off disk, so naming it here would
        demote nothing and confuse the report.

        AND ONLY THIS REPOSITORY'S. An Azure DevOps project holds every repository's pipelines
        together, so a definition pointing at a sibling repo would otherwise disable a path that,
        read relative to the checkout in hand, names a completely different file (C-18 again)."""
        target = repo or self.repo
        try:
            found = self._client().values("build/definitions",
                                          params={"queryOrder": "nameAscending"})
        except Exception as exc:  # noqa: BLE001 — an unreadable list is not an empty one
            log.info("could not list the pipelines of %s (%s) — the onboarding will not know "
                     "which are switched off", target, str(exc)[:160])
            return None
        out: list[str] = []
        for row in found:
            if not isinstance(row, dict):
                continue
            status = str(row.get("queueStatus") or "enabled").strip().lower()
            # The list route returns a summary; `configuration` arrives only on the full read, so
            # ask for it once per DISABLED definition rather than for all of them.
            if status not in self._DEAD_QUEUE:
                if status != "enabled":
                    log.info("%s reports pipeline %r with queueStatus %r, which this adapter does "
                             "not know — treating it as live", target, row.get("name"), status)
                continue
            try:
                full = self._client().call("GET", f"build/definitions/{int(row['id'])}")
            except Exception as exc:  # noqa: BLE001 — one unreadable definition is not all of them
                log.info("could not read pipeline %s of %s (%s)", row.get("id"), target,
                         str(exc)[:120])
                continue
            config = full.get("configuration") or {}
            path = str(config.get("path") or "").strip().lstrip("/")
            named = ((config.get("repository") or {}).get("id")
                     or (full.get("repository") or {}).get("name") or "")
            if path and (not named or str(named) == target):
                out.append(path)
        return sorted(set(out))

    def latest_tag(self) -> str | None:
        """The latest release tag, for the prod version picker.

        SORTED BY VERSION, NOT BY POSITION, and that is not defensive coding. Verified live:
        `v0.2.0` was created first and `v0.1.0` second, and the refs route returned them as
        [v0.1.0, v0.2.0] — Azure DevOps orders refs LEXICOGRAPHICALLY by name, so neither end of
        the list is "the latest" and `v0.10.0` would sort below `v0.9.0`.

        The ordering key is `openfactory.semver.parse`, the same function the picker uses to render
        the
        suggestions — a second version parser here is a picker that disagrees with itself. Tags
        that do not parse all tie at (0,0,0) and fall back to name order, so a repository tagged
        with something else still gets a stable, explainable answer."""
        from openfactory.semver import parse

        names = [str(r.get("name") or "").removeprefix("refs/tags/") for r in self._tags()]
        names = [n for n in names if n]
        if not names:
            return None
        return max(names, key=lambda n: (parse(n), n))

    def create_tag(self, *, tag: str, ref: str) -> None:
        """Cut an annotated release tag at `ref` — the prod trigger (D-12).

        IDEMPOTENT (D-16), twice over: an existing tag returns before writing, and the 409 the
        server answers when somebody else created it between the check and the POST is treated as
        success. Verified live — a repeated create answers
        `409: A Git ref with the name refs/tags/v0.2.0 already exists.`

        Annotated rather than lightweight because a release wants an author and a date on it, and
        Azure DevOps's own tags view shows those."""
        if any(str(r.get("name") or "") == f"refs/tags/{tag}" for r in self._tags()):
            return
        client = self._client()
        version = ref.removeprefix("refs/heads/").removeprefix("refs/tags/")
        # `versionType` defaults to `branch`, so a caller that hands us a SHA (the promotion path
        # takes a branch, but `create_tag` is on the port for anyone) would get a 404 naming a
        # branch that was never a branch. Detected from the value rather than asked for.
        params = {"searchCriteria.itemVersion.version": version, "$top": "1"}
        if re.fullmatch(r"[0-9a-f]{40}", version, re.I):
            params["searchCriteria.itemVersion.versionType"] = "commit"
        commits = (client.call(
            "GET", f"git/repositories/{urllib.parse.quote(self.repo)}/commits",
            params=params).get("value") or [])
        if not commits:
            raise AzureDevOpsError(
                f"could not resolve {ref!r} to a commit in {self.repo} — refusing to tag, because "
                f"a release tag on the wrong commit is worse than a release that did not happen"
            )
        try:
            client.call("POST", f"git/repositories/{urllib.parse.quote(self.repo)}/annotatedtags",
                        body={"name": tag,
                              "taggedObject": {"objectId": commits[0]["commitId"]},
                              "message": f"release {tag}"})
        except AzureDevOpsError as exc:
            if "already exists" in str(exc):
                return  # created concurrently between our check and this POST
            raise

    # ── creating a repository (RepositoryCreatingForge) ─────────────────────────────────────────

    def create_repository(self, *, name: str, private: bool = True,
                          description: str = "") -> tuple[str, bool]:
        """See `RepositoryCreatingForge`. `(project/name, created)`.

        WHY THIS EXISTS AT ALL: without it a deployment with no GitHub anywhere could onboard a
        client who ALREADY had a context repository and not one who did not — which is most of
        them, and it is the first hour of the engagement. The pilot operator set the bar the day
        the mixed-vendor half was fixed: this platform may not be GitHub-only, because the
        deployment after the pilot is a 100% Azure DevOps enterprise (2026-08-12).

        THE COORDINATES COME FROM THIS ADAPTER, never from a parameter — the same rule the GitHub
        implementation states, and it matters more here: an Azure DevOps PAT is scoped to an
        ORGANISATION, so a caller able to name the project could create a repository anywhere in
        it. The new repository is created in the project this adapter already drives, and its
        identity is returned as `project/name` because that is what every other route here reads
        back (`coordinates` resolves the ADO project; the git repository is the leaf).

        `private` IS ACCEPTED AND CANNOT BE HONOURED, and saying so is better than pretending:
        Azure Repos has no per-repository visibility — a repository is as visible as the PROJECT
        that contains it. A deployment that needs a private context repository puts it in a
        private project, which is a decision taken before this call. Ignoring the flag silently
        would let a caller believe it had asked for something.

        IDEMPOTENT, like its GitHub sibling: an existing repository of that name returns
        `(…, False)` rather than raising, because a retry of a durable activity, a client who made
        it themselves and an earlier onboarding are all the expected case. And the creation is
        RE-READ before it is believed — a repository reported created that cannot be listed would
        surface an hour later as the product role failing to write a requirement, in a message
        about something else entirely.
        """
        bare = (name or "").strip().strip("/").split("/")[-1]
        if not bare:
            raise ValueError(f"cannot create a repository called {name!r}")
        if not self.project:
            raise ValueError(
                "cannot create a repository: this adapter has no Azure DevOps project, and a "
                "repository has to live in one. Declare `project` in the forge options — "
                "refusing to guess, because this credential can write across the organisation.")
        full = f"{self.project}/{bare}"
        client = self._client()

        def _exists() -> bool:
            listed = (client.call("GET", "git/repositories").get("value") or [])
            return any(str(r.get("name") or "").lower() == bare.lower() for r in listed)

        if _exists():
            return full, False

        try:
            client.call("POST", "git/repositories",
                        body={"name": bare, "project": {"name": self.project}})
        except AzureDevOpsError as exc:
            # Lost a race with a concurrent create, or somebody made it by hand between the two
            # calls: the name being taken IS the outcome this asked for.
            if "already exists" in str(exc).lower() and _exists():
                return full, False
            raise
        if not _exists():
            raise AzureDevOpsError(
                f"{full} was reported created and cannot be listed back — treating it as not "
                f"created, because a repository nobody can reach is worse than one nobody made")
        return full, True
