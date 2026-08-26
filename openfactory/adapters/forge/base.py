"""ForgeAdapter — where code lives: branches, PRs, reviews, merges (GitHub, GitLab...).

Independent axis from the tracker. This is also where the platform *triggers*
lifecycle transitions (merge) — it triggers; the project's pipeline executes the
deploy with its own secrets (ADR-0001 D-12). Merge rights are governed by the floor
+ the bot credential, not by prompts.
"""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

ReviewEvent = Literal["approve", "comment", "request-changes"]


def truncated(text: str, max_chars: int) -> str:
    """The tail of a diff that fits, and a MARKER when it did not.

    A diff that stops mid-hunk with nothing saying so reads as a change that ends there — a reader
    concludes the pull request does less than it does. The HEAD is kept rather than the tail, which
    is the opposite of a log: the first hunks of a diff are the change, and the tail is usually
    lockfiles and generated files.
    """
    if len(text) <= max_chars:
        return text
    return (text[:max_chars]
            + f"\n\n[... this diff was cut here: {len(text)} characters in total, "
              f"{max_chars} shown. It is NOT the whole change.]\n")


def host_of(url: str) -> str:
    """The host an https URL names, lowercased, or `""` for anything else.

    `""` FOR SSH AND FOR SCP-STYLE REMOTES ON PURPOSE — `git@host:owner/name` has no scheme and
    every caller of this is deciding whether to inject a credential, which those two shapes do not
    take. One home rather than a `split("://")` at each adapter, because two of those had already
    been written by hand and the second one forgot that a URL may carry a port."""
    import urllib.parse

    if not url.lower().startswith("https://"):
        return ""
    return (urllib.parse.urlsplit(url).hostname or "").lower()


def carries_credentials(url: str) -> bool:
    """Whether `url` already has userinfo — a deployment's own credential helper or deploy key.

    Rewriting one of those is how a working setup starts failing after an upgrade, so every
    adapter leaves such a URL alone."""
    import urllib.parse

    return bool(urllib.parse.urlsplit(url).username or urllib.parse.urlsplit(url).password)


