"""GitHubForge — branches, PRs, reviews, merges via the `gh` CLI (v1).

Runs as the bot when a token is provided (GH_TOKEN in the subprocess env); falls
back to ambient `gh` auth otherwise (dev only).
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import urllib.parse

from openfactory.adapters.forge.base import ForgeAdapter, ReviewEvent
from openfactory.adapters.forge.base import truncated as _truncated

log = logging.getLogger("openfactory.forge.github")


def discover_token() -> str | None:
    """The `gh` login's token on THIS machine, or None — never raises, never logs the value.

    THE GITHUB FORGE'S OWN CAPABILITY, reached through the credential registry's `github` row.
    It lived in `cli.py` as `_gh_token_if_logged_in`, which made the core spawn a vendor's CLI
    by name on a path that asks "what forge did you choose?" one line earlier. A convenience
    with a warning attached at the call site: it is a PERSON's credential, so the factory would
    commit as them. The generator says so in its remaining-steps list rather than here, because
    this function's job is only to answer whether one exists."""
    try:
        done = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    return (done.stdout or "").strip() or None if done.returncode == 0 else None

_EVENT_FLAG = {
    "approve": "--approve",
    "comment": "--comment",
    "request-changes": "--request-changes",
}


def _ci_status_from_checks(checks: list[dict]) -> str:
    """Aggregate `gh pr checks --json bucket` rows into one CI state. Fail wins over pending
    wins over pass; an empty set is "none". `skipping`/`cancel` are treated conservatively:
    cancel → failure (a cancelled required check must not read as green); skipping → ignored."""
    if not checks:
        return "none"
    buckets = {(c.get("bucket") or "").lower() for c in checks}
    if "fail" in buckets or "cancel" in buckets:
        return "failure"
    if "pending" in buckets:
        return "pending"
    return "success"


def _redact(text: str) -> str:
    """Strip any token embedded in an authenticated URL before it reaches a log/error."""
    return re.sub(r"(https://)[^@/\s]+@", r"\1***@", text or "")


