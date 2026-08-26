"""The program that runs INSIDE the box — whatever the box is.

MOVED OUT OF `runtime/fargate/` AND THAT IS THE WHOLE POINT. Not one of the thirteen symbols here
touches AWS: no boto3, no ECS, no CloudWatch. This is the entrypoint of a BOXED JOB — the same
program whether the box is a Fargate task, a Docker container on the client's own EC2 instance, a
pod in their cluster, or a laptop. Its sibling `fargate/launcher.py` is the vendor half (five of
its six symbols are ECS and CloudWatch) and stays where it is.

THE ADDRESS WAS THE LIE, NOT THE CODE. `runtime/temporal/worker.py` imported `materialize_app_key`
from `openfactory.runtime.boxed_job`, and `activities.py` imported `BoxConfig` — the box's own
configuration contract — from the same place, on paths that never go near a cloud. Anybody reading
those lines concludes the worker needs Fargate. It does not, and it never did; `default_sandbox()`
answers `container` unless the deployment declares another box in `OPENFACTORY_SANDBOX`.

The product owner put the principle plainly on 2026-08-06: *"the worker and the job are what
circulate — they have to be entirely local, not least because a client may simply want to bring up
machines (EC2, say) instead of using Fargate."* The code already obeyed it. Only the import path
disagreed, and an import path is what a reader believes.
"""


from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

RESULT_PREFIX = "OPENFACTORY_RESULT_JSON:"
_DONE = {"pr_open", "merged", "done", "awaiting_prod_approval"}


def clone_url(cfg: BoxConfig, *, token: str | None) -> str:
    """The URL that clones this job's repository — ASKED OF THE FORGE PORT, not spelled here.

    THE WELD THIS REPLACED (#162): `https://…@github.com/{repo}.git`, built by hand and blind to
    `BoxConfig.forge_kind`, which has been carried in since the day the box stopped hardcoding its
    provider. A boxed job on an Azure DevOps deployment therefore cloned a github.com URL for a
    repository that lives at `dev.azure.com/{org}/{project}/_git/{repo}` — and Azure's paths nest
    three coordinates where GitHub's take two, so no amount of substituting a host would have
    fixed it. The adapter is the only thing that knows the shape.

    It also cost the GitHub path something: `GH_HOST` was already honoured by the adapter, so a
    GitHub Enterprise deployment cloned from github.com from here while every other read went to
    their own host.

    `token` IS A QUESTION, NOT A VALUE. Truthy means "authenticated, with whatever credential the
    FORGE axis owns" — which is not necessarily this one: `clone_url_for` exists precisely because
    the Azure row refuses an ambient GitHub token, and the box carries a GitHub App token. Falsy
    means NO credential at all, which is what the origin rewrite below needs and what the adapter's
    own `token=None` gives on every vendor.
    """
    from openfactory.adapters.forge.registry import build_forge, clone_url_for

    project = _project_for(cfg, repo_dir=None)
    if not token:
        # Deliberately NOT `clone_url_for(..., token=None)`: that hands back the ADAPTER's own
        # credential, which is right for cloning and wrong here — this URL exists to be the one
        # the sandboxed agent CANNOT push with.
        return build_forge(project).clone_url(cfg.repo, token=None)
    return clone_url_for(project, cfg.repo, token=token)


def redact(text: str) -> str:
    return re.sub(r"(https://)[^@/\s]+@", r"\1***@", text)


