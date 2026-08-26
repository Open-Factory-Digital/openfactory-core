"""WorktreeSandbox — lightweight local/test sandbox via `git worktree`.

Isolates the code state only (no CPU/mem/network/secret isolation). Use it for fast
orchestrator tests and local debugging without Docker; real jobs run in
ContainerSandbox. Same Protocol, so the orchestrator is identical against both.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from openfactory.adapters.sandbox.base import (
    OutputBuffer,
    SandboxAdapter,
    Workspace,
    run_and_stream,
)

log = logging.getLogger("openfactory.sandbox.worktree")

#: What git says when the remote ANSWERED and holds no such branch — the one failure that
#: legitimately degrades a resume to a fresh start. Every other failure (no credential, no
#: network, no such host) means we could not ask, and "could not ask" is never "it is not there".
_NO_SUCH_REF = ("couldn't find remote ref", "could not find remote ref")


def _remote_has_no_such_branch(fetch_output: str) -> bool:
    return any(marker in (fetch_output or "").lower() for marker in _NO_SUCH_REF)

# A job clones/pushes over git and talks to GitHub — it never needs AWS. But a Fargate
# task inherits the ECS task-role credentials (chiefly via
# AWS_CONTAINER_CREDENTIALS_RELATIVE_URI), and those leak into the agent and into the
# app/tests it runs: an app that reaches a cloud service at boot picks up the ambient
# role and fails with a permission error instead of booting offline — which once pushed
# an agent into an out-of-scope "fix" that weakened a prod safety contract and evaded the
# coverage gate. Strip them so the workload sees a clean, credential-less environment.
# (engineering.md #4 — creds mint-at-use, never ambient; #11 — stay in scope.)
_AWS_CRED_VARS = (
    "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
    "AWS_CONTAINER_CREDENTIALS_FULL_URI",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_SECURITY_TOKEN",
    "AWS_WEB_IDENTITY_TOKEN_FILE",
    "AWS_ROLE_ARN",
    "AWS_PROFILE",
)

# The forge (GitHub) push credentials live in the task env so the FRAMEWORK can push the
# branch + open the PR — but the agent must never wield them. If the agent can read a bot
# token it can `git push`/`gh pr create` and bypass the pipeline's control of version
# control (which #232 did). The framework pushes via an explicit authenticated remote
# (forge.push_remote(), resolved from the host env), so stripping these from the *workload*
# env costs it nothing. (engineering.md #4 — creds mint-at-use, never ambient.)
# A DENIAL LIST NAMES EVERY SPELLING THE SECRET CAN SIT UNDER, AND "ONE NAME PER SECRET" IS A
# DIFFERENT CLAIM THAT MISLED THIS LIST. No adoption shim serves a second spelling of a name any
# more (the retired prefix left on 2026-08-25) — but `credentials.py` still serves ONE bot
# credential under THREE names, by fallback rather than by alias: `forge_token()` reads
# OPENFACTORY_FORGE_TOKEN then OPENFACTORY_BOT_TOKEN, `tracker_token()` reads
# OPENFACTORY_TRACKER_TOKEN then the same OPENFACTORY_BOT_TOKEN. This list carried two of the
# three, so a deployment that filled the tracker override handed the agent that credential under
# the one name no scrub removed — and on a personal GitHub account that override is the classic
# PAT `docs/setup/github.md` scopes `repo` + `project`, which pushes (measured 2026-08-26).
# The rule is the FALLBACK CHAIN, not the prefix: a name any reader serves for a listed secret is
# listed with it. Held by `tests/test_the_environment_carries_the_products_name.py`, which derives
# the chains from `credentials.py` rather than repeating them here.
_FORGE_CRED_VARS = (
    "OPENFACTORY_FORGE_TOKEN",
    "OPENFACTORY_BOT_TOKEN",
    "OPENFACTORY_TRACKER_TOKEN",
    "GH_TOKEN",
    "GITHUB_TOKEN",
    "OPENFACTORY_GH_APP_KEY",
    "OPENFACTORY_GH_APP_KEY_CONTENT",
    "OPENFACTORY_GH_APP_ID",
    "OPENFACTORY_GH_APP_INSTALLATION_ID",
)

# The Claude token POOL — every failover token — is read by the agent ADAPTER in the
# framework's OWN process (claude_code.py picks the active one and delivers it to the CLI
# separately via CLAUDE_CODE_OAUTH_TOKEN/ANTHROPIC_API_KEY). The workload subprocess must
# never see the whole pool: a compromised agent, or the project's own app/tests booting
# inside the sandbox, could read `OPENFACTORY_AGENT_TOKENS` and exfiltrate EVERY token at once.
# Stripping it costs the CLI nothing (its active token still arrives via the auth var).
# (engineering.md #4 — creds mint-at-use, never ambient; the pool is the crown jewels.)
_AGENT_CRED_VARS = ("OPENFACTORY_AGENT_TOKENS",)


def _scrubbed_env(keep: tuple[str, ...] = ()) -> dict[str, str]:
    """The process env minus ambient AWS credentials, forge push tokens, and the Claude
    token pool — so the sandboxed workload cannot reach cloud services with the task's
    identity (boots offline as designed), nor push/PR with the bot's GitHub credentials
    (version control is the pipeline's job, not the agent's), nor read the whole failover
    token pool (only the framework picks the active token, delivered to the CLI directly).

    `keep` IS THE PROJECT'S `box.env`, AND IT EXISTS BECAUSE THE SCRUB HAD A SECOND EFFECT NOBODY
    HAD LOOKED AT. When the harness authenticates through the client's own cloud — Bedrock — the
    variables it needs to reach the MODEL are the same ones stripped here to keep the agent away
    from our INFRASTRUCTURE. The container box already solved this: `box.env` names what passes
    through. The worktree had no such seam, and every judging role runs in a worktree — the sizer,
    the tech-lead's chat and diagnosis, the whole product module. So on a Bedrock deployment the
    executor and reviewer would work (they run in the box) while the tech-lead answered "could not
    answer" to every question and the size gate silently degraded. Nothing would have said why.

    The security property is UNCHANGED for anyone who declares nothing, and it is narrower than it
    looks even for those who do: what the operator names should be a credential scoped to invoking
    a model and nothing else, never the deployment's own task role. Naming it is an explicit,
    per-project decision made by whoever runs the factory — the same contract `box.env` already
    documents — rather than the blanket ambient identity this function exists to remove.
    """
    env = dict(os.environ)
    kept = {v for v in keep if v}
    for var in _AWS_CRED_VARS + _FORGE_CRED_VARS + _AGENT_CRED_VARS:
        if var not in kept:
            env.pop(var, None)
    return env


def _redact(text: str) -> str:
    """Strip any embedded credential from an authenticated URL before logging."""
    return re.sub(r"(https://)[^@/\s]+@", r"\1***@", text)


def _run(cmd: list[str], *, cwd: Path | None = None, timeout: int = 120) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


class WorktreeSandbox(SandboxAdapter):
    def __init__(self, *, root: Path, extra_env: tuple[str, ...] = ()) -> None:
        self.root = root  # where worktrees are created
        #: `box.env` — the NAMES the project declares its harness needs (see `_scrubbed_env`).
        #: Validated like the container's, because the two must not disagree about what a "name"
        #: is: a project that works in the box and is rejected here would be the worse failure.
        bad = [v for v in extra_env if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", v or "")]
        if bad:
            raise ValueError(
                f"box.env entries must be environment variable NAMES, got {bad!r}")
        self.extra_env = tuple(extra_env)
        self._repo_root: Path | None = None
        #: What the command currently running has written — the buffer `tail()` reads (C-39).
        self._output = OutputBuffer()

    def prepare(
        self, *, repo_path: Path, base_branch: str, branch: str, checkout_existing: bool = False,
        remote_url: str | None = None,
    ) -> Workspace:
        self._repo_root = repo_path
        self.root.mkdir(parents=True, exist_ok=True)
        wt = self.root / branch.replace("/", "-")
        if wt.exists():
            _run(["git", "-C", str(repo_path), "worktree", "remove", "--force", str(wt)])
        # Re-running the same ticket must start clean. `worktree remove` frees the dir but
        # the branch outlives it, so a bare `worktree add -b` collides ("branch already
        # exists"). Prune stale worktree refs and drop the branch first (both no-ops when
        # absent — e.g. a fresh cloud clone). Matches the codebase's idempotent-retry
        # posture (publish_branch --force, workflow-id no-op).
        _run(["git", "-C", str(repo_path), "worktree", "prune"])
        _run(["git", "-C", str(repo_path), "branch", "-D", branch])
        # A CI-repair / C2 resume works on the ALREADY-PUSHED branch (ADR-0004/0012), so start
        # the worktree from the remote branch's tip; a normal job starts fresh off base. If the
        # remote branch is GONE (deleted by a human, cleanup automation, or a preserve that
        # never landed) we FALL BACK to base instead of raising — a lost branch must degrade a
        # resume to a fresh start, never brick it into a crash-park (audit HIGH).
        #
        # BUT ONLY WHEN THE REMOTE ACTUALLY ANSWERED. A fetch that FAILED is not evidence of
        # absence, and this fallback used to accept both: on a private repository the tokenless
        # cache origin fails for want of a password, the branch reads as "gone", the resume
        # starts from base — and `publish_branch` then force-pushes that over the open PR,
        # DESTROYING the work it was sent to repair. Anything not positively identified as
        # "the remote has no such ref" raises, naming the real git error (credential scrubbed).
        # Same asymmetry the impediment classifier uses: unknown never degrades toward acting.
        start = base_branch
        if checkout_existing:
            source = remote_url or "origin"
            rc, out = _run(["git", "-C", str(repo_path), "fetch", source,
                            f"+{branch}:refs/remotes/origin/{branch}"], timeout=180)
            if rc == 0:
                start = f"origin/{branch}"
            elif _remote_has_no_such_branch(out):
                log.warning("OPENFACTORY_BRANCH_GONE %s is not on the remote — this resume starts "
                            "fresh "
                            "from %s instead of continuing preserved work", branch, base_branch)
            else:
                raise RuntimeError(
                    f"could not ask the remote for {branch!r}, so this workspace cannot start "
                    f"from the open PR's branch: {_redact(out).strip()[:300]}")
        rc, out = _run(
            ["git", "-C", str(repo_path), "worktree", "add", "-b", branch, str(wt), start]
        )
        if rc != 0:
            raise RuntimeError(f"worktree add failed: {out}")
        # host_path == path here: the worktree IS on the orchestrator's filesystem.
        return Workspace(path=wt, host_path=wt, branch=branch, base_branch=base_branch)

    def harness_path(self, name: str) -> str:
        """The bare name: this runs on the host, where the operator installed the harness and
        `PATH` is theirs to own. An absolute path here would break every local run."""
        return name

    def run(self, *, workspace: Workspace, command: str, timeout: int,
            on_output: Callable[[str], None] | None = None) -> tuple[int, str]:
        """`capture_output=True` MEANT THE OUTPUT DID NOT EXIST UNTIL THE PROCESS DIED (C-39).

        A timeout is still an OUTCOME, not a crash — letting `TimeoutExpired` propagate lost the
        reason, the job parked as a generic "errored" and the tech-lead diagnosed a crash that
        never happened — but the conversion now happens inside `run_and_stream`, in one place for
        both local boxes, with whatever the process had already written kept either way.

        `errors="replace"` is new and deliberate: `text=True` alone decodes strictly, so a single
        stray byte anywhere in four hours of agent output raised `UnicodeDecodeError` out of the
        sandbox — losing the entire pass to a mojibake character in a filename."""
        return run_and_stream(
            subprocess.Popen(
                command, shell=True, cwd=workspace.path,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, errors="replace", bufsize=1,
                env=_scrubbed_env(self.extra_env),
            ),
            command=command, timeout=timeout, buffer=self._output, on_output=on_output,
        )

    def tail(self) -> list[str] | None:
        """Never None: a local subprocess's pipe is the shortest read there is, and this box says
        so as `streams=True` in the registry. The two answers are one claim — see the guard in
        `tests/test_the_box_transmits_while_it_runs.py` that checks the trait against the box."""
        return self._output.take()

    @staticmethod
    def _in_home(relative: str) -> Path | None:
        """`$HOME/relative`, or None when `relative` is not a plain relative path — the same rule
        the container box applies, because the two boxes must not disagree about what a caller is
        allowed to name (`..` would reach outside the harness's own state)."""
        rel = (relative or "").strip()
        if not rel or rel.startswith("/") or ".." in Path(rel).parts:
            log.warning("refusing %r as a path inside HOME — it must be relative and must not "
                        "climb out of it", relative)
            return None
        return Path.home() / rel

    @staticmethod
    def _no_symlinks(directory: str, names: list[str]) -> list[str]:
        """Symlinks are dropped rather than followed. A harness home can hold links into the
        checkout or into the operator's own dotfiles, and restoring one into the NEXT box would be
        a persistence channel — the property the session snapshot has always had, kept here now
        that the copy happens through the box instead of through a tar."""
        return [n for n in names if (Path(directory) / n).is_symlink()]

    def export_home_dir(self, *, workspace: Workspace, relative: str, dest: Path) -> bool:
        """See the port. This box IS the host, so the transfer is a copy — but still a COPY, not a
        path handed out: the caller archives and stores what it is given, and a directory the
        harness is still writing to would otherwise change underneath it."""
        src = self._in_home(relative)
        if src is None or not src.is_dir():
            return False
        try:
            if dest.exists():
                shutil.rmtree(dest, ignore_errors=True)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, dest, symlinks=False, ignore=self._no_symlinks)
        except OSError as exc:
            log.warning("could not copy %s out of the worktree box (%s)", relative, exc)
            return False
        return dest.is_dir()

    def import_home_dir(self, *, workspace: Workspace, src: Path, relative: str) -> bool:
        """See the port. MERGES — on this box HOME belongs to the process, not to the job."""
        target = self._in_home(relative)
        if target is None or not src.is_dir():
            return False
        try:
            target.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, target, symlinks=False, ignore=self._no_symlinks,
                            dirs_exist_ok=True)
        except OSError as exc:
            log.warning("could not copy %s back into the worktree box (%s)", relative, exc)
            return False
        return target.is_dir()

    def diff_paths(self, *, workspace: Workspace) -> list[str]:
        rc, out = _run(
            ["git", "diff", "--name-only", f"{workspace.base_branch}..HEAD"], cwd=workspace.path
        )
        return [ln for ln in out.splitlines() if ln.strip()] if rc == 0 else []

    def publish_branch(self, *, workspace: Workspace, remote_url: str | None = None) -> None:
        # push to the authenticated bot remote if given, else the shared origin.
        # --force so a retry after a partial failure (branch already pushed, then the task
        # died) overwrites the bot's OWN dedicated openfactory/<id> branch instead of dead-locking
        # on a non-fast-forward forever. Safe: this branch is unique per job and only ever
        # the bot's; execution is serial (idempotency, engineering.md #3).
        target = remote_url or "origin"
        rc, out = _run(
            ["git", "-C", str(workspace.path), "push", "--force", target, workspace.branch]
        )
        if rc != 0:
            raise RuntimeError(f"push failed: {_redact(out)}")

    def rebase_onto_base(
        self, *, workspace: Workspace, base: str, remote_url: str | None = None
    ) -> str:
        # Framework-side (host creds), like publish_branch: fetch the latest base and, if the
        # branch is behind it, rebase onto it. Returns "up_to_date" (base already an ancestor
        # → nothing to do), "rebased" (moved onto newer base → caller must re-validate), or
        # "conflict" (textual conflict → aborted, tree left clean for a human).
        wp = str(workspace.path)
        target = remote_url or "origin"
        rc, out = _run(["git", "-C", wp, "fetch", target, base], timeout=180)
        if rc != 0:
            raise RuntimeError(f"fetch failed: {_redact(out)}")
        # already on top of the latest base? (fetched base is an ancestor of HEAD)
        rc, _ = _run(["git", "-C", wp, "merge-base", "--is-ancestor", "FETCH_HEAD", "HEAD"])
        if rc == 0:
            return "up_to_date"
        rc, out = _run(["git", "-C", wp, "rebase", "FETCH_HEAD"])
        if rc != 0:
            _run(["git", "-C", wp, "rebase", "--abort"])
            return "conflict"
        return "rebased"

    def cleanup(self, *, workspace: Workspace) -> None:
        if self._repo_root:
            _run(
                ["git", "-C", str(self._repo_root), "worktree", "remove", "--force",
                 str(workspace.path)]
            )
        if workspace.path.exists():
            shutil.rmtree(workspace.path, ignore_errors=True)