@runtime_checkable
class ForgeAdapter(Protocol):
    def push_remote(self) -> str | None:
        """An authenticated HTTPS remote URL carrying the bot token, so the push is
        attributed to the bot. Per-provider scheme (GitHub: x-access-token, GitLab:
        oauth2). None → use the repo's ambient origin (dev)."""
        ...

    def clone_url(self, repo: str, *, token: str | None) -> str:
        """An HTTPS URL that clones `repo` on THIS forge, carrying `token` when there is one.

        A SIBLING OF `push_remote`, NOT A DUPLICATE. That one answers for the repository this
        adapter was built for and is what the job pushes to; this one answers for ANY repository
        the same forge hosts, because the callers that need it are cloning something else: the
        preflight sizes the CARD's repo (C-18 — one board, N repos), the knowledge pipeline reads
        the merged one, and the product module clones a docs repository that is not the code.

        IT EXISTS BECAUSE THE PLATFORM HAD A `clone_url()` THAT SAID `github.com` WITH NO BRANCH —
        in `runtime/fargate/entrypoint.py` — since moved to `runtime/boxed_job.py` for the same
        reason (ADR-0040) — reached from twenty call sites including the box clone, the preflight
        and the knowledge refresh. On an Azure project the box cloned
        `github.com/<repo>.git` (a 404, or worse somebody else's repository of that name) and the
        other two degraded silently: a ticket that proceeds UNSIZED, and a knowledge bundle that
        answers `no-repo` for ever with nobody told.

        A clone URL is provider knowledge — the host, the credential's shape, and for Azure DevOps
        an extra `/{project}/_git/` segment GitHub has no equivalent of. It belongs to the adapter
        that already holds all three."""
        ...

    def authenticated_url(self, url: str) -> str:
        """`url` carrying THIS ADAPTER'S credential, if it owns the host — otherwise untouched.

        THE QUESTION IS "IS THIS MY HOST", and only the adapter can answer it (#162). The neutral
        path had a helper that injected `x-access-token:<token>@` into ANY `https://` URL, which
        made it a credential-forwarding primitive: a project registered as GitHub whose
        `repo_path` names some other host got this deployment's App token sent there. That is not
        hypothetical — `project init` registers `kind="github"` for every URL that is not an Azure
        one, so a GitLab path arrives here labelled GitHub.

        A SIBLING OF `clone_url`, ASKING THE OTHER DIRECTION. That one is handed a repository and
        composes the whole URL; this one is handed a URL somebody else composed — a registry row,
        a manifest, an operator's paste — and only decides whether this adapter's credential
        belongs on it. Both need the same two facts (the host, and how this vendor spells a
        credential), which is why they live together.

        THE ADAPTER'S OWN CREDENTIAL, NEVER THE CALLER'S — the same rule `clone_url_for` states
        and for the same measured reason: every call site in this codebase hands the forge axis a
        GitHub credential, so a method that authenticated with whatever it was passed would wrap a
        `ghs_…` secret in Azure's spelling and send it to dev.azure.com. Taking no token at all is
        what makes that impossible rather than merely discouraged.

        UNTOUCHED IS THE HONEST ANSWER for a foreign host, an ssh remote, or a URL that already
        carries credentials of its own: the clone then fails saying it needs authentication, which
        is a sentence somebody can act on, rather than failing with another system's secret in the
        request — a 401 that reads like a revoked credential, the most expensive shape a
        configuration error takes."""
        ...

    # ---- acting on an ARBITRARY repository --------------------------------------------------
    #
    # THIS PORT WAS DESIGNED FROM WHAT A JOB WRITES, AND WENT BLIND WHERE IT READS. Everything
    # bound to `self.repo` answers about the repository the adapter was built for, because that is
    # where the job's branch, PR and CI live. The methods carrying `repo` take one for the same
    # reason `clone_url` does: their caller is asking about a DIFFERENT one — the product module
    # proposes a requirement in the documentation repository, which is not the code.
    #
    # That gap had a cost. `openfactory/product/authoring.py` never went through this port at all;
    # it
    # shelled out to `gh` about `docs_repo` ~13 times. So when a deployment moved off GitHub the
    # capability did not port — it VANISHED, and the module refused (safely) rather than leaking
    # an Azure credential to github.com. The platform kept working and answered worse.
    #
    # SEVEN METHODS CARRY `repo` NOW, AND THE LAST THREE ARE WHAT CLOSED IT (#95). `clone_url`,
    # `list_branches`, `delete_branch` and `pr_for_head` let the product path READ another
    # repository and commit into it; `open_pr`, `pr_status` and `merge_pr` are the review-request
    # ceremony on top, and until they took a repository the module could open no pull request on
    # any vendor but GitHub. The rule is one rule everywhere: `""` means this adapter's own
    # repository, so no existing call site changed.
    #
    # THESE ARE READS, AND A READ HAS A THIRD ANSWER A WRITE DOES NOT:
    #
    #     None = I could not read.        [] / "" = I read, and there is nothing.
    #
    # Collapsing those is this codebase's most expensive defect class — an unreadable board has
    # read as an empty queue, an unparsed review as a rejection. "There are no `req/*` branches"
    # sends the product module on to mint a number; "I could not list them" must not. A provider
    # that genuinely cannot tell the two apart answers None, and says so in its own docstring.

    def list_branches(self, repo: str = "", *, prefix: str = "") -> list[str] | None:
        """Branch names in `repo` ("" = this adapter's own), or None if they could not be read.

        BARE NAMES — `req/0007-x`, never `refs/heads/req/0007-x`. Every other method on this port
        takes a bare name (`open_pr(head=…)`, `create_tag(ref=…)`, `dispatch_workflow(ref=…)`) and
        each provider adds its own spelling back; handing refs out here would make every caller
        strip a prefix that only one vendor uses.

        `prefix` is a STRING prefix, not a path segment: `req/` matches `req/0007-x`, and `req`
        would also match `requirements-cleanup`. It exists so the filtering happens at the server
        — a documentation repository with a thousand branches must not be paged through a client
        that wants nine of them — so it is a narrowing, never a promise about shape.

        `[]` = the repository was read and nothing matches. `None` = it could not be read.
        """
        ...

    def delete_branch(self, name: str, *, repo: str = "") -> bool:
        """Delete a branch. True when it is GONE, False when it may still be there.

        THE ANSWER IS THE POST-CONDITION, NOT THE ACT, and that is the decision worth arguing.
        The caller is a convergence sweep: `land_open_proposals` deletes a `req/*` branch whose
        pull request already merged, so that the next hourly pass stops re-proposing work that is
        in the base. What it needs to know is "is that branch still going to be here next hour",
        which is a fact about the repository, not about who removed it. So a branch that was
        already gone answers True — the sweep converges, and a retried activity is a no-op rather
        than an error (D-16). Providers log the two cases apart even though they return the same.

        WHAT MUST NOT COLLAPSE IS ALREADY-GONE AGAINST REFUSED, and here they cannot: refused is
        False. A protected branch, a missing scope, an unreachable server — all False, all meaning
        the branch is still there and the sweep will see it again. GitHub makes that easy to get
        wrong: `DELETE git/refs/heads/<b>` answers 422 for a branch that does not exist and 403
        for one it will not touch, and both exit non-zero, so a provider reading the exit status
        alone reports every refusal as a successful cleanup, for ever, silently.

        NEVER RAISES. Nothing downstream of a failed branch cleanup should stop: the requirement
        landed, the leftover ref is untidiness. A False and a log line is the whole remedy.
        """
        ...

    def pr_for_head(self, head: str, *, repo: str = "") -> str | None:
        """The most recent pull request opened FROM branch `head`, as a URL — in ANY state.

        ANY STATE, because the question this answers is idempotency: has this branch ever been
        proposed? A closed or merged pull request is still an answer of yes, and re-opening a
        second one for the same work is what the caller is trying not to do. That is deliberately
        wider than the `open_pr` implementations' own private lookup, which asks the narrower
        question "is one OPEN right now" and must stay narrow — an abandoned PR is not a reason to
        refuse to open a fresh one.

        `""` = the repository was read and no pull request was ever opened from that branch.
        `None` = it could not be read. A caller that writes `if not pr: create_one()` puts those
        back together and will file a duplicate on a transient error; the check is `is None`.

        WHAT THIS DOES NOT SAY IS WHICH STATE THE PULL REQUEST IS IN, and one caller needs that:
        the proposal sweep treats a MERGED pull request on a surviving branch ("done work") the
        opposite way from an open one ("finish it"). `pr_status` answers exactly that, and now
        takes a repository too — so the two are asked together about the documentation repository
        rather than this one being given a `state` argument its `str | None` return could not
        report back.
        """
        ...

    def open_pr(self, *, head: str, base: str, title: str, body: str, repo: str = "") -> str:
        """Open a pull request in `repo` ("" = this adapter's own); return its URL.

        `repo` IS HERE FOR THE REASON `clone_url`'S IS — the caller is asking about a different
        repository. The product module proposes a requirement in the DOCUMENTATION repository,
        which is not the code the job is changing, and while this was bound to `self.repo` it had
        no way to say so: it shelled out to `gh`, and on any other vendor the review request was
        refused rather than opened (#95).

        THE IDEMPOTENCY LOOKUP IS SCOPED TO THE SAME REPOSITORY THIS WRITES TO. Both providers
        check for an already-open pull request from `head` before creating one (D-16 — a retried
        activity must not double-file), and that check has to follow `repo`. Aimed at the
        adapter's own repository it would find nothing on a docs repository, create a second
        pull request for work already in flight, and the duplicate would be ours.

        RAISES when no pull request could be opened, and that is deliberate where the reads next
        door answer None. There is no value here that could mean "I could not tell": a caller
        given "" would have to decide whether a review request exists, and the one thing this
        must never do is let a failure read as "PR opened". The product path catches the raise and
        says exactly what is true — the text is committed and pushed, the review request is not
        open — which is the answer a person can act on."""
        ...

    def review_pr(self, *, pr: str, event: ReviewEvent, body: str) -> None:
        """Post a review on the PR (the reviewer's verdict, as a real review)."""
        ...

    def request_reviewers(self, *, pr: str, reviewers: list[str]) -> None:
        """Request human reviewers (the default human-on-PR path)."""
        ...

    def merge_pr(self, *, pr: str, repo: str = "") -> None:
        """Trigger a merge (only on the `auto` policy; the pipeline reacts, e.g.
        staging deploy). Never reachable for a bot whose token lacks the right.

        `repo` DISAMBIGUATES A BARE REF, AND A PULL REQUEST THAT NAMES ITS OWN REPOSITORY WINS
        OVER IT. That is not a design choice, it is what both vendors do, measured on both
        (2026-08-06):

            gh pr view <url of A#6> --repo <B>        answered A#6, silently ignoring --repo
            gh pr view 2 --repo <B>                   answered B#2 — the ref alone is ambiguous
            GET git/pullrequests/13  (project-scoped)  answered the PR's own repository

        So `repo` is what makes a bare `13` or `#4` addressable at all, and a caller holding a URL
        may pass it anyway — the product path does, because the intent belongs on the line. What
        it can never do is REDIRECT a pull request that already knows where it lives, which is the
        one reading of this argument that could merge the wrong thing.

        TRIGGERING IS NOT MERGING, on either vendor. GitHub arms `--auto`; Azure DevOps arms
        auto-complete and completes ASYNCHRONOUSLY (measured: the arming PATCH answered `active`
        and the PR read `completed` seconds later). Nothing here verifies its own result — a
        caller that needs the verdict reads `pr_status` back, and must expect to poll for it."""
        ...

    def close_pr(self, *, pr: str, reason: str = "") -> None:
        """Close a pull request WITHOUT merging it (#68) — the human answered `discard`.

        NOTHING IS DELETED. The branch and its commits stay exactly where they are, so a discard
        is reversible: somebody can reopen the PR or cut a new one from the same work. That is why
        this needs no password gate, unlike a production release — and it is worth stating on the
        port, because the word 'discard' promises more destruction than the operation performs."""
        ...

    def pr_merged(self, *, pr: str) -> bool:
        """Whether the PR has actually been merged — the immediate post-merge check the
        auto-merge path uses to tell an armed --auto (still pending CI) from a real merge."""
        ...

    def pr_status(self, *, pr: str, repo: str = "") -> str:
        """The PR's lifecycle state for the durable merge-watch: "merged" | "closed" |
        "open". "closed" = a human closed it WITHOUT merging, so the watch must stop and
        hand back (ADR-0007) instead of polling until the merge deadline.

        `repo` follows the same rule as `merge_pr`'s — it disambiguates a bare ref, and a pull
        request that names its own repository wins over it.

        THE SECOND CALLER IS THE PROPOSAL SWEEP, and it is why this had to widen (#95). Given a
        `req/*` branch that still exists and a pull request that exists, "merged" and "open" lead
        to opposite acts: delete the leftover branch, or finish the merge. `pr_for_head` answers
        WHETHER a branch was ever proposed and deliberately not which state it is in, so without
        this the sweep could see every stuck proposal on a docs repository and act on none of them.

        RAISES rather than guessing when the state cannot be read. "open" would send the sweep on
        to merge something already merged, "merged" would drop a live proposal out of its
        attention for ever; both are worse than a retry."""
        ...

    def disable_auto_merge(self, *, pr: str) -> None:
        """Disarm a previously-armed auto-merge (best-effort) — used when a CI-repair pass
        adds a gate suppression and the change must go to a human, not auto-merge on green."""
        ...

    def pr_ci_status(self, *, pr: str) -> str:
        """Aggregate the forge-side CI state for the PR's head: "success" (all required
        checks passed), "failure" (any failed), "pending" (still running/queued), or
        "none" (no checks). The durable workflow polls this to react to CI (ADR-0004)."""
        ...

    def failed_ci_logs(self, *, pr: str) -> str:
        """The (redacted, tail-truncated) logs of the PR's FAILING CI jobs — fed to the
        agent as the repair input so it fixes the CI like a developer would. Empty if
        nothing is failing or logs are unavailable."""
        ...

    def pr_diff(self, *, pr: str, repo: str = "", max_chars: int = 60000) -> str | None:
        """The pull request's own changes as a unified diff — or None when it could not be read.

        THE FACT THIS PORT NEVER HAD, and the one the tech-lead is asked about most (#171). It can
        read a PR's STATE, its checks, its failing logs and its merge SHA; it could not read what
        the pull request actually CHANGES. So "can I merge this?" was answered from a stored review
        verdict written by a different pass at a different time — which is why #153 happened at
        all: it quoted a two-hour-old rejection and recommended discarding the work that had
        already fixed it. A human tech-lead re-reads the diff. This one could not.

        THE OPTION TYPE CARRIES THE WHOLE MEANING, and it is this port's own existing rule:

            None   could not look — no credential, refused, unreachable
            ""     looked, and there are no changes

        Those are opposite facts. Collapsing them is how a failed read becomes a claim about
        somebody's pull request, which is the discipline every read on this port already keeps.

        `repo` disambiguates a bare ref exactly as `pr_status`'s does. `max_chars` is the caller's
        bound: a large diff can dwarf every other fact it is shown beside, so it is TRUNCATED
        rather than refused, and the truncation says so in the text — a diff that stops mid-hunk
        with no marker reads as a change that ends there.
        """
        ...

    def pr_body(self, *, pr: str, repo: str = "") -> str | None:
        """The pull request's description as it stands — or None when it could not be read.

        THE PLATFORM WRITES THIS BODY AND COULD NEVER READ IT BACK (#187). It opens the pull
        request with a description that carries the review verdict, and every later pass rewrote
        the code underneath it while the text stayed exactly as first published. So the PR itself
        — where a reviewer naturally goes, and the ONLY surface a collaborator without the panel
        token has — presented a verdict about code that no longer existed as if it were current.

        The same option type as every other read on this port: None is "could not look", "" is a
        pull request whose description is genuinely empty. Amending from a failed read would
        replace somebody's description with a body built from nothing.
        """
        ...

    def set_pr_body(self, *, pr: str, body: str, repo: str = "") -> bool:
        """Replace the pull request's description. True when the forge accepted it.

        FALSE IS NOT AN EXCEPTION, for the reason `merge_pr`'s refusal is not: the caller is
        annotating a fact somewhere else, and a forge refusing a description edit must never fail
        the pass that was doing the work. It must also never be SILENT — a caller that ignores
        this returns to a body that still reads as current.
        """
        ...

    def pr_checks(self, *, pr: str) -> list[dict]:
        """Every check on the PR as {name, bucket, state} — the per-check detail behind
        `pr_ci_status`'s aggregate, for the panel's "what ran" view. Empty if none."""
        ...

    def merge_commit_sha(self, *, pr: str) -> str | None:
        """The SHA of the commit the PR merged into the base as — the exact commit the
        post-merge deploy runs on (ADR-0005). None if the PR isn't merged yet."""
        ...

    def deploy_run_status(self, *, sha: str, workflow: str) -> tuple[str, str | None]:
        """Observe the deploy workflow's run on commit `sha`: ("success"|"failure"|
        "pending"|"none", run_url). "none" = no run found yet for that workflow+sha (it
        may not have been dispatched). The deploy-watch polls this and only NOTIFIES —
        it never gates (ADR-0005)."""
        ...

    def dispatch_workflow(self, *, workflow: str, ref: str) -> None:
        """Trigger a `workflow_dispatch` CI workflow on `ref` — the on-demand e2e run an
        `e2e`-labelled ticket kicks off (ADR-0008). The platform then watches it via
        `latest_run` and reports pass/fail; it never implements anything."""
        ...

    def latest_run(self, *, workflow: str) -> dict | None:
        """The most recent run of `workflow` — {id, status, conclusion, url, created_at} — so
        the e2e-ticket can poll the run it just dispatched to completion. None if none."""
        ...

    def disabled_ci_paths(self, repo: str = "") -> list[str] | None:
        """Repo-relative paths of CI definitions the FORGE reports as switched off — or None
        when this provider cannot say (#117).

        THREE ANSWERS, NOT TWO, and the middle one is the whole point. `None` means "I could not
        find out"; `[]` means "I asked and none are disabled". Collapsing them would make a forge
        that cannot answer indistinguishable from a repository whose pipelines are all live, which
        is the shape that produced this method.

        WHY IT EXISTS. `onboarding/infer.py` is offline and vendor-neutral by design: it reads
        files. On disk a retired workflow is byte-identical to a living one, so the pilot's
        proposal carried `uv run bandit -c pyproject.toml -r src` read verbatim from a `ci.yml`
        whose forge state is `disabled_manually` — cited as "observed from ci.yml", with full
        confidence, and the box proof then failed on a gate the client had deliberately turned
        off. The inference cannot know; the ONBOARDING has a forge and can ask.

        The next deployment makes it worse rather than better: an enterprise arrives with years of
        retired pipelines sitting beside the living ones, in the same directory, under the same
        extension.

        A PROVIDER THAT CANNOT ANSWER RETURNS None AND IS NOT WRONG. It costs the client a
        question they must answer themselves, which is what they had before; returning `[]`
        instead would cost them a silent false claim, which is what this fixes.
        """
        ...

    def latest_tag(self) -> str | None:
        """The latest release tag (for the prod version picker), or None."""
        ...

    def create_tag(self, *, tag: str, ref: str) -> None:
        """Cut a release tag at `ref` (the prod trigger, D-12). MUST be idempotent:
        a retry when the tag already exists is a no-op, never a duplicate/error —
        the durable runtime auto-retries activities (ADR-0001 D-16)."""
        ...