@dataclass
class BoxConfig:
    project: str
    issue: str
    repo: str
    board_owner: str | None = None
    board_number: str | None = None
    #: WHICH provider the job talks to, carried in rather than assumed. The seam was honoured
    #: everywhere except here: the box re-registers its project from the environment, and used to
    #: hardcode `kind="github"` — so a Jira deployment got a correct tracker on the worker and a
    #: GitHub client inside the container. Not a missing provider but a WRONG one, which ADR-0022
    #: calls the most expensive shape a config error takes.
    tracker_kind: str = "github"
    forge_kind: str = "github"
    #: EACH AXIS'S OWN COORDINATES, opaque to the box and carried whole (#162). The kind travelled
    #: and the options did not, which is half a seam: `azure_devops` names an adapter that cannot
    #: be built without an organization and a project, so a box told only the KIND raises where a
    #: box told nothing at all silently cloned the wrong host. Whole rather than
    #: key-by-key because `board_owner`/`board_number` below are GitHub Projects' vocabulary — two
    #: hand-picked keys is how a neutral contract learns one vendor's shape.
    tracker_options: dict[str, str] = field(default_factory=dict)
    forge_options: dict[str, str] = field(default_factory=dict)
    review: bool = True
    resume_handle: str | None = None  # C2: opaque token to resume a prior paused attempt
    spent_turns: int = 0  # cumulative effort already spent on this ticket (ADR-0013 D4)
    decision: str = ""  # a resolved human choice to inject into the agent (a resumed blocker)


def materialize_app_key(env: dict[str, str], *, dest_dir: Path) -> str | None:
    """Secrets Manager delivers the bot App private key as content (OPENFACTORY_GH_APP_KEY_CONTENT);
    the token minter wants a file path. Write it out and return the path (or None)."""
    content = env.get("OPENFACTORY_GH_APP_KEY_CONTENT")
    if not content or env.get("OPENFACTORY_GH_APP_KEY"):
        return None
    path = dest_dir / "openfactory-bot.pem"
    # create 0600 atomically (O_EXCL) — never a world-readable window on the private key
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(content)
    os.environ["OPENFACTORY_GH_APP_KEY"] = str(path)
    return str(path)


def _options(raw: str | None) -> dict[str, str]:
    """A provider's options, as the launcher JSON-encoded them — or `{}`."""
    import json

    if not raw:
        return {}
    try:
        got = json.loads(raw)
    except ValueError:
        print(f"OPENFACTORY_WARN: could not read provider options ({raw[:60]!r}) — continuing "
              f"without them", flush=True)
        return {}
    return {str(k): str(v) for k, v in got.items()} if isinstance(got, dict) else {}


def config_from_env(env: dict[str, str]) -> BoxConfig:
    missing = [k for k in ("OPENFACTORY_PROJECT", "OPENFACTORY_ISSUE", "OPENFACTORY_REPO")
               if not env.get(k)]
    if missing:
        raise KeyError(f"missing required env: {', '.join(missing)}")
    return BoxConfig(
        project=env["OPENFACTORY_PROJECT"],
        issue=env["OPENFACTORY_ISSUE"],
        repo=env["OPENFACTORY_REPO"],
        board_owner=env.get("OPENFACTORY_BOARD_OWNER") or None,
        board_number=env.get("OPENFACTORY_BOARD_NUMBER") or None,
        # `or "github"` is a MIGRATION window, not a preference. A deploy replaces the worker
        # while jobs are in flight, and a box launched by the previous build has neither variable
        # in its environment; it must keep behaving exactly as it did rather than fail on an
        # absent one. An empty string counts as absent — that is what a shell exports for an
        # unset variable, and an empty kind would raise `unknown tracker ''` deep inside the job
        # instead of at the door.
        tracker_kind=env.get("OPENFACTORY_TRACKER_KIND") or "github",
        forge_kind=env.get("OPENFACTORY_FORGE_KIND") or "github",
        # JSON, because these are a provider's own vocabulary and the box may not name a single
        # key of it. A malformed map reads as ABSENT rather than raising: the box is the far end
        # of a launch nobody is watching, and failing here loses a run over a variable, where
        # continuing loses at most the options the launcher meant to add.
        tracker_options=_options(env.get("OPENFACTORY_TRACKER_OPTIONS")),
        forge_options=_options(env.get("OPENFACTORY_FORGE_OPTIONS")),
        review=env.get("OPENFACTORY_REVIEW", "true").lower() not in ("0", "false", "no"),
        resume_handle=env.get("OPENFACTORY_RESUME_HANDLE") or None,
        spent_turns=int(env.get("OPENFACTORY_SPENT_TURNS") or 0),
        decision=env.get("OPENFACTORY_DECISION") or "",
    )