class GitHubForge(ForgeAdapter):
    def __init__(self, repo: str, *, token: str | None = None, token_provider=None) -> None:
        self.repo = repo  # "owner/name"
        self._static_token = token
        self._token_provider = token_provider  # re-mints a fresh token at use (long jobs)

    @property
    def token(self) -> str | None:
        # resolved at each use so a job that outlives the ~1h App token still pushes (H3)
        return self._token_provider() if self._token_provider else self._static_token

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        if self.token:
            env["GH_TOKEN"] = self.token
        return env

    def _gh(self, args: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["gh", *args], capture_output=True, text=True, timeout=timeout, env=self._env()
        )

    def push_remote(self) -> str | None:
        # GitHub scheme: the token is the password for the x-access-token user.
        if not self.token:
            return None
        return f"https://x-access-token:{self.token}@github.com/{self.repo}.git"

    def authenticated_url(self, url: str) -> str:
        """`url` with this adapter's token as the x-access-token password — if it is on THIS
        GitHub, which for an Enterprise deployment is not github.com."""
        from openfactory.adapters.forge.base import carries_credentials, host_of

        token = self.token
        if not token or carries_credentials(url) or host_of(url) != self._host():
            return url
        return url.replace("https://", f"https://x-access-token:{token}@", 1)

    def _host(self) -> str:
        """Which GitHub this adapter is talking to — github.com, or an Enterprise deployment."""
        import os

        return (os.environ.get("GH_HOST") or os.environ.get("GITHUB_HOST")
                or "github.com").strip().lower()

    def clone_url(self, repo: str, *, token: str | None) -> str:
        """`https://x-access-token:<token>@<host>/<owner>/<name>.git`, or the plain URL.

        `GH_HOST` is honoured for the same reason `ticket_url` honours it: a GitHub Enterprise
        deployment is not on github.com, and a clone aimed there fails with a 404 that reads like a
        missing repository rather than like a wrong host. The bare `github.com` literal this
        replaced did not even have that."""
        host = self._host()
        name = (repo or self.repo or "").strip().strip("/")
        if token:
            return f"https://x-access-token:{token}@{host}/{name}.git"
        return f"https://{host}/{name}.git"

    # ---- reading an ARBITRARY repository -------------------------------------------------------

    def _repo_or_self(self, repo: str) -> str:
        """`owner/name` for whichever repository the caller meant. "" means this adapter's own."""
        return (repo or "").strip().strip("/") or self.repo

    def _gh_read(self, args: list[str], what: str) -> subprocess.CompletedProcess[str] | None:
        """`_gh` for the three reads below, with a FAILURE OF THE PROCESS folded into "could not
        read" instead of thrown. None = the command never produced an answer at all.

        `subprocess.run` does not answer for every failure — it RAISES for two of them: a `gh` that
        hangs past the 120s timeout (`TimeoutExpired`) and a `gh` that is not on PATH in the first
        place (`FileNotFoundError`, the shape a worker image without the CLI takes). Every other
        method in this class lets those escape, and for a write that is right: a PR that could not
        be opened must stop the job. These three are different, and the port says so in two places
        — `delete_branch` promises NEVER RAISES because its caller is an hourly convergence sweep
        that must survive one bad hour, and both reads promise None as the word for a failed read.
        An escaping exception is a third answer no caller is written for, and the Azure sibling
        does not produce it: its transport errors already arrive as `AzureDevOpsError` and come
        back as None/False. Two providers behind one port must fail in the same vocabulary, or the
        product's claim that a provider is configuration stops being true at the first timeout.
        """
        try:
            return self._gh(args)
        except (subprocess.SubprocessError, OSError) as exc:
            # `gh` never answered, so there is nothing to parse and nothing to conclude.
            log.warning("gh could not be run to %s: %s", what, _redact(str(exc))[:200])
            return None

    def list_branches(self, repo: str = "", *, prefix: str = "") -> list[str] | None:
        """Bare branch names, filtered server-side by `prefix`. `[]` = none; `None` = unreadable.

        `git/matching-refs/heads/<prefix>` RATHER THAN `/branches`, which is what the product
        module shells out to today. The branches route cannot filter, so a documentation
        repository with a thousand branches is paged through in full to find nine `req/*` ones.
        Verified live on this platform's own GitHub repository: matching-refs answers `[]` for a
        prefix nothing matches and 404s for a repository that is not there — exactly the two-answer
        split this method has to make — and it answers an ARRAY even when one ref matches, unlike
        the older `git/refs/{ref}` route, which answers a bare object and would break a parser on
        the single-branch repository.

        `--paginate` IS LOAD-BEARING AND ONE `json.loads` IS ENOUGH, which is two facts that argue
        with each other until you measure them. Without the flag GitHub hands back the first page
        and nothing that says there was a second, so a repository over `per_page` silently loses
        branches. With it, `gh` (2.83.2) MERGES the pages into a single JSON array rather than
        concatenating one document per page — checked by forcing `per_page=1` against a
        two-branch repository and finding no `][` anywhere in the output. A parser written for the
        concatenated shape would be defending against something this tool does not do.
        """
        import json as _json

        path = f"repos/{self._repo_or_self(repo)}/git/matching-refs/heads/"
        # `safe="/"` because a branch prefix is a path here: `req/` must stay two segments.
        path += urllib.parse.quote((prefix or "").lstrip("/"), safe="/")
        p = self._gh_read(["api", "--paginate", f"{path}?per_page=100"],
                          f"list the branches of {self._repo_or_self(repo)}")
        if p is None:
            return None  # `_gh_read` already logged why the command produced nothing
        if p.returncode != 0:
            log.warning("could not list the branches of %s: %s",
                        self._repo_or_self(repo), _redact(p.stderr)[-200:])
            return None
        try:
            rows = _json.loads(p.stdout or "[]")
        except ValueError:
            log.warning("gh api matching-refs returned output that is not JSON for %s",
                        self._repo_or_self(repo))
            return None
        if not isinstance(rows, list):
            # An answer we do not understand is not an empty repository. `[]` here would tell the
            # product module there are no proposals in flight and let it mint a number already
            # taken by one.
            log.warning("gh api matching-refs answered a %s rather than a list for %s",
                        type(rows).__name__, self._repo_or_self(repo))
            return None
        names = [str((r or {}).get("ref") or "") for r in rows if isinstance(r, dict)]
        return [n.removeprefix("refs/heads/") for n in names if n.startswith("refs/heads/")]

    def delete_branch(self, name: str, *, repo: str = "") -> bool:
        """True when the branch is gone, False when it may still be there. See the port.

        THE EXIT STATUS IS NOT THE ANSWER, and that is the whole method. `gh api -X DELETE
        repos/…/git/refs/heads/<b>` answers `422 Reference does not exist` for a branch that was
        already deleted and `403` for one the credential may not touch, and both exit 1 — so a
        provider that returns `p.returncode == 0` reports a refusal as a successful cleanup and a
        sweep re-tries it hourly for ever with nothing in the log. Both statuses were observed
        live against this repository (the 422 by deleting a branch that does not exist, which is
        a request that changes nothing).

        So a failure is resolved by RE-READING the refs, which is the only evidence that settles
        it. A re-read that itself fails is False: not knowing is not the same as gone, and this
        method's False costs one wasted sweep while a wrong True loses the branch from the sweep's
        attention permanently.
        """
        branch = (name or "").strip().strip("/")
        if not branch:
            log.warning("refusing to delete an unnamed branch in %s", self._repo_or_self(repo))
            return False
        target = self._repo_or_self(repo)
        p = self._gh_read(["api", "-X", "DELETE", f"repos/{target}/git/refs/heads/{branch}"],
                          f"delete {branch} in {target}")
        if p is None:
            # `gh` never ran, so the branch is certainly still there. False is the answer that
            # keeps it in the sweep's attention, which is what NEVER RAISES buys.
            return False
        if p.returncode == 0:
            return True
        present = self.list_branches(target, prefix=branch)
        if present is None:
            log.warning("could not delete %s in %s (%s) and could not re-read the branch list "
                        "either — reporting it as still there", branch, target,
                        _redact(p.stderr)[-160:])
            return False
        if branch in present:
            log.warning("%s in %s was NOT deleted (%s) — it is still on the remote",
                        branch, target, _redact(p.stderr)[-200:])
            return False
        log.info("%s was already gone from %s — nothing to delete", branch, target)
        return True

    def pr_for_head(self, head: str, *, repo: str = "") -> str | None:
        """The newest pull request opened from `head`, any state. "" = none; None = unreadable.

        SORTED HERE RATHER THAN TRUSTED FROM `gh`. A `req/*` branch really can carry several pull
        requests — proven on the Azure side, where one probe branch answered three — and "the
        newest" is only meaningful if something guarantees the order. `gh pr list` happens to sort
        newest-first today; asking for `createdAt` and taking the maximum makes that a property of
        this method instead of a property of a CLI's default, and costs one JSON field.

        A NON-LIST ANSWER IS UNREADABLE, NOT AN ABSENCE — the same check `list_branches` makes two
        methods up, which is where it was learned. Iterating a JSON OBJECT yields its keys, so
        `{"message": "Moved Permanently"}` survives `json.loads`, filters down to no rows and reads
        as `""`: this branch was never proposed. That is the single answer that makes the caller
        open a duplicate pull request, and it is the collapse the whole port exists to prevent.
        """
        import json as _json

        p = self._gh_read(["pr", "list", "--repo", self._repo_or_self(repo), "--head", head,
                           "--state", "all", "--json", "url,createdAt"],
                          f"look up the pull requests for {head}")
        if p is None:
            return None
        if p.returncode != 0:
            log.warning("could not look up the pull requests for %s: %s",
                        head, _redact(p.stderr)[-200:])
            return None
        try:
            answer = _json.loads(p.stdout or "[]")
        except ValueError:
            log.warning("gh pr list returned malformed JSON for head %s", head)
            return None
        if not isinstance(answer, list):
            log.warning("gh pr list answered a %s rather than a list for head %s — unreadable, "
                        "not absent", type(answer).__name__, head)
            return None
        if not answer:
            return ""
        rows = [r for r in answer if isinstance(r, dict)]
        if not rows:
            log.warning("gh pr list answered %d rows this adapter cannot read for head %s",
                        len(answer), head)
            return None
        newest = max(rows, key=lambda r: str(r.get("createdAt") or ""))
        # A row with no URL is an answer we cannot use, not an absent pull request.
        return (str(newest.get("url") or "").strip() or None)

    # ---- pull requests -------------------------------------------------------------------------

    def open_pr(self, *, head: str, base: str, title: str, body: str, repo: str = "") -> str:
        target = self._repo_or_self(repo)
        # Idempotent (D-16): if an open PR already exists for this branch — a retry,
        # or a re-triggered job — return it instead of opening a second one. Scoped to `target`
        # and not to `self.repo`: on the product path this is the DOCS repository, and a lookup
        # aimed at the code would answer "no PR" about every proposal ever made.
        existing = self._open_pr_for_head(head, repo=target)
        if existing:
            return existing
        p = self._gh(
            ["pr", "create", "--repo", target, "--head", head, "--base", base,
             "--title", title, "--body", body]
        )
        if p.returncode != 0:
            try:  # lost a race with a concurrent create?
                recovered = self._open_pr_for_head(head, repo=target)
            except RuntimeError as exc:
                # We lost a race and then could not find the winner either — the caller will treat
                # this as "no PR", which is the one case where a duplicate can be opened.
                log.warning("could not recover the PR for %s after a race (%s)",
                            head, str(exc)[:120])
                recovered = None
            if recovered:
                return recovered
            raise RuntimeError(f"gh pr create failed: {_redact(p.stderr)}")
        return p.stdout.strip()

    def _open_pr_for_head(self, head: str, *, repo: str = "") -> str | None:
        """The OPEN pull request on `repo` ("" = this adapter's own), or None — `open_pr`'s
        idempotency check and nothing else.

        RENAMED AWAY FROM `_pr_for_head` when the public `pr_for_head` arrived, because the two
        differ by one underscore and disagree about what None means: here None is "there is no
        open PR" and a failed lookup RAISES; there None is "I could not read" and a clean empty
        answer is "". Two neighbouring methods with inverted sentinels is the kind of collision
        that gets found by a duplicate pull request in production."""
        p = self._gh(
            ["pr", "list", "--repo", self._repo_or_self(repo), "--head", head, "--state", "open",
             "--json", "url", "--jq", ".[0].url"]
        )
        # a FAILED lookup is "unknown", not "no PR" — raise so callers don't blindly
        # create a duplicate on a transient error (idempotency, engineering.md #3).
        if p.returncode != 0:
            raise RuntimeError(f"gh pr list failed: {_redact(p.stderr)}")
        return p.stdout.strip() or None

    def review_pr(self, *, pr: str, event: ReviewEvent, body: str) -> None:
        self._gh(["pr", "review", pr, "--repo", self.repo, _EVENT_FLAG[event], "--body", body])

    def request_reviewers(self, *, pr: str, reviewers: list[str]) -> None:
        if not reviewers:
            return
        self._gh(["pr", "edit", pr, "--repo", self.repo, "--add-reviewer", ",".join(reviewers)])

    def merge_pr(self, *, pr: str, repo: str = "") -> None:
        # --auto arms auto-merge (merges once required checks pass) — but it needs the
        # repo to have auto-merge + branch protection enabled. Where it doesn't, fall
        # back to an immediate squash merge so the autonomy chain isn't broken (A3).
        target = self._repo_or_self(repo)
        p = self._gh(["pr", "merge", pr, "--repo", target, "--squash", "--auto"])
        if p.returncode != 0:
            p = self._gh(["pr", "merge", pr, "--repo", target, "--squash"])
            if p.returncode != 0:
                raise RuntimeError(f"gh pr merge failed: {_redact(p.stderr)}")

    def force_merge(self, *, pr: str) -> None:
        """Merge NOW, bypassing the up-to-date / required-check gate — the executable option a
        human picks when a PR keeps starving behind a busy base (owner: the factory acts on the
        decision). Uses admin override; raises if even that is refused (then it stays parked)."""
        p = self._gh(["pr", "merge", pr, "--repo", self.repo, "--squash", "--admin"])
        if p.returncode != 0:
            raise RuntimeError(f"gh pr merge --admin failed: {_redact(p.stderr)}")

    def close_pr(self, *, pr: str, reason: str = "") -> None:
        """`gh pr close` — closes without merging and LEAVES THE BRANCH. Deliberately no
        `--delete-branch`: the work must survive a discard, so the answer is reversible."""
        argv = ["pr", "close", pr, "--repo", self.repo]
        if reason.strip():
            argv += ["--comment", reason.strip()[:500]]
        p = self._gh(argv)
        if p.returncode != 0:
            raise RuntimeError(f"gh pr close failed: {_redact(p.stderr)}")

    def pr_merged(self, *, pr: str) -> bool:
        """Whether the PR (URL or number) has actually been merged — the workflow's
        durable wait-for-merge gate before promotion (A2)."""
        import json as _json

        p = self._gh(["pr", "view", pr, "--repo", self.repo, "--json", "mergedAt"])
        if p.returncode != 0:
            raise RuntimeError(f"gh pr view failed: {_redact(p.stderr)}")
        try:
            return bool(_json.loads(p.stdout or "{}").get("mergedAt"))
        except ValueError as exc:
            raise RuntimeError("gh pr view returned malformed JSON") from exc

    def pr_status(self, *, pr: str, repo: str = "") -> str:
        """The PR's lifecycle state for the durable merge-watch: "merged" | "closed" | "open".
        A `mergedAt` timestamp wins (state may lag). "closed" means a human closed the PR
        WITHOUT merging — the watch must stop immediately instead of polling until the merge
        deadline (which would freeze the floor for days on a floor of one). "open" keeps the
        watch going. Reads state+mergedAt in ONE call so the poll adds no extra history.

        `repo` is the port's rule: "" is this adapter's own, and a `pr` that is a full URL wins
        over it — measured, `gh pr view <url of A#6> --repo <B>` answers A#6 and says nothing
        about the argument it ignored. It matters for a BARE number, where `--repo` is the only
        thing that decides which repository's #2 the answer is about."""
        import json as _json

        p = self._gh(["pr", "view", pr, "--repo", self._repo_or_self(repo),
                      "--json", "state,mergedAt"])
        if p.returncode != 0:
            raise RuntimeError(f"gh pr view failed: {_redact(p.stderr)}")
        try:
            data = _json.loads(p.stdout or "{}")
        except ValueError as exc:
            raise RuntimeError("gh pr view returned malformed JSON") from exc
        if data.get("mergedAt"):
            return "merged"
        if (data.get("state") or "").upper() == "CLOSED":
            return "closed"
        return "open"

    def mergeable_state(self, *, pr: str) -> str:
        """The PR's mergeability, so the merge-watch can KEEP IT FRESH instead of waiting on a
        merge that will never fire. GitHub's mergeStateStatus, lowercased: 'clean' (ready to
        merge), 'behind' (base advanced — needs an update or auto-merge stalls), 'blocked'
        (required checks pending/failing or a review required), 'dirty' (conflicts — a human
        must resolve), 'unstable'/'has_hooks', or 'unknown'. Best-effort — 'unknown' on error so
        the loop degrades to plain polling rather than crashing."""
        import json as _json

        p = self._gh(["pr", "view", pr, "--repo", self.repo, "--json", "mergeStateStatus"])
        if p.returncode != 0:
            return "unknown"
        try:
            return (_json.loads(p.stdout or "{}").get("mergeStateStatus") or "unknown").lower()
        except ValueError:
            return "unknown"

    def update_branch(self, *, pr: str) -> bool:
        """Bring a BEHIND PR branch up to date with its base so auto-merge can proceed (the
        self-heal for busy-main starvation: other developers keep advancing main, our single
        PR falls behind). Uses GitHub's update-branch API. Best-effort — True if accepted.

        THE REPO COMES FROM THE URL when the PR is one (C-18): every sibling op hands `pr` to
        the gh CLI, which resolves owner/repo from a URL itself — this is the one op composed
        as a REST path, and `self.repo` here silently updated a same-numbered PR in the DEFAULT
        repo when the card lived in another."""
        num = pr.rstrip("/").rsplit("/", 1)[-1]
        repo = self.repo
        if "github.com/" in pr:
            tail = pr.split("github.com/", 1)[1].split("/pull", 1)[0]
            repo = tail if "/" in tail else repo
        p = self._gh(["api", "--method", "PUT",
                      f"repos/{repo}/pulls/{num}/update-branch"])
        return p.returncode == 0

    def disable_auto_merge(self, *, pr: str) -> None:
        """Disarm a previously-armed `--auto` merge (best-effort). Used when the CI-repair
        pass introduced a gate suppression: the change must go to a human, so auto-merge must
        NOT fire when CI next goes green. A no-op if auto-merge wasn't armed."""
        self._gh(["pr", "merge", pr, "--repo", self.repo, "--disable-auto"])

    def pr_ci_status(self, *, pr: str) -> str:
        import json as _json

        # `gh pr checks` normalizes check-runs AND status-contexts into a single `bucket`
        # (pass/fail/pending/skipping/cancel); it exits non-zero when checks fail/pend, so
        # parse stdout regardless of returncode. No checks → gh writes a message to stderr.
        # `--required` scopes to the checks that actually GATE the merge, so the CI-repair
        # loop reacts to the same failures `--auto` blocks on — a flaky ADVISORY check (e.g.
        # a non-required e2e) never triggers a spurious repair (ADR-0004).
        p = self._gh(["pr", "checks", pr, "--repo", self.repo, "--required", "--json", "bucket"])
        if not (p.stdout or "").strip():
            # TWO different sentences mean "nothing gates this merge", and only one was known:
            # "no checks reported" (a repo with no CI at all) and "no REQUIRED checks reported" —
            # a repo WITH workflows but WITHOUT branch protection, which is the commonest real
            # client shape there is. The moment fx-jira gained its ci.yml (F-02, 2026-08-05),
            # every status poll raised, the activity retried forever, and the merge watch died
            # on a repo that was perfectly healthy. CI existing does not mean CI is REQUIRED.
            stderr = (p.stderr or "").lower()
            if "no checks" in stderr or "no required checks" in stderr:
                return "none"
            raise RuntimeError(f"gh pr checks failed: {_redact(p.stderr)}")
        try:
            checks = _json.loads(p.stdout)
        except ValueError as exc:
            raise RuntimeError("gh pr checks returned malformed JSON") from exc
        return _ci_status_from_checks(checks)

    def pr_checks(self, *, pr: str) -> list[dict]:
        """Every check on the PR as {name, bucket, state} — for the panel's per-check view
        (which of lint/vitest/e2e/pg_integration/… ran and how they landed). Empty on none."""
        import json as _json

        p = self._gh(["pr", "checks", pr, "--repo", self.repo, "--json", "name,bucket,state"])
        if not (p.stdout or "").strip():
            return []
        try:
            rows = _json.loads(p.stdout)
        except ValueError:
            return []
        return [
            {"name": r.get("name"), "bucket": r.get("bucket"), "state": r.get("state")}
            for r in rows if isinstance(r, dict)
        ]

    def pr_body(self, *, pr: str, repo: str = "") -> str | None:
        """`gh pr view --json body` — the description, or None when the read failed.

        NONE AND "" ARE DIFFERENT ANSWERS, exactly as they are for `pr_diff` one method down: a
        pull request may genuinely have an empty description, and amending from a failed read
        would publish a body assembled out of nothing over whatever is really there."""
        got = self._gh(["pr", "view", pr, "--repo", repo or self.repo, "--json", "body",
                        "-q", ".body"])
        if got.returncode != 0:
            log.warning("could not read the description of %s (%s)", pr,
                        (got.stderr or "").strip()[:160])
            return None
        # `-q .body` prints the field and a trailing newline; an empty description prints just
        # that newline, which is "" and not None.
        return (got.stdout or "").rstrip("\n")

    def set_pr_body(self, *, pr: str, body: str, repo: str = "") -> bool:
        """`gh pr edit --body` — True when the forge took it."""
        done = self._gh(["pr", "edit", pr, "--repo", repo or self.repo, "--body", body])
        if done.returncode != 0:
            log.warning("could not update the description of %s (%s)", pr,
                        (done.stderr or "").strip()[:160])
            return False
        return True

    def pr_diff(self, *, pr: str, repo: str = "", max_chars: int = 60000) -> str | None:
        """`gh pr diff` — the changes themselves, or None when the read failed.

        NONE AND "" ARE DIFFERENT ANSWERS. `gh` exits non-zero when it cannot see the pull request
        (no credential, wrong repo, rate limit); it exits ZERO with empty output for a pull request
        that genuinely changes nothing. Reporting the first as the second tells a reader their diff
        is empty when the platform simply could not look.
        """
        got = self._gh(["pr", "diff", pr, "--repo", repo or self.repo])
        if got.returncode != 0:
            log.warning("could not read the diff of %s (%s)", pr,
                        (got.stderr or "").strip()[:160])
            return None
        return _truncated(_redact(got.stdout or ""), max_chars)

    def failed_ci_logs(self, *, pr: str, max_chars: int = 6000) -> str:
        import json as _json

        head = self._gh(["pr", "view", pr, "--repo", self.repo, "--json", "headRefName"])
        try:
            branch = _json.loads(head.stdout or "{}").get("headRefName", "")
        except ValueError:
            # `gh` returned something we cannot parse. Every CI read below is derived from this, so
            # an unreadable answer reads downstream as "no CI at all".
            log.warning("could not read the PR's head branch from gh output")
            branch = ""
        if not branch:
            return ""
        runs = self._gh([
            "run", "list", "--repo", self.repo, "--branch", branch,
            "--json", "databaseId,conclusion", "--limit", "20",
        ])
        try:
            rl = _json.loads(runs.stdout or "[]")
        except ValueError:
            log.warning("could not read the workflow runs from gh output")
            rl = []
        failed = [r["databaseId"] for r in rl if (r.get("conclusion") or "").lower() == "failure"]
        chunks: list[str] = []
        for rid in failed[:2]:  # newest failing runs
            lp = self._gh(
                ["run", "view", str(rid), "--repo", self.repo, "--log-failed"], timeout=180
            )
            if lp.returncode == 0 and lp.stdout:
                chunks.append(lp.stdout)
        return _redact("\n".join(chunks))[-max_chars:]

    def merge_commit_sha(self, *, pr: str) -> str | None:
        import json as _json

        p = self._gh(["pr", "view", pr, "--repo", self.repo, "--json", "mergeCommit"])
        if p.returncode != 0:
            raise RuntimeError(f"gh pr view failed: {_redact(p.stderr)}")
        try:
            mc = _json.loads(p.stdout or "{}").get("mergeCommit") or {}
        except ValueError as exc:
            raise RuntimeError("gh pr view returned malformed JSON") from exc
        return (mc.get("oid") or "").strip() or None

    def deploy_run_status(self, *, sha: str, workflow: str) -> tuple[str, str | None]:
        import json as _json

        # Find the deploy workflow's run ON THIS COMMIT — scoped by --workflow (the deploy's
        # file/name) and matched on headSha so a later unrelated run never fools the watch.
        p = self._gh([
            "run", "list", "--repo", self.repo, "--workflow", workflow, "--limit", "30",
            "--json", "databaseId,headSha,status,conclusion,url",
        ])
        if p.returncode != 0:
            raise RuntimeError(f"gh run list failed: {_redact(p.stderr)}")
        try:
            runs = _json.loads(p.stdout or "[]")
        except ValueError as exc:
            raise RuntimeError("gh run list returned malformed JSON") from exc
        run = next((r for r in runs if (r.get("headSha") or "") == sha), None)
        if not run:
            return "none", None
        url = run.get("url")
        # A run that hasn't reached "completed" is still deploying — pending, not judged.
        if (run.get("status") or "").lower() != "completed":
            return "pending", url
        return ("success" if (run.get("conclusion") or "").lower() == "success"
                else "failure"), url

    def dispatch_workflow(self, *, workflow: str, ref: str) -> None:
        """Trigger a `workflow_dispatch` GitHub Actions workflow (on-demand e2e, ADR-0008)."""
        p = self._gh(["workflow", "run", workflow, "--repo", self.repo, "--ref", ref])
        if p.returncode != 0:
            raise RuntimeError(f"gh workflow run {workflow} failed: {_redact(p.stderr)}")

    def latest_run(self, *, workflow: str) -> dict | None:
        """The most recent run of `workflow` as {id, status, conclusion, url, created_at} —
        for polling a just-dispatched run to completion. None if there are none."""
        import json as _json

        p = self._gh([
            "run", "list", "--repo", self.repo, "--workflow", workflow, "--limit", "1",
            "--json", "databaseId,status,conclusion,url,createdAt",
        ])
        if p.returncode != 0:
            raise RuntimeError(f"gh run list failed: {_redact(p.stderr)}")
        try:
            rows = _json.loads(p.stdout or "[]")
        except ValueError:
            return None
        if not rows:
            return None
        r = rows[0]
        return {"id": r.get("databaseId"), "status": r.get("status"),
                "conclusion": r.get("conclusion"), "url": r.get("url"),
                "created_at": r.get("createdAt")}

    def create_repository(self, *, name: str, private: bool = True,
                          description: str = "") -> tuple[str, bool]:
        """See `RepositoryCreatingForge`. `(owner/name, created)`.

        THE OWNER COMES FROM THE PROJECT'S OWN REPO, never from a parameter. A caller that could
        name the organisation could create a repository in one this deployment was never pointed
        at — and the credential is an installation with write access to a client's org, so that is
        not a hypothetical. `name` is the repository only; the org is where this project already
        lives.

        EXISTENCE IS CHECKED FIRST, and the check is what makes this idempotent: `gh repo create`
        fails with "Name already exists" and that failure is indistinguishable, by exit status,
        from a permission refusal. Asking first turns the expected case into a normal return and
        leaves the raise for the case that genuinely cannot proceed.
        """
        owner = (self.repo or "").split("/")[0].strip()
        if not owner:
            raise ValueError(
                "cannot create a repository: this project does not name an `owner/name` repo, so "
                "there is no organisation to create it in. Refusing to guess one — the credential "
                "here can write to a client's whole organisation.")
        bare = name.strip().strip("/").split("/")[-1]
        if not bare:
            raise ValueError(f"cannot create a repository called {name!r}")
        full = f"{owner}/{bare}"

        seen = self._gh_read(["repo", "view", full, "--json", "name"], f"look up {full}")
        if seen is not None and seen.returncode == 0:
            return full, False

        made = self._gh(["repo", "create", full,
                         "--private" if private else "--public",
                         *(["--description", description] if description else [])])
        if made.returncode != 0:
            err = (made.stderr or made.stdout or "").strip()
            if "not accessible by integration" not in err.lower():
                raise RuntimeError(f"could not create {full}: {err[:300]}")
            # `gh repo create` is a GraphQL mutation GitHub refuses to EVERY App installation
            # token, and the raw refusal reads like a platform bug when it is a credential
            # class (pilot, 2026-08-13). What exists instead depends on who the owner is, so
            # the owner is asked first — the probe-then-decide the board setup already earned
            # on a live personal account.
            kind = self._gh(["api", f"users/{owner}", "--jq", ".type"])
            owner_type = (kind.stdout or "").strip() if kind.returncode == 0 else ""
            if owner_type == "Organization":
                rest = self._gh(["api", "--method", "POST", f"orgs/{owner}/repos",
                                 "-f", f"name={bare}",
                                 "-F", f"private={'true' if private else 'false'}",
                                 *(["-f", f"description={description}"] if description else [])])
                if rest.returncode != 0:
                    raise RuntimeError(
                        f"the GitHub App cannot create {full}: its Repository → Administration "
                        f"permission is not Read and write. Grant it on the App's settings "
                        f"page, accept the permission update on the installation "
                        f"(docs/setup/github.md §1), and re-run — this step is idempotent. Or "
                        f"create the repository yourself and declare it: "
                        f"`openfactory product declare <project> {full}`")
            else:
                raise RuntimeError(
                    f"a GitHub App token cannot create a repository on a personal account "
                    f"({owner} is a user, not an organisation) — no permission changes that. "
                    f"Two ways forward: keep the classic PAT the board already uses (scopes "
                    f"repo+project, docs/setup/github.md §6) in OPENFACTORY_TRACKER_TOKEN and "
                    f"re-run — the factory creates the repository with it; or create {full} "
                    f"yourself and declare it: `openfactory product declare <project> {full}`. "
                    f"Both are idempotent.")
        # RE-READ RATHER THAN TRUST THE EXIT STATUS, the same rule `delete_branch` documents one
        # screen up: `gh` has answered 0 for requests that changed nothing. A creation reported as
        # done over a repository that does not exist would have the product role fail to write a
        # requirement an hour later, in a message about something else entirely.
        again = self._gh_read(["repo", "view", full, "--json", "name"], f"confirm {full}")
        if again is None or again.returncode != 0:
            raise RuntimeError(
                f"{full} was reported created and cannot be read back — treating it as not "
                f"created, because a repository nobody can reach is worse than one nobody made")
        return full, True

    #: `state` values GitHub uses for a workflow that will not run. `active` is the only live one;
    #: everything else here means the file is on disk and the forge is ignoring it.
    #:
    #: LISTED RATHER THAN INVERTED (`!= "active"`) on purpose: a state GitHub adds later would
    #: otherwise be silently treated as disabled, and demoting a LIVE gate into a question is the
    #: error that costs a client their real CI. An unknown state stays live and is logged.
    _DEAD_STATES = frozenset({"disabled_manually", "disabled_inactivity", "disabled_fork"})

    def disabled_ci_paths(self, repo: str = "") -> list[str] | None:
        """Workflow files GitHub reports as switched off. `None` when the API would not answer.

        The state is a property of the FORGE, not of the file — which is the whole reason this
        exists: `.github/workflows/ci.yml` reads identically whether it runs on every push or has
        not run since somebody disabled it in the Actions tab (pilot, 2026-08-14)."""
        target = repo or self.repo
        p = self._gh_read(
            ["api", f"repos/{target}/actions/workflows?per_page=100",
             "--jq", ".workflows[] | .state + \"\\t\" + .path"],
            f"list the workflows of {target}")
        if p is None or p.returncode != 0:
            # NOT `[]`. A repository whose workflows we could not list is not a repository with no
            # disabled ones, and the caller renders those two differently by design.
            if p is not None:
                log.info("could not read the workflow states of %s (%s) — the onboarding will "
                         "not know which pipelines are switched off", target,
                         _redact(p.stderr)[:160])
            return None
        out: list[str] = []
        for line in p.stdout.splitlines():
            state, _tab, path = line.partition("\t")
            state, path = state.strip(), path.strip().lstrip("/")
            if not path:
                continue
            if state in self._DEAD_STATES:
                out.append(path)
            elif state != "active":
                log.info("%s reports workflow %s in state %r, which this adapter does not know — "
                         "treating it as live, because demoting a working gate is the more "
                         "expensive mistake", target, path, state)
        return sorted(set(out))

    def latest_tag(self) -> str | None:
        p = self._gh(["api", f"repos/{self.repo}/tags?per_page=1", "--jq", ".[0].name"])
        name = p.stdout.strip()
        return name or None

    def create_tag(self, *, tag: str, ref: str) -> None:
        # Idempotent (D-16): if the tag already exists, a retry is a no-op — never a
        # duplicate ref or an error. Otherwise resolve `ref` to a sha and create it.
        if self._tag_exists(tag):
            return
        sha = self._ref_sha(ref)
        p = self._gh(
            ["api", "--method", "POST", f"repos/{self.repo}/git/refs",
             "-f", f"ref=refs/tags/{tag}", "-f", f"sha={sha}"]
        )
        if p.returncode != 0:
            if self._tag_exists(tag):  # created concurrently between our check and POST
                return
            raise RuntimeError(f"create tag {tag} failed: {_redact(p.stderr)}")

    def _tag_exists(self, tag: str) -> bool:
        return self._gh(["api", f"repos/{self.repo}/git/ref/tags/{tag}"]).returncode == 0

    def _ref_sha(self, ref: str) -> str:
        p = self._gh(["api", f"repos/{self.repo}/commits/{ref}", "--jq", ".sha"])
        sha = p.stdout.strip()
        if not sha:
            raise RuntimeError(f"could not resolve sha for {ref!r}: {_redact(p.stderr)}")
        return sha
