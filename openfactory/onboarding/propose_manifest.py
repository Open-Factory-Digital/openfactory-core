"""Propose a project's manifest as a PULL REQUEST — the onboarding step, done server-side.

THE GAP THIS CLOSES, raised by the pilot operator on the day it mattered: *"how could this have
the option of running 100% in the cloud if there is a dependency on my
laptop?"* (2026-08-12). The
factory's own work never needed a personal machine — it clones, builds, tests, branches, opens
the pull request, watches the deploy, all where the stack runs. The exception was AUTHORING
`.openfactory/project.yaml`: `env apply` wrote a file into a checkout, so a project registered by
clone URL was refused, and somebody had to have the repository on a machine somewhere.

Writing it into the worker's own cache clone would be worse than the refusal: nobody reviews
that tree and the next fetch replaces it. The manifest belongs in the client's repository, in a
diff a human reads — which is exactly what a pull request is. The product module already
proposes requirements this way (`product/authoring.py`); this is the same shape for the
engineering half, and it deliberately reuses that module's hard-won arms:

    the idempotency question goes through the PORT (`pr_for_head`), because a `gh` lookup
    answers "" both for "never proposed" and for "could not reach the repository", and a caller
    writing `if not found: propose()` files the duplicate on the transient failure;

    a branch pushed with no pull request on it — the window a rate limit or a dying worker
    lands in — is FINISHED rather than re-pushed, because a second attempt's `push -u` is
    rejected as non-fast-forward and the verb wedges permanently;

    the commit carries the bot identity explicitly (`-c user.name=…`), because a clean
    container has no ambient git identity and git refuses the commit with "Please tell me who
    you are" — which is what a fresh deployment is.

NOT MERGED, and that is the point rather than a limitation: the manifest declares what the
factory will run against this repository, and a human reading it before it is true is the whole
reason it lives in the repository at all.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("openfactory.onboarding.propose_manifest")

_GIT_TIMEOUT = 180

#: Deterministic, so a retry finds its own pull request instead of opening a second one.
BRANCH = "openfactory/manifest"


@dataclass(frozen=True)
class Proposal:
    """What happened, in the terms a caller has to report."""

    ok: bool
    #: the pull request's URL when there is one
    url: str = ""
    #: the branch the proposal lives on, whatever else happened
    ref: str = ""
    #: True when this found work already proposed and did not propose it again
    existed: bool = False
    #: one sentence for a person — the failure, or what was done
    detail: str = ""
    #: the temporary clone, when the caller still needs to read from it
    checkout: Path | None = None


def _git(args: list[str], cwd: Path | None = None) -> tuple[int, str]:
    """One git call, authored as the bot — the identity carried, never assumed.

    A TIMEOUT IS AN ORDINARY OUTCOME HERE, AND ITS EXCEPTION CARRIES THE ARGV. `subprocess.run`
    raises `TimeoutExpired` whose `str()` includes the whole command — and one of these commands
    is `git clone https://openfactory:<token>@…`. Unguarded it would travel up as a traceback
    through the CLI, into a refusal string and into whatever log reads it: a live credential
    published by a slow network. Caught here, scrubbed, and returned as an ordinary failure the
    caller already knows how to report (pre-commit adversarial review, 2026-08-12)."""
    from openfactory.credentials import bot_identity

    bot = bot_identity()
    ident = ["-c", f"user.name={bot.name}", "-c", f"user.email={bot.email}"]
    try:
        p = subprocess.run(["git", *ident, *args], cwd=cwd, capture_output=True, text=True,
                           timeout=_GIT_TIMEOUT, check=False)
    except subprocess.TimeoutExpired:
        return 124, (f"git {args[0] if args else '?'} timed out after {_GIT_TIMEOUT}s — the "
                     f"repository may be large or the network slow; nothing was changed")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def scrub(text: str) -> str:
    """A token inside an authenticated remote URL never reaches a log or a message."""
    return re.sub(r"(https://)[^@/\s]+@", r"\1***@", text or "")


def default_branch(checkout: Path) -> str:
    """What the clone actually landed on — the repository's own default branch.

    ASKED, NEVER ASSUMED. The caller's `base` comes from `load_manifest_base_branch`, which
    answers `main` unless the registry names something else — so a client on `master` or
    `develop` got a pull request against a branch that does not exist, after the push had
    already happened (pre-commit review, 2026-08-12).

    ONE HOME FOR THE GIT QUESTION (#162). The reading lives in `repo_cache.current_branch`, which
    answers `""` for an absent tree, a corrupt one and a detached HEAD; this adds the fallback ITS
    caller needs — a manifest proposal has to name a branch, and `main` is the framework's word
    for "no idea". The cache needs the opposite, so the fallback belongs at the caller and the
    reading belongs in one place. Two copies of this drifted apart once already."""
    from openfactory.runtime.repo_cache import current_branch

    return current_branch(checkout) or "main"


def clone_for_proposal(*, clone_url: str, base: str = "",
                       history: bool = False) -> tuple[Path | None, str]:
    """A shallow checkout to read from and write into, or `(None, why)`.

    `base` empty clones the repository's OWN default branch, which is what a caller that does
    not know it should ask for — pinning `main` is how a `master` repository fails at the pull
    request, one step after the push.

    `history=True` asks for a checkout whose LOG can be read (`onboarding/history.py`). `--depth 1`
    carries exactly one commit, so every question about churn, authorship or age answers "1,
    everywhere" — and a caller that read that as an answer would rank every area of the repository
    identically. It clones `--filter=blob:none` rather than simply dropping the depth limit: that
    fetches the whole commit graph and the trees `--name-only` needs, while leaving every
    HISTORICAL file's content on the server, which on a fifteen-year monolith is the difference
    between seconds and an afternoon.

    A server without partial clone (`uploadpack.allowFilter`) refuses that, so the request DEGRADES
    to the shallow clone rather than to nothing: the backfill is then exactly as able as it was
    before this parameter existed, and `read_history` names the shallow checkout rather than
    reporting a quiet repository."""
    tmp = Path(tempfile.mkdtemp(prefix="openfactory-manifest-"))
    shallow = ["clone", "--depth", "1", *(["--branch", base] if base else []),
               clone_url, str(tmp)]
    rc, out = (_git(["clone", "--filter=blob:none", *(["--branch", base] if base else []),
                     clone_url, str(tmp)])
               if history else _git(shallow))
    if history and rc != 0:
        # `git clone` refuses a target directory that is not empty, and a failed clone leaves one
        # behind — so the retry cannot reuse `tmp` without this. Same reason as the branch below.
        log.info("partial clone refused, falling back to a shallow checkout: %s",
                 scrub(out)[-200:])
        shutil.rmtree(tmp, ignore_errors=True)
        tmp = Path(tempfile.mkdtemp(prefix="openfactory-manifest-"))
        shallow[-1] = str(tmp)
        rc, out = _git(shallow)
    if rc != 0:
        # REMOVED HERE, because the caller registers the directory for cleanup only when it gets
        # one back — so a failed clone left an empty directory in /tmp on every retry, and the
        # retries are exactly what a wrong branch name or a missing credential produces.
        shutil.rmtree(tmp, ignore_errors=True)
        return None, scrub(out)[-300:]
    # The clone's origin still carries the tokened URL in .git/config — and this checkout goes
    # on to HOST AGENTS (the backfill's ask pass reads the tree) and into the BOX PROOF, which
    # mounts it where the client's own setup:/validate: commands run. Nothing downstream needs
    # origin: every push passes the URL explicitly. So the credential leaves the tree the
    # moment the clone lands — the same rule repo_cache and the tech-lead's diagnosis clone
    # already enforce (adversarial review, 2026-08-13).
    _git(["-C", str(tmp), "remote", "set-url", "origin",
          re.sub(r"(https://)[^@/\s]+@", r"\1", clone_url)])
    return tmp, ""


def already_proposed(forge, repo: str, branch: str = BRANCH) -> str | None:
    """The pull request still OPEN for this branch — `""` for none, `None` for "could not ask".

    THE `None` ARM IS WHY THIS GOES THROUGH THE PORT: a `gh` lookup answers "" both for "never
    proposed" and for "could not reach the repository", and a caller writing
    `if not found: propose()` files the duplicate on the transient failure.

    STILL OPEN, not ever-proposed, and that difference is the whole verb. `pr_for_head` answers
    for ANY state by design — the product module wants that, because a requirement proposed once
    must never be proposed twice. A MANIFEST is the opposite: the first proposal is meant to be
    merged, and after that the project may legitimately need a corrected one. Reading the merged
    pull request as "already proposed" locked the verb for ever — every later run returned the
    old PR's URL and wrote nothing (pre-commit adversarial review, 2026-08-12). So the state is
    checked, and anything that is not open is treated as "propose again"."""
    if forge is None:
        return None
    try:
        found = (forge.pr_for_head(branch, repo=repo) or "").strip()
    except Exception:  # noqa: BLE001 — unreadable is not "there is none"
        log.info("could not ask %s whether %s was already proposed", repo, branch, exc_info=True)
        return None
    if not found:
        return ""
    try:
        state = (forge.pr_status(pr=found, repo=repo) or "").strip().lower()
    except Exception:  # noqa: BLE001 — the same rule as above: unreadable is not "it is closed"
        log.info("could not read the state of %s — treating it as still open, because "
                 "proposing over an open review is worse than not proposing", found,
                 exc_info=True)
        return found
    if state in ("merged", "closed", "abandoned", "completed"):
        log.info("the previous manifest proposal on %s is %s — proposing a fresh one",
                 branch, state)
        return ""
    return found


#: A provider saying "you are out of budget", in the words each one uses. Matched to tell a
#: WAIT from a FAILURE: the first clears by itself at a known time and the operator needs only
#: to be told when; the second needs them to do something. Reported as one thing, the wait reads
#: as a broken platform — which is how the pilot met it (2026-08-14).
_RATE_LIMITED = re.compile(
    r"rate limit|secondary rate|too many requests|\b429\b|abuse detection|quota exceeded",
    re.I)


def rate_limited(text: str) -> bool:
    """Whether a provider's refusal is a budget wait rather than a failure."""
    return bool(_RATE_LIMITED.search(text or ""))


#: Whether the LAST review request refused for budget. A module-level flag rather than a return
#: value because `open_review_request` promises `str` to several callers and widening that shape
#: would put a tuple through every one of them for a sentence only two of them say.
_LAST_WAS_RATE_LIMIT = False


def last_error_was_rate_limit() -> bool:
    """Whether the most recent `open_review_request` failed on a budget wait."""
    return _LAST_WAS_RATE_LIMIT


def open_review_request(forge, *, repo: str, head: str, base: str, title: str, body: str) -> str:
    """Open the pull request, or `""` — never a raise, because by the time this runs the
    manifest is committed and pushed, and losing that half to report the ceremony's failure
    tells the operator less than the branch name does."""
    global _LAST_WAS_RATE_LIMIT
    _LAST_WAS_RATE_LIMIT = False
    try:
        return (forge.open_pr(head=head, base=base, title=title, body=body, repo=repo)
                or "").strip()
    except Exception as exc:  # noqa: BLE001 — every provider's failure means the same here
        # A BUDGET WAIT IS NOT A FAILURE, and calling it one costs an hour of somebody
        # re-running a command that cannot work yet. Named here rather than at the call site
        # because this is where the provider's own words arrive.
        if rate_limited(str(exc)):
            _LAST_WAS_RATE_LIMIT = True
            log.warning("OPENFACTORY_PR_RATE_LIMITED repo=%s head=%s — the branch is pushed; "
                        "the review request is waiting on the API budget", repo, head)
        else:
            log.error("OPENFACTORY_MANIFEST_PR_CREATE_FAILED repo=%s head=%s (%s) — the manifest "
                      "is committed and pushed; only the review request did not open",
                      repo, head, exc)
        return ""


def propose(*, checkout: Path, manifest_path: str, repo: str, clone_url: str, base: str,
            forge, project_name: str, summary: str = "", branch: str = BRANCH,
            extra_paths: list[str] | None = None,
            title: str = "", body: str = "") -> Proposal:
    """Commit the manifest already written into `checkout` and open the pull request.

    The files are written by the caller — `env apply` composes and validates the manifest, and
    this module has no opinion about content beyond where it goes. `extra_paths` is the onboard
    verb's half (2026-08-13): the same pull request carries the module map (`knowledge/`), so
    the reviewer merges ONE declaration of how the repo is built, validated and navigated.
    `title`/`body` override the manifest-shaped defaults when the PR is about more than the
    manifest; empty keeps today's words byte for byte."""
    pushed_already = already_proposed(forge, repo, branch)
    if pushed_already is None:
        return Proposal(ok=False, ref=branch,
                        detail=f"could not ask {repo} whether this manifest was already "
                               f"proposed, so nothing was pushed — asking again in a moment is "
                               f"safer than opening a second pull request")
    if pushed_already.strip():
        return Proposal(ok=True, url=pushed_already.strip(), ref=branch, existed=True,
                        detail=f"the manifest was already proposed on {branch}")

    try:
        branches = {str(b) for b in (forge.list_branches(repo=repo) or ())}
    except Exception:  # noqa: BLE001 — an unreadable branch list is not a reason to write twice
        log.info("could not list %s's branches before proposing a manifest", repo, exc_info=True)
        branches = set()
    if branch in branches:
        # THE WEDGE ARM. The branch exists with no OPEN pull request on it. Two very different
        # histories put it there: an attempt that pushed and then died (finish it — open the
        # review request on what it pushed), or a proposal that was MERGED and left its ref
        # behind (there the forge refuses the zero-diff PR, and returning failure wedged the
        # verb permanently on every repository where it had already worked once — adversarial
        # review, 2026-08-13). The forge's answer tells the two apart, so a refused open FALLS
        # THROUGH to a fresh proposal instead of reporting a defect that is not there; the
        # force-push below overwrites the leftover ref, which is the platform's own.
        url = open_review_request(
            forge, repo=repo, head=branch, base=base,
            title=f"OpenFactory: declare how to build and validate {project_name}",
            body="This branch was pushed by an earlier attempt that never opened its pull "
                 "request. Opening it now — the content is that attempt's.")
        if url:
            return Proposal(ok=True, url=url, ref=branch, existed=True,
                            detail="the branch was already pushed; the review request was the "
                                   "part still missing, and it is open now")
        log.info("%s exists on %s but a review request would not open on it (likely a merged "
                 "proposal's leftover ref) — proposing fresh over it", branch, repo)

    rc, out = _git(["checkout", "-b", branch], cwd=checkout)
    if rc != 0:
        return Proposal(ok=False, ref=branch, detail=f"could not create {branch}: "
                                                     f"{scrub(out)[-200:]}")
    for path in (manifest_path, *(extra_paths or ())):
        rc, out = _git(["add", "--", path], cwd=checkout)
        if rc != 0:
            # a gitignored path silently staging nothing would surface two steps later as
            # "nothing to commit" — a misleading refusal about a file that exists
            return Proposal(ok=False, ref=branch,
                            detail=f"could not stage {path}: {scrub(out)[-200:]}")
    rc, out = _git(["commit", "-m",
                    f"chore: declare how OpenFactory builds and validates {project_name}\n\n"
                    f"{summary or 'Proposed from the repository, for a human to correct.'}"],
                   cwd=checkout)
    if rc != 0:
        return Proposal(ok=False, ref=branch,
                        detail=f"nothing to commit: {scrub(out)[-200:]}")
    # --force: this is the platform's OWN dedicated proposal branch, never a client's. A
    # previous proposal that was merged or closed leaves the ref behind, and a plain `push -u`
    # is then rejected as non-fast-forward — which would wedge the verb permanently on exactly
    # the repositories where it had already worked once. Same rule, same reason, as
    # `product init`'s onboarding branch.
    rc, out = _git(["push", "--force", "-u", clone_url, branch], cwd=checkout)
    if rc != 0:
        return Proposal(ok=False, ref=branch,
                        detail=f"could not push {branch}: {scrub(out)[-200:]}")

    url = open_review_request(
        forge, repo=repo, head=branch, base=base,
        title=title or f"OpenFactory: declare how to build and validate {project_name}",
        body=body or "\n".join([
            f"`{manifest_path}` declares what OpenFactory runs against this repository: the "
            f"setup commands, the validation gates it reads exit codes from, and the merge "
            f"policy.",
            "",
            "**It was read from this repository, not invented** — every field was proposed from "
            "what is actually here, and the fields nothing could answer were left out rather "
            "than guessed. The one that matters most is `validate.test`: a guessed test command "
            "that exits 0 having tested nothing is worse than none at all.",
            "",
            "Correct anything that is wrong and merge. Until this is merged, the factory has no "
            "declaration to obey for this repository.",
        ]))
    if not url:
        return Proposal(ok=True, ref=branch,
                        detail=f"the manifest is committed and pushed on {branch}, but the pull "
                               f"request did not open — open it by hand against {base}")
    return Proposal(ok=True, url=url, ref=branch,
                    detail=f"proposed as a pull request on {branch}")