def _clone(cfg: BoxConfig, dest: Path, token: str | None) -> None:
    p = subprocess.run(
        ["git", "clone", "--no-single-branch", clone_url(cfg, token=token), str(dest)],
        capture_output=True, text=True, timeout=300,
    )
    if p.returncode != 0:
        raise RuntimeError(f"clone failed: {redact(p.stderr)}")
    # Strip the embedded bot token from `origin` so the sandboxed agent can't `git push`
    # with it. The framework publishes via an explicit authenticated remote
    # (forge.push_remote()), so the real push is unaffected — this only denies the agent a
    # ready-to-use credentialed remote (defence in depth alongside the scrubbed env + the
    # executor's no-git instruction; #232 pushed a stray branch this way).
    if token:
        subprocess.run(
            ["git", "-C", str(dest), "remote", "set-url", "origin", clone_url(cfg, token=None)],
            capture_output=True, text=True, timeout=30,
        )


def _project_for(cfg: BoxConfig, *, repo_dir: Path | None):
    """The project the job runs against, built from what the launcher carried in.

    Pure and shared, because it was written twice — once in `run_boxed` and once in `_register` —
    and both copies hardcoded `kind="github"`. A seam honoured on the worker and abandoned inside
    the box is not a seam; it is the wrong client, authenticating against the wrong host, arriving
    as a permissions error (ADR-0022 §1).

    The forge is stated explicitly rather than left to fall back on the tracker: `forge_kind` and
    `tracker_kind` are separable axes, and a Jira-tracker/GitHub-forge project is the ordinary case
    the contract was designed for.
    """
    from openfactory.contracts.project import Project, ProviderRef

    # THE LEGACY PAIR IS A FLOOR, NOT A CEILING (#162). A box launched by an older worker carries
    # `board_owner`/`board_number` and no options map at all; one launched by this worker carries
    # the whole map, which already contains those two. Merging in that order means an older
    # launcher keeps working and a newer one is never overridden by a subset of itself.
    legacy: dict[str, str] = {}
    if cfg.board_owner and cfg.board_number:
        legacy = {"board_owner": cfg.board_owner, "board_number": cfg.board_number}
    return Project(
        name=cfg.project,
        repo_path=str(repo_dir) if repo_dir is not None else "",
        tracker=ProviderRef(kind=cfg.tracker_kind, repo=cfg.repo,
                            options={**legacy, **cfg.tracker_options}),
        forge=ProviderRef(kind=cfg.forge_kind, repo=cfg.repo,
                          options={**legacy, **cfg.forge_options}),
    )


def run_boxed(cfg: BoxConfig, *, workdir: Path, token: str | None) -> object:
    """Clone, register the project against the clone, and run the job. Returns a
    RunResult. Kept import-light so the pure helpers above stay unit-testable."""
    from openfactory.factory import build_runner
    from openfactory.observability.registry import journal_for
    from openfactory.paths import events_file
    from openfactory.registry import ProjectRegistry

    repo_dir = workdir / "repo"
    print("OPENFACTORY_PHASE: cloning", flush=True)
    _clone(cfg, repo_dir, token)

    # ephemeral registry, isolated to this task
    os.environ["OPENFACTORY_REGISTRY"] = str(workdir / "registry.yaml")
    reg = ProjectRegistry()
    reg.add(_project_for(cfg, repo_dir=repo_dir))
    project = reg.get(cfg.project)
    # stream events to stdout (→ CloudWatch) so the remote job is never silent
    events = journal_for(events_file(project, cfg.issue), live=True)
    print("OPENFACTORY_PHASE: running", flush=True)
    runner = build_runner(
        project, cfg.issue, sandbox="worktree", image="", review=cfg.review, events=events
    )
    result = runner.run(cfg.issue, resume_handle=cfg.resume_handle,
                        spent_turns=cfg.spent_turns, decision=cfg.decision)
    # Stamp WHICH A/B ARM this run was in (ADR-0017's gate). Stamped here rather than inside the
    # runner because `run()` returns from a dozen paths; one place at the boundary can't be
    # forgotten by a new early return. See RunResult.knowledge. Guarded because this runs AFTER
    # the ticket's work is done: an exception here would turn a finished job into a box failure,
    # which is an absurd way to lose a run over a dashboard column.
    try:
        result.knowledge = runner.knowledge_arm()
    except Exception as exc:  # noqa: BLE001 — a DASHBOARD dimension must never fail a finished run
        # The A/B loses this ticket. Never worth failing a run that worked, always worth saying.
        print(f"OPENFACTORY_WARN: could not record the knowledge arm "
              f"({str(exc)[:120]})", flush=True)
    return result


