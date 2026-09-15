"""`forge.local` — the person's own repository is the forge (ADR-0049 D3, D4).

WHAT THIS ROW IS. Every other row on this axis reaches a service that hosts a copy of somebody's
repository and keeps a pull request in its own database. Here the repository is a directory on this
machine and the pull request is a row in `board.db`, so a person with `git init` and some commits
gets the whole loop — branch, review, pull request, merge — without pushing anywhere or opening an
account.

WHAT IT WRITES INTO THEIR REPOSITORY, EXHAUSTIVELY, because this is somebody's own working copy and
the list has to be short enough to read:

  · `refs/heads/openfactory/<n>` — the job's branch, force-pushed by the box on every publish;
  · on the worktree box, a linked worktree under `.git/worktrees/<n>` (the box's own doing);
  · the fast-forward THEY asked for, on the base branch, when they press merge.

Nothing else. No remote is added, no hook is installed, no config is edited,
`receive.denyCurrentBranch` is left alone, and no bare mirror is made. The force applies to
`openfactory/<n>` and to nothing else — a commit a person adds to the factory's own branch is
overwritten by the next publish, which is true of every forge here and is why that branch is named
after the platform.

FAST-FORWARD, NEVER SQUASH. The hosted rows squash; locally the history is the job branch's own
commits, authored as the bot, which is how a reader tells the factory's commits from the person's.
A squash would write the person's index; a fast-forward writes only the ref.

A PROPOSAL WHOSE BASE MOVED IS REBASED FIRST, AND ONLY IN THE INSTALLATION'S BARE REPOSITORY
(#142). The context repository's `main` moves on its own — the knowledge pipeline's module-map
refresh lands there while a baseline waits for a person — and a fast-forward alone refused that
baseline for ever. So `merge_pr` rebases it in a scratch tree outside the repository and then
fast-forwards as always: still the proposal's own commits, in a line, with no merge commit. The
person's repository is never rebased by a merge; a job branch that fell behind there goes through
`update_branch`, which the loop asks for.

RAISING WHERE THE HOSTED ROWS TRIGGER. `merge_pr` on GitHub arms auto-merge and returns; the caller
polls `pr_status` for the verdict. Here the merge either happened or it did not, and
`merge_pr_now` reads success as *no exception* — so a refused fast-forward that returned quietly
would settle the workflow as MERGED over a base that never moved. It raises, with git's own
sentence.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from openfactory.adapters.board_db import connect, next_pr, now_iso

log = logging.getLogger("openfactory.forge.local")

#: How long any one git command may take. Every command here is local and reads or moves a ref;
#: a minute means something is wedged, not slow.
_TIMEOUT = 60


class LocalForge:
    """The person's repository, and the pull requests in `board.db`."""

    def __init__(self, project: str, repo_path: str, *, base: str = "main",
                 db_path=None, token: str | None = None, token_provider=None) -> None:
        self.project = (project or "").strip()
        self.repo_path = str(repo_path or "")
        self.base = (base or "main").strip() or "main"
        self._db = db_path
        #: Accepted and ignored, as on the tracker row: every call site hands the forge axis a
        #: credential and a row that refused the argument would fail on a deployment that has one.
        self.token = token

    # ---- git, in one place ----------------------------------------------------------------

    def _git(self, *args: str, cwd: str | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", cwd or self.repo_path, *args],
                              capture_output=True, text=True, timeout=_TIMEOUT, check=False)

    def _out(self, *args: str, cwd: str | None = None) -> str:
        p = self._git(*args, cwd=cwd)
        return (p.stdout or "").strip() if p.returncode == 0 else ""

    @staticmethod
    def _sentence(p: subprocess.CompletedProcess) -> str:
        """Git's own words, whichever stream it used and without the trailing blank lines.

        NOT PARAPHRASED. "Your local changes to the following files would be overwritten by
        merge: src/app.py" names the file; every rewriting of that sentence this platform could
        write is worse, and the person is standing in the repository it is about."""
        text = ((p.stderr or "") + "\n" + (p.stdout or "")).strip()
        return "\n".join(line for line in text.splitlines() if line.strip())[:2000]

    # ---- where the code is ----------------------------------------------------------------

    def push_remote(self) -> str | None:
        """The person's own repository path — NEVER `None` (ADR-0049 D3).

        `None` MEANS "USE THE AMBIENT ORIGIN" at nine call sites in the runner, and this
        repository has no origin: the container box would read `origin`'s URL and raise its own
        sentence, and the worktree box would push to the name `origin` and surface git's. Both are
        a configuration error reported as a push failure, on a deployment that is configured
        correctly."""
        return self.repo_path

    def clone_url(self, repo: str, *, token: str | None = None) -> str:
        """A path a `git clone` accepts. This row's URLs are paths, and that is the whole of it.

        A URL IS RETURNED UNTOUCHED, because a project on this row may still name a repository
        somewhere else — the knowledge bundle's, say — and rewriting somebody's URL into a local
        path is how a clone silently reads the wrong tree."""
        name = (repo or "").strip()
        if not name or name == self.project:
            return self.repo_path
        if "://" in name or name.startswith("git@"):
            return name
        # A short name that is not this project's is a repository the INSTALLATION owns — the
        # context repository the knowledge pipeline pushes into (slice 7). Answered as a path
        # under the operator's own directory so it exists on the same machine as everything else.
        from openfactory import namespace

        return str(namespace.operator_path(f"context/{name}.git"))

    def authenticated_url(self, url: str) -> str:
        """Untouched. There is no credential to add, and adding one belonging to another system is
        the failure this method exists to prevent everywhere else."""
        return url

    # ---- branches --------------------------------------------------------------------------

    def list_branches(self, repo: str = "", *, prefix: str = "") -> list[str] | None:
        """Bare names. `None` when the repository could not be read — `[]` when it has none."""
        where = self.clone_url(repo)
        p = self._git("for-each-ref", "--format=%(refname:short)", "refs/heads/", cwd=where)
        if p.returncode != 0:
            log.warning("could not list %s's branches — %s", where, self._sentence(p))
            return None
        names = [n.strip() for n in (p.stdout or "").splitlines() if n.strip()]
        return [n for n in names if n.startswith(prefix)] if prefix else names

    def delete_branch(self, name: str, *, repo: str = "") -> bool:
        """True when the branch is GONE — the post-condition, not the act, so an already-absent
        branch answers True and a refused delete answers False."""
        where = self.clone_url(repo)
        if not (name or "").strip():
            return False
        p = self._git("branch", "-D", name, cwd=where)
        if p.returncode == 0:
            return True
        gone = "not found" in (p.stderr or "").lower()
        if gone:
            log.info("%s was already gone in %s", name, where)
        else:
            log.warning("could not delete %s in %s — %s", name, where, self._sentence(p))
        return gone

    def latest_tag(self) -> str | None:
        return self._out("describe", "--tags", "--abbrev=0") or None

    def create_tag(self, *, tag: str, ref: str) -> None:
        p = self._git("tag", tag, ref)
        if p.returncode != 0:
            raise RuntimeError(f"could not tag {ref} as {tag}: {self._sentence(p)}")

    # ---- pull requests, which live in board.db ---------------------------------------------

    def _row(self, pr: str) -> dict | None:
        number = _pr_number(pr)
        if not number:
            return None
        with connect(self._db) as conn:
            row = conn.execute(
                "SELECT * FROM pull_requests WHERE project = ? AND number = ?",
                (self.project, number)).fetchone()
        return dict(row) if row else None

    def _where(self, row: dict) -> str:
        """The repository a pull request is IN — the directory every git command about it runs in.

        FROM THE ROW, NEVER FROM THE CALL, and that is the fix for #140. This row is built once per
        project with one `repo_path`, and `_git` falls back to it — so a pull request the product
        role opened in the context repository was diffed and merged in the person's code instead:
        `pr_diff` answered None and the merge said the branch was gone. The callers could not have
        passed the repository even knowing it: the panel holds a pull-request number and nothing
        else, and `mergeable_state`, `update_branch` and `force_merge` take no `repo` on the port.
        So the pull request remembers, and a `repo` argument is not consulted once the row exists —
        a pull request that names its own repository wins over the caller, which is the port's
        rule for the hosted rows too."""
        return self.clone_url(str(row.get("repo") or ""))

    def _repo_key(self, repo: str) -> str:
        """What a pull request records as its repository: `""` for this project's own, the name as
        given for any other.

        DECIDED BY `clone_url`, so the two cannot disagree: `""`, the project's name and anything
        else that resolves to `repo_path` are one repository and one key, and a lookup asked with
        either spelling finds the same pull request."""
        name = (repo or "").strip()
        return "" if self.clone_url(name) == self.repo_path else name

    def pr_url(self, number: int) -> str:
        """The pull request's address — a route on the panel, this deployment's own surface."""
        from openfactory.adapters.tracker.local import panel_url

        return f"{panel_url()}/p/{self.project}/pr/{number}"

    def pr_for_head(self, head: str, *, repo: str = "") -> str | None:
        """The most recent pull request from `head` in `repo`, in ANY state. `""` none was ever
        opened; `None` the file could not be read — a caller writing `if not pr` puts those
        together and files a duplicate on a transient error.

        SCOPED TO THE REPOSITORY, as `gh pr list --repo` is on the hosted row: a head is a name
        inside one repository, and the same `req/…` in two of them is two proposals."""
        key = self._repo_key(repo)
        try:
            with connect(self._db) as conn:
                row = conn.execute(
                    "SELECT number FROM pull_requests WHERE project = ? AND repo = ? AND head = ? "
                    "ORDER BY number DESC LIMIT 1",
                    (self.project, key, (head or "").strip())).fetchone()
        except Exception:  # noqa: BLE001 — could not read is not "there is none"
            log.warning("could not read %s's pull requests", self.project, exc_info=True)
            return None
        return self.pr_url(row["number"]) if row else ""

    # ---- creating a repository (RepositoryCreatingForge) --------------------------------------

    def create_repository(self, *, name: str, private: bool = True,
                          description: str = "") -> tuple[str, bool]:
        """The context repository, as a BARE repository this installation owns. `(name, created)`.

        WHY BARE, and it is not a preference: the knowledge pipeline pushes into a clone's `origin`
        and the requirement authoring pushes straight at `clone_url`, and git refuses a push into a
        branch that is checked out somewhere. A non-bare repository here would work until the first
        push and then fail in a message about `receive.denyCurrentBranch`, halfway through the
        product role's first requirement.

        WHOSE IT IS: the INSTALLATION'S, under the operator's own directory — not the person's
        project repository, which is theirs and holds their code. `clone_url` already answers this
        path for a short name that is not the project's; this is what makes that path exist.

        `private` AND `description` ARE ACCEPTED AND UNUSED, deliberately. A directory on somebody's
        own machine has no visibility to set and nowhere to put a description, and a signature that
        refused them would make this row the odd one out at a seam whose whole point is that the
        caller does not know which forge it holds.

        IDEMPOTENT, like every other row's: an existing repository is the expected case — a retry,
        a second project, an earlier onboarding — and `created` is what a client-facing sentence
        needs to tell "we made you one" from "we found the one you had"."""
        from pathlib import Path

        where = Path(self.clone_url(name))
        if (where / "HEAD").exists():
            return name, False
        where.parent.mkdir(parents=True, exist_ok=True)
        made = subprocess.run(["git", "init", "--bare", "-b", "main", str(where)],
                              capture_output=True, text=True, timeout=_TIMEOUT, check=False)
        if made.returncode != 0 or not (where / "HEAD").exists():
            # RAISES WHEN IT CANNOT TELL (the protocol's rule): a refusal read as success would
            # have the onboarding report a repository nobody can push to, and the first sign would
            # be the product role failing to write a requirement an hour later.
            raise RuntimeError(f"could not create the context repository at {where}: "
                               f"{self._sentence(made) or 'git said nothing'}")
        return name, True

    def open_pr(self, *, head: str, base: str, title: str, body: str, repo: str = "") -> str:
        """Open one, or answer the OPEN one this head already has. Raises when it cannot.

        THE REUSE LIVES INSIDE `open_pr`, as it does on the hosted rows, because a retried
        activity must not double-file (D-16) — and the check is narrower than `pr_for_head`'s: an
        abandoned pull request is not a reason to refuse to open a fresh one.

        IN `repo`, WITH ITS SHAS TAKEN THERE. The row records the repository it was opened
        against, and `base_sha` and `patch_id` are read in that repository at the moment of
        opening: read in the project's, a context-repository pull request was written with both
        EMPTY — wrong at creation, before anybody asked it anything (#140)."""
        branch = (head or "").strip()
        onto = (base or "").strip() or self.base
        if not branch:
            raise ValueError("a pull request needs a head branch")
        key = self._repo_key(repo)
        where = self.clone_url(key)
        when = now_iso()
        with connect(self._db, write=True) as conn:
            live = conn.execute(
                "SELECT number FROM pull_requests WHERE project = ? AND repo = ? AND head = ? "
                "AND state = 'open' ORDER BY number DESC LIMIT 1",
                (self.project, key, branch)).fetchone()
            if live:
                return self.pr_url(live["number"])
            number = next_pr(conn, self.project)
            conn.execute(
                "INSERT INTO pull_requests(project, number, repo, head, base, title, body, state, "
                "base_sha, patch_id, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,'open',?,?,?,?)",
                (self.project, number, key, branch, onto, (title or "").strip(), body or "",
                 self._sha(onto, where), self._patch_id(onto, branch, where), when, when))
        return self.pr_url(number)

    def pr_body(self, *, pr: str, repo: str = "") -> str | None:
        row = self._row(pr)
        return None if row is None else (row["body"] or "")

    def set_pr_body(self, *, pr: str, body: str, repo: str = "") -> bool:
        number = _pr_number(pr)
        if not number:
            return False
        with connect(self._db, write=True) as conn:
            changed = conn.execute(
                "UPDATE pull_requests SET body = ?, updated_at = ? "
                "WHERE project = ? AND number = ?",
                (body or "", now_iso(), self.project, number)).rowcount
        return bool(changed)

    def review_pr(self, *, pr: str, event, body: str) -> None:
        """Append the verdict. The events are the pull request's own record, and the page reads
        them in order — a review is a thing that HAPPENED, so nothing here overwrites."""
        number = _pr_number(pr)
        if not number:
            return
        verdict = getattr(event, "value", None) or str(event)
        with connect(self._db, write=True) as conn:
            row = conn.execute("SELECT events FROM pull_requests WHERE project = ? AND number = ?",
                               (self.project, number)).fetchone()
            if row is None:
                return
            events = _load(row["events"])
            events.append({"event": verdict, "body": body or "", "at": now_iso()})
            conn.execute(
                "UPDATE pull_requests SET events = ?, updated_at = ? "
                "WHERE project = ? AND number = ?",
                (json.dumps(events), now_iso(), self.project, number))

    def pr_events(self, *, pr: str) -> list[dict]:
        """The reviews recorded on this pull request, oldest first.

        NOT ON THE PORT, AND ASKED THROUGH `getattr` (ADR-0049 D4/D6). Every hosted vendor keeps
        its review timeline behind its own API and its own shapes; this row keeps them because it
        wrote them, so the page can render what it has and no other row is made to claim it. A
        page that demanded this of the port would be a page only one row could serve."""
        row = self._row(pr)
        return _load(row["events"]) if row else []

    def pr_refusal(self, *, pr: str) -> str:
        """The sentence the last refused merge left on this pull request, or `""`.

        THE WORDS ARE GIT'S. The page prints them because this platform's paraphrase of "your
        local changes to the following files would be overwritten by merge: app.py" loses the file
        name, and the file name is the whole of what the person can act on."""
        row = self._row(pr)
        return str(row["refused"] or "") if row else ""

    def request_reviewers(self, *, pr: str, reviewers: list[str]) -> None:
        """Recorded, and a no-op otherwise. AN EMPTY LIST IS ACCEPTED because the runner passes
        `manifest.reviewers` unconditionally, and a row that refused one would fail every job on a
        manifest that names none."""
        number = _pr_number(pr)
        if not number:
            return
        with connect(self._db, write=True) as conn:
            conn.execute(
                "UPDATE pull_requests SET reviewers = ?, updated_at = ? "
                "WHERE project = ? AND number = ?",
                (json.dumps([r for r in (reviewers or []) if r]), now_iso(),
                 self.project, number))

    def close_pr(self, *, pr: str, reason: str = "") -> None:
        """Closed, not deleted: the branch and its commits stay exactly where they are, so the
        next `open_pr` for the same head opens a NEW number rather than reviving this one."""
        number = _pr_number(pr)
        if not number:
            return
        with connect(self._db, write=True) as conn:
            conn.execute(
                "UPDATE pull_requests SET state = 'closed', refused = ?, updated_at = ? "
                "WHERE project = ? AND number = ? AND state = 'open'",
                (reason or "", now_iso(), self.project, number))

    def pr_merged(self, *, pr: str) -> bool:
        row = self._row(pr)
        return bool(row and row["state"] == "merged")

    def pr_status(self, *, pr: str, repo: str = "") -> str:
        """`merged` | `closed` | `open`. RAISES when it cannot be read, as the port requires: an
        `open` would send the sweep on to merge something already merged, and a `merged` would
        drop a live pull request out of its attention for ever."""
        row = self._row(pr)
        if row is None:
            raise KeyError(f"no pull request {pr!r} on {self.project!r}")
        return str(row["state"])

    def merge_commit_sha(self, *, pr: str) -> str | None:
        row = self._row(pr)
        return (row["merge_sha"] or None) if row else None

    def pr_diff(self, *, pr: str, repo: str = "", max_chars: int = 60000) -> str | None:
        """`git diff base...head`, capped. `None` when there is no merge base to diff from —
        *could not look*, which is a different fact from a pull request that changes nothing."""
        row = self._row(pr)
        if row is None:
            return None
        where = self._where(row)
        merge_base = self._out("merge-base", row["base"], row["head"], cwd=where)
        if not merge_base:
            return None
        p = self._git("diff", f"{row['base']}...{row['head']}", cwd=where)
        if p.returncode != 0:
            return None
        text = p.stdout or ""
        if len(text) <= max_chars:
            return text
        # TRUNCATED, AND IT SAYS SO. A diff that stops mid-hunk with no marker reads as a change
        # that ends there — which is a claim about somebody's pull request that nobody made.
        return text[:max_chars] + f"\n… truncated at {max_chars} characters …\n"

    # ---- there is no CI here, and every answer says so --------------------------------------

    def pr_ci_status(self, *, pr: str) -> str:
        """`"none"` — the port's own word for *no checks*. The loop then never waits on CI and
        never triggers a CI repair, which is the correct behaviour rather than a degraded one."""
        return "none"

    def pr_checks(self, *, pr: str) -> list[dict]:
        return []

    def failed_ci_logs(self, *, pr: str) -> str:
        return ""

    def latest_run(self, *, workflow: str) -> dict | None:
        return None

    def deploy_run_status(self, *, sha: str, workflow: str) -> tuple[str, str | None]:
        return "none", None

    def disabled_ci_paths(self, repo: str = "") -> list[str] | None:
        """`[]` — asked, and none are disabled. `None` would say this row cannot tell, and it
        can: there is no CI here to switch off."""
        return []

    def dispatch_workflow(self, *, workflow: str, ref: str) -> None:
        """RAISES, naming what is missing. A card carrying `e2e_label` on a manifest that names an
        `e2e_workflow` parks with this sentence rather than reporting a run that never happened."""
        raise RuntimeError(
            f"this project's forge is the repository on this machine and has no CI to dispatch, "
            f"so {workflow!r} cannot be run. Remove `e2e_workflow:` from the manifest, or point "
            f"the project at a forge that runs one.")

    def disable_auto_merge(self, *, pr: str) -> None:
        """A no-op: nothing was armed. There is no asynchronous completion here — a merge either
        happened or it raised."""

    # ---- merging, which is a fast-forward and nothing else ----------------------------------

    def mergeable_state(self, *, pr: str) -> str:
        """`clean` | `behind` | `dirty` | `unknown` — and NEVER a raise.

        The activity that calls this has no `try` around it, and GitHub answers `unknown` on an
        error rather than failing, so a row that raised here would take down a watch that every
        other row survives."""
        try:
            row = self._row(pr)
            if row is None or row["state"] != "open":
                return "unknown"
            base, head, where = row["base"], row["head"], self._where(row)
            if not self._sha(head, where):
                return self._refuse(pr, f"the branch {head} is gone from this repository")
            # THE ORDER IS THE ANSWER, and two of these were in the wrong place until a test
            # reached them. A repository with a merge in progress cannot be rebased either, so
            # `dirty` has to be decided BEFORE `behind` — otherwise the loop would spend its
            # bounded update attempts on a tree that refuses all of them.
            if blocked := self._blocked(base, where):
                return self._refuse(pr, blocked)
            if self._git("merge-base", "--is-ancestor", base, head, cwd=where).returncode != 0:
                # The base moved under the pull request. A rebase would apply, which is what
                # `update_branch` is for — this is not a refusal.
                return "behind"
            overlap = self._overlap(base, head, where)
            return self._refuse(pr, overlap) if overlap else "clean"
        except Exception:  # noqa: BLE001 — see the docstring
            log.warning("could not judge %s's mergeability", pr, exc_info=True)
            return "unknown"

    def _blocked(self, base: str, where: str) -> str:
        """Why the repository at `where` cannot be written at all right now, or `""`.

        ASKED WITH READS rather than by trying it: this runs on a poll, every two minutes for an
        hour, and a poll that attempted a merge would be a poll that changes the person's tree.

        `where` IS THE PULL REQUEST'S REPOSITORY, never assumed to be the project's: a merge in
        progress in the person's checkout says nothing about a proposal in the context repository,
        and refusing one for the other is the same defect as reading its diff in the wrong place."""
        owner = self._worktree_of(base, where)
        if owner and not _same(owner, where):
            # SOMEBODY ELSE HAS THE BASE OUT. Git refuses to move a branch checked out in another
            # worktree, and this row would refuse anyway: writing a tree nobody asked about is the
            # one thing it promises not to do.
            return (f"the base branch {base} is checked out in {owner} — this row will not write "
                    f"a working tree it was not asked about. Close that worktree, or merge from "
                    f"inside it")
        state = self._out("rev-parse", "--git-dir", cwd=where)
        # THE PLATFORM'S WORDS WHERE IT EXPLAINS, git's where git speaks. "this repository has a
        # MERGE_HEAD in progress" is the file's name read out loud at somebody standing in their
        # own repository; `MERGE_HEAD` is not a thing they did.
        for marker, said in (("MERGE_HEAD", "merge"), ("CHERRY_PICK_HEAD", "cherry-pick"),
                             ("REVERT_HEAD", "revert"), ("rebase-merge", "rebase"),
                             ("rebase-apply", "rebase")):
            if state and (Path(where) / state / marker).exists():
                return (f"this repository has a {said} in progress — finish or abort it "
                        f"(`git {said} --abort`), then answer again")
        return ""

    def _overlap(self, base: str, head: str, where: str) -> str:
        """Git's sentence when the fast-forward would overwrite an edit, else `""`.

        ONLY WHERE THE BASE IS THIS TREE'S OWN HEAD. A base nobody has out is moved as a ref and
        writes no file, so no edit can be in its way; a base somebody else has out was refused one
        step earlier."""
        if not _same(self._worktree_of(base, where), where):
            return ""
        touched = set(self._out("diff", "--name-only", f"{base}..{head}", cwd=where).splitlines())
        overlap = sorted(touched & self._dirty_paths(where))
        if not overlap:
            return ""
        return ("your local changes to the following files would be overwritten by merge:\n  "
                + "\n  ".join(overlap[:20]))

    def _dirty_paths(self, where: str) -> set[str]:
        """Every path `git status --porcelain` reports, staged, unstaged or untracked.

        THE RAW STDOUT, NEVER `_out`, AND THAT IS THE WHOLE COMMENT. Porcelain v1 puts TWO
        significant status columns before the path — ` M app.py` for an unstaged edit — and `_out`
        strips the string, which eats the leading space and shifts every name by one character.
        Measured by driving it: `mergeable_state` answered `clean` for an overlapping edit that
        `merge_pr` then refused, which is the worst pair of answers this row could give — a page
        offering a merge button that cannot work.

        A rename reports `R  old -> new`, and BOTH sides are dirty: the merge would write over the
        destination and git will not lose the source either."""
        p = self._git("status", "--porcelain", "--untracked-files=all", cwd=where)
        if p.returncode != 0:
            return set()
        out: set[str] = set()
        for line in (p.stdout or "").splitlines():
            if len(line) <= 3:
                continue
            for part in line[3:].split(" -> "):
                if name := part.strip().strip('"'):
                    out.add(name)
        return out

    def _worktree_of(self, branch: str, where: str) -> str:
        """The path of the working tree of the repository at `where` that has `branch` checked
        out, or `""` when nobody has.

        THE PATH, NOT A BOOLEAN, and a test is what taught the difference. "Checked out" is two
        different situations: this repository's own HEAD, which the merge writes, and a LINKED
        worktree, which it must not — and a boolean answered both with one word. `merge_pr` then
        ran `git merge --ff-only` in a repository whose HEAD was the job branch, merging the head
        into itself instead of the base.

        Decided over `git worktree list --porcelain`, never `HEAD` alone: a linked worktree holds
        a branch this repository's HEAD never mentions, and git refuses to move it just the
        same.

        A BARE REPOSITORY ANSWERS `""`, AND THAT IS INTENDED RATHER THAN AN ACCIDENT OF WHERE THE
        PATH COMES FROM. The context repository is bare (`create_repository` says why), and
        `git worktree list --porcelain` there prints one `worktree` line, then `bare`, and no
        `branch` line at all (measured, git 2.43) — nobody has anything out. So `_blocked` and
        `_overlap`, which exist to protect a person's working tree, are clean on it by
        construction, and `merge_pr` moves its base as a ref with `fetch . head:base`. That is the
        right answer: there is no tree there to protect, and the repository is the
        installation's, not a person's."""
        p = self._git("worktree", "list", "--porcelain", cwd=where)
        if p.returncode != 0:
            return (where
                    if self._out("symbolic-ref", "--short", "HEAD", cwd=where) == branch else "")
        where = ""
        for line in (p.stdout or "").splitlines():
            if line.startswith("worktree "):
                where = line.split(" ", 1)[1].strip()
            elif line.strip() == f"branch refs/heads/{branch}":
                return where
        return ""

    def _checked_out(self, branch: str, where: str) -> bool:
        """Whether anybody has `branch` out. `_worktree_of` says WHO, which is what the callers
        that write need; this is for the ones that only need to know."""
        return bool(self._worktree_of(branch, where))

    def _refuse(self, pr: str, sentence: str) -> str:
        """Record git's words on the pull request and answer `dirty`. THE SENTENCE TRAVELS: the
        page and the hold print what git said, and a paraphrase would lose the file name."""
        number = _pr_number(pr)
        if number:
            with connect(self._db, write=True) as conn:
                conn.execute("UPDATE pull_requests SET refused = ?, updated_at = ? "
                             "WHERE project = ? AND number = ?",
                             (sentence, now_iso(), self.project, number))
        return "dirty"

    def update_branch(self, *, pr: str) -> bool:
        """Rebase the head onto the base — the three commands the box's own rebase runs.

        IN THE PERSON'S REPOSITORY BUT NEVER IN THEIR TREE: `rebase --onto` on a branch that is
        not checked out moves the ref and touches no working file. A branch they have checked out
        is refused, because rebasing it under them is exactly the act this row promises not to
        make.

        ON A BARE REPOSITORY, IN A SCRATCH TREE (#142). `rebase --onto` needs a working tree and
        the context repository has none — git says `this operation must be run in a work tree`
        (measured, git 2.43) — so this answered False there and a proposal whose base moved stayed
        `behind`. It rebases the way `merge_pr` does now; a conflict is still False, with nothing
        moved."""
        row = self._row(pr)
        if row is None:
            return False
        base, head, where = row["base"], row["head"], self._where(row)
        if self._checked_out(head, where):
            log.warning("%s is checked out — it will not be rebased under whoever has it", head)
            return False
        merge_base = self._out("merge-base", base, head, cwd=where)
        if not merge_base:
            return False
        if self._bare(where):
            if refused := self._rebase_in_a_scratch_tree(base, head, where):
                log.warning("could not rebase %s onto %s — %s", head, base, refused)
                return False
        else:
            p = self._git("rebase", "--onto", base, merge_base, head, cwd=where)
            if p.returncode != 0:
                self._git("rebase", "--abort", cwd=where)
                log.warning("could not rebase %s onto %s — %s", head, base, self._sentence(p))
                return False
        with connect(self._db, write=True) as conn:
            conn.execute("UPDATE pull_requests SET patch_id = ?, base_sha = ?, updated_at = ? "
                         "WHERE project = ? AND number = ?",
                         (self._patch_id(base, head, where), self._sha(base, where), now_iso(),
                          self.project, _pr_number(pr)))
        return True

    def merge_pr(self, *, pr: str, repo: str = "") -> None:
        """Fast-forward the base onto the head. RAISES with git's sentence when refused.

        STRICTER THAN THE HOSTED *TRIGGER*, and deliberately so: `merge_pr_now` reads success as
        *no exception* and the workflow settles MERGED on it. A refused fast-forward that returned
        quietly would mark work delivered over a base that never moved.

        IN THE REPOSITORY THE PULL REQUEST IS AGAINST — the row's, see `_where`. `repo` is
        accepted for the port and not consulted: a merge that followed the caller's word over the
        row's would be one more way to move the wrong repository's base."""
        row = self._row(pr)
        if row is None:
            raise KeyError(f"no pull request {pr!r} on {self.project!r}")
        if row["state"] == "merged":
            return  # idempotent: a retried activity must not fail on work already done
        base, head, where = row["base"], row["head"], self._where(row)

        # A PROPOSAL THE BASE MOVED UNDER, IN A BARE REPOSITORY, IS REBASED BEFORE ANYTHING IS READ
        # (#142): the fast-forward below is the only merge this row makes, and it refuses a head
        # the base is not an ancestor of. A head that is gone is left to the sentence saying so.
        if (self._bare(where) and self._sha(head, where)
                and self._git("merge-base", "--is-ancestor", base, head, cwd=where).returncode):
            if refused := self._rebase_in_a_scratch_tree(base, head, where):
                self._refuse(pr, refused)
                raise RuntimeError(refused)

        # The patch id is taken BEFORE the ref moves. Afterwards the three-dot diff is empty by
        # construction, so a reading taken later would record that this pull request changed
        # nothing.
        patch = self._patch_id(base, head, where)
        head_sha = self._sha(head, where)
        if not head_sha:
            raise RuntimeError(f"the branch {head} is gone from this repository — nothing to merge")

        if blocked := self._blocked(base, where):
            self._refuse(pr, blocked)
            raise RuntimeError(blocked)
        if _same(self._worktree_of(base, where), where):
            # The base is THIS tree's own HEAD: the fast-forward writes their working files, and
            # it is the one act they asked for.
            p = self._git("merge", "--ff-only", head, cwd=where)
        else:
            # Nobody has it out: move the ref without touching any tree. `fetch . <head>:<base>`
            # is the one command that fast-forwards a branch that is not checked out.
            p = self._git("fetch", ".", f"{head}:{base}", cwd=where)
        if p.returncode != 0:
            sentence = self._sentence(p)
            self._refuse(pr, sentence)
            raise RuntimeError(sentence)

        with connect(self._db, write=True) as conn:
            conn.execute(
                "UPDATE pull_requests SET state = 'merged', merge_sha = ?, patch_id = ?, "
                "refused = '', updated_at = ? WHERE project = ? AND number = ?",
                (head_sha, patch, now_iso(), self.project, _pr_number(pr)))

    def force_merge(self, *, pr: str) -> None:
        """The same act. There is no branch protection here to override, so a `force_merge` that
        did something MORE than `merge_pr` would be a second way to write somebody's repository
        that nothing asked for."""
        self.merge_pr(pr=pr)

    # ---- internals -------------------------------------------------------------------------

    # `where` IS A REQUIRED ARGUMENT ON EVERY HELPER BELOW THE PORT, and that is the guard rather
    # than a style. #140 was `cwd or self.repo_path`: a helper that could be called without saying
    # which repository quietly read the project's, and every existing test happened to open its
    # pull request there. A helper that cannot be called without a path cannot make that mistake.

    def _sha(self, ref: str, where: str) -> str:
        return self._out("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", cwd=where)

    def _patch_id(self, base: str, head: str, where: str) -> str:
        """`git patch-id --stable` over `merge-base(base, head)..head` — the identity of the
        CHANGE, which survives a rebase where a sha does not."""
        if not self._out("merge-base", base, head, cwd=where):
            return ""
        diff = self._git("diff", f"{base}...{head}", cwd=where)
        if diff.returncode != 0 or not (diff.stdout or "").strip():
            return ""
        got = subprocess.run(["git", "patch-id", "--stable"], input=diff.stdout,
                             capture_output=True, text=True, timeout=_TIMEOUT, check=False)
        return (got.stdout or "").split(" ")[0].strip()

    def _bare(self, where: str) -> bool:
        return self._out("rev-parse", "--is-bare-repository", cwd=where) == "true"

    def _rebase_in_a_scratch_tree(self, base: str, head: str, where: str) -> str:
        """Rebase `head` onto `base` in the bare repository at `where`, and move `head` there. `""`
        when it did; otherwise the sentence saying why, with nothing moved (#142).

        A SCRATCH TREE, BECAUSE A BARE REPOSITORY HAS NONE: a linked worktree of `where` in a
        temporary directory, gone before this returns whichever way it went. `rmtree` takes the
        files and `worktree prune` takes the registration, and the rebase's own state goes with it
        — measured on git 2.43 over a real conflict: nothing left under `worktrees/`, no ref moved.
        So there is no `rebase --abort` to run first.

        DETACHED, AND THE BRANCH MOVES BY COMPARE-AND-SWAP. The tree holds the head's COMMIT, not
        its branch, and `update-ref <branch> <rebased> <started>` moves the branch only if it is
        still where the rebase started. A proposal pushed again meanwhile is the newer text, and a
        rebase of the older one must not land over it.

        AS THE BOT. A rebase writes new commits, and a bare repository has no identity to write them
        with — measured with no git config at all: `Please tell me who you are`, exit 128. Each
        commit keeps its author; the committer is the bot, as on every commit the product role
        makes."""
        from openfactory.credentials import bot_identity

        started = self._sha(head, where)
        scratch = tempfile.mkdtemp(prefix="openfactory-rebase-")
        tree = str(Path(scratch) / "tree")
        try:
            added = self._git("worktree", "add", "--detach", tree, started, cwd=where)
            if added.returncode != 0:
                return (f"no scratch tree could be made to rebase {head} in, so nothing was "
                        f"moved — {self._sentence(added)}")
            bot = bot_identity()
            p = self._git("-c", f"user.name={bot.name}", "-c", f"user.email={bot.email}",
                          "rebase", base, cwd=tree)
            if p.returncode != 0:
                conflicted = self._out("diff", "--name-only", "--diff-filter=U", cwd=tree)
                if not conflicted:
                    return (f"{head} could not be rebased onto {base}, and nothing was moved — "
                            f"{self._sentence(p)}")
                files = "\n  ".join(conflicted.splitlines()[:20])
                return (f"{head} conflicts with {base}, so nothing was moved. Both changed:\n"
                        f"  {files}\nRebase {head} onto {base} in a clone of {where}, resolve it "
                        f"there and push the branch, then merge again.")
            moved = self._git("update-ref", f"refs/heads/{head}", self._sha("HEAD", tree), started,
                              cwd=where)
            if moved.returncode != 0:
                return (f"{head} was pushed again while it was being rebased onto {base}, so the "
                        f"newer push was kept and nothing was merged — {self._sentence(moved)}")
            return ""
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
            self._git("worktree", "prune", cwd=where)


def _same(a: str, b: str) -> bool:
    """Whether two paths name the same directory. Resolved, because `git worktree list` answers
    with the real path and a caller may hold a symlinked or relative one."""
    if not a or not b:
        return False
    try:
        return Path(a).resolve() == Path(b).resolve()
    except OSError:
        return str(a) == str(b)


def _load(raw: str) -> list:
    try:
        got = json.loads(raw or "[]")
        return got if isinstance(got, list) else []
    except (TypeError, ValueError):
        return []


def _pr_number(pr: object) -> int:
    """The pull request's number, from its panel route or from a bare number.

    `0` FOR ANYTHING ELSE, which matches no row — so a malformed reference reads as *no such pull
    request* rather than raising inside a poll tick."""
    text = str(pr or "").strip().rstrip("/")
    tail = text.rsplit("/", 1)[-1].lstrip("#")
    return int(tail) if tail.isdigit() else 0