@runtime_checkable
class RepositoryCreatingForge(Protocol):
    """A forge that can CREATE a repository in a client's organisation.

    A SEPARATE PROTOCOL, ON PURPOSE — the `ConfirmingChannel` pattern, for the same reason. The
    core surface above is what the platform needs of every forge; this is a capability only some
    have, and some deployments will deliberately withhold it. Folding it into `ForgeAdapter` would
    make every adapter and every test double claim an ability they may not have, and an
    `isinstance` check that lies is worse than one that says no. Callers ask
    `isinstance(forge, RepositoryCreatingForge)` and say so plainly when the answer is no.

    WHY THE CORE NEEDS IT AT ALL — the justification the three-method rule demands. #99 slice 2b:
    the product role must write requirements somewhere, and `ProductConfig.docs_repo` is required
    because *"a product module with nowhere to write requirements is not a configuration, it is a
    mistake."* The product owner decided where that somewhere is (2026-08-07): *"sempre na org
    do cliente. Definimos que se o cliente não tiver um repositório de contexto temos que criar
    um."*

    Measured before it was written: nothing in `sdlc/` created or cloned a repository. So a client
    who already has a context repository could be onboarded and a client who did not could not be
    — which is most of them, and it is the first hour of the engagement.

    IT IS THE MOST CONSEQUENTIAL THING THIS PLATFORM ASKS OF A CREDENTIAL. Everything else edits
    inside a repository somebody already pointed us at; this makes a new one in their
    organisation, under their name, visible to their whole company. The caller gates it on an
    explicit yes — the protocol does not, because a protocol that enforced consent would be two
    concerns in one seam and the gate belongs where the human is.
    """

    def create_repository(self, *, name: str, private: bool = True,
                          description: str = "") -> tuple[str, bool]:
        """`(repo, created)` — the `owner/name` that now exists, and whether WE made it.

        IDEMPOTENT, AND THE SECOND VALUE IS WHY. A repository that already exists is the expected
        case, not a failure: a client may have made it themselves, an earlier onboarding may have
        made it, or this may be a retry of an activity the durable runtime is re-running. So
        "already there" returns normally — and says so, because "we created a repository in your
        organisation" and "we found the one you already had" are different sentences to a client,
        and only one of them needs to be in an email.

        RAISES when it cannot tell. A refusal that reads as success would have the onboarding
        report a repository nobody can push to, and the first sign would be the product role
        failing to write a requirement an hour later, in a message about something else.
        """
        ...