def _register(cfg: BoxConfig, workdir: Path, token: str | None):
    """Clone the repo + register the project ephemerally; return the Project."""
    from openfactory.registry import ProjectRegistry

    repo_dir = workdir / "repo"
    _clone(cfg, repo_dir, token)
    os.environ["OPENFACTORY_REGISTRY"] = str(workdir / "registry.yaml")
    reg = ProjectRegistry()
    reg.add(_project_for(cfg, repo_dir=repo_dir))
    return reg.get(cfg.project)


def run_ci_repair(cfg: BoxConfig, *, workdir: Path, token: str | None, human: bool = False):
    """One repair pass on the existing branch, pushed to the same PR. Runs INSIDE the task — it
    has gh + creds + the clone. The durable workflow drives the bounded loop.

    TWO CALLERS, ONE MACHINE. On a red CI (ADR-0004) it pulls the failing logs and asks the
    executor to fix the build. On a human `adjust` (#68) the prose is already in the environment —
    a person's review comment, framed as one by the workflow — and NO log is fetched: a green PR
    has no failed logs to read, and the fetch would be a wasted forge call in the best case and a
    misleading empty string in the worst."""
    from openfactory.adapters.forge.registry import build_forge
    from openfactory.factory import build_runner
    from openfactory.observability.registry import journal_for
    from openfactory.paths import events_file

    project = _register(cfg, workdir, token)
    events = journal_for(events_file(project, cfg.issue), live=True)
    pr = os.environ.get("OPENFACTORY_PR", "")
    if human:
        ci_log = os.environ.get("OPENFACTORY_ADJUST_TEXT", "")
    else:
        # inside the box too: the repair reads its CI logs through whichever forge the project uses
        ci_log = build_forge(project, token=token).failed_ci_logs(pr=pr) if pr else ""
    print(f"OPENFACTORY_PHASE: {'adjust' if human else 'ci-repair'}", flush=True)
    return build_runner(
        project, cfg.issue, sandbox="worktree", image="", review=cfg.review, events=events
    ).repair_ci(cfg.issue, ci_log, pr_url=pr)


def run_review_pass(cfg: BoxConfig, *, workdir: Path, token: str | None):
    """Read the open pull request again and publish a fresh verdict — a person asked (#181).

    THE ONE PASS IN THIS FILE THAT WRITES NOTHING. It needs the clone and the credential like the
    others, and unlike the others it runs no agent, no `setup:` and no push.

    `review=True` REGARDLESS OF `cfg.review`. That flag says whether a NEW job reviews what it
    builds; this box exists because somebody asked for a review, and honouring the flag here would
    answer a pressed button with silence."""
    from openfactory.factory import build_runner
    from openfactory.observability.registry import journal_for
    from openfactory.paths import events_file

    project = _register(cfg, workdir, token)
    events = journal_for(events_file(project, cfg.issue), live=True)
    pr = os.environ.get("OPENFACTORY_PR", "")
    print("OPENFACTORY_PHASE: review", flush=True)
    return build_runner(
        project, cfg.issue, sandbox="worktree", image="", review=True, events=events
    ).review_pr(cfg.issue, pr_url=pr)


def run_promotion(cfg: BoxConfig, phase: str, *, workdir: Path, token: str | None):
    """Run the post-merge promotion INSIDE the task (it has gh + creds + the cloned repo's
    manifest — the worker has none of those). phase=staging observes staging → parks;
    phase=release tags prod + observes (H12)."""
    from openfactory.factory import build_promotion_runner

    project = _register(cfg, workdir, token)
    runner = build_promotion_runner(project, cfg.issue)
    ref = f"#{cfg.issue.lstrip('#')}"
    if phase == "release":
        return runner.release_prod(
            ref,
            version=os.environ["OPENFACTORY_RELEASE_VERSION"],
            approver=os.environ["OPENFACTORY_RELEASE_APPROVER"],
            comment=os.environ.get("OPENFACTORY_RELEASE_COMMENT", ""),
        )
    return runner.promote(ref)


def _emit(result) -> None:
    """The ONE contract line the host parses out of the logs."""
    print(RESULT_PREFIX + result.model_dump_json(), flush=True)


def main() -> int:
    from openfactory.contracts import JobState, RunResult
    from openfactory.credentials import deployment_forge_token, forge_token, forge_token_for

    issue = os.environ.get("OPENFACTORY_ISSUE", "")
    try:
        cfg = config_from_env(dict(os.environ))
        # DETERMINISTIC workdir (C2, audit HIGH): the agent CLI keys its session transcripts by
        # the working directory's PATH. A random mkdtemp per container meant a resumed run's cwd
        # never matched the paused run's, so a restored session could not be found by --resume.
        # The task runs ONE job in an ephemeral container, so a fixed per-job path is collision-
        # free and makes pause-container and resume-container cwds identical.
        tag = f"openfactory-box-{cfg.project}-{cfg.issue.lstrip('#')}"
        workdir = Path(tempfile.gettempdir()) / tag
        workdir.mkdir(parents=True, exist_ok=True)
        materialize_app_key(dict(os.environ), dest_dir=workdir)
        # PER PROJECT NOW, AND THE THING THAT BLOCKED IT IS GONE. This comment used to say the box
        # could not resolve the forge credential per project because `BoxConfig` carried no
        # `token_env` — so a call to `forge_token_for` would silently fall back to the same
        # process-wide value while reading as if it had asked, which is worse than the gap. #162
        # made the box carry each axis's OPTIONS whole, and `token_env` lives in them, so the
        # question is answerable here for the first time.
        #
        # THE PROJECT OBJECT DOES NOT NEED THE CLONE. `_project_for(cfg, repo_dir=None)` is built
        # from what the launcher carried in — the same object `clone_url` already asks — so the
        # chicken-and-egg the old comment described was about a different function.
        #
        # WHAT IS STILL A GAP, and it is deployment configuration rather than code: the variable a
        # project NAMES has to actually reach the container. `forge_token_for` logs a warning when
        # it names one and finds it empty, which is the honest failure — a 401 that says which
        # variable was expected beats a 401 that says nothing.
        token = (forge_token_for(_project_for(cfg, repo_dir=None))
                 or forge_token()             # honour OPENFACTORY_BOT_TOKEN for the GitHub path
                 or deployment_forge_token(_project_for(cfg, repo_dir=None)))
        phase = os.environ.get("OPENFACTORY_PROMOTE_PHASE")
        if os.environ.get("OPENFACTORY_REVIEW_PASS"):
            # BEFORE the repair branch, and that ordering is the guard: a re-review must never be
            # dispatched as a repair, which would run an agent and push on a pull request whose
            # owner asked only to have it read.
            result = run_review_pass(cfg, workdir=workdir, token=token)
        elif os.environ.get("OPENFACTORY_CI_REPAIR") or os.environ.get("OPENFACTORY_ADJUST"):
            result = run_ci_repair(cfg, workdir=workdir, token=token,
                                   human=bool(os.environ.get("OPENFACTORY_ADJUST")))
        elif phase:
            result = run_promotion(cfg, phase, workdir=workdir, token=token)
        else:
            result = run_boxed(cfg, workdir=workdir, token=token)
    except Exception as exc:
        # ALWAYS emit a contract result. A crash with no RESULT line is invisible to the
        # host — it looks like an infra fault and triggers 5 fresh (paid) re-runs. A
        # returned FAILED result makes the activity succeed-with-failure: visible, no
        # rerun, no lost signal (engineering.md #1). Redacted so no token leaks.
        _emit(RunResult(
            ticket_id=f"#{issue.lstrip('#')}" if issue else "?",
            state=JobState.FAILED,
            note=f"box failed: {redact(str(exc))}",
        ))
        return 1
    _emit(result)
    return 0 if result.state.value in _DONE else 1


if __name__ == "__main__":
    sys.exit(main())
