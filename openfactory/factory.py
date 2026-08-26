"""Construction of the orchestrator's runners from a registered project.

Extracted from the CLI so the SAME wiring builds a JobRunner / PromotionRunner
whether the trigger is `openfactory run` on the command line or a Temporal activity in
the durable runtime (ADR-0001 D-16). Adapters and credentials are assembled from
the project's manifest + the process environment, once, here.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

log = logging.getLogger("openfactory.factory")

#: Box knobs EVERY box applies, so they are never "ignored" whatever the deployment runs. Only
#: `extra_env` so far: the container passes the names through `docker -e`, the worktree spares them
#: from its credential scrub, and both are real.
_EVERY_BOX_HONOURS = frozenset({"extra_env"})


def _warn_if_a_pause_will_cost_a_second_pass(project, sandbox: str) -> None:
    """Say, ONCE and where the box is chosen, that this box cannot carry a paused session.

    `BoxTraits.transfers_state` is the pre-flight form of a question the operator otherwise only
    gets answered by a bill: a box that cannot hand its harness state over resumes COLD after a
    rate-limit pause — it replans, re-implements and spends a second agent pass on work already
    done. The trait exists so that is knowable BEFORE the pause, which means something has to ask
    it; a declaration nobody consults is this repository's signature defect wearing a contract."""
    from openfactory.adapters.sandbox.registry import box_traits

    try:
        if box_traits(sandbox).transfers_state:
            return
    except ValueError:
        return  # an unknown box is the box registry's error to report, with its own list
    log.warning(
        "project %r runs in the %r box, which cannot carry a paused agent session — if the "
        "harness hits its usage limit mid-job, the resumed run starts cold (it replans and "
        "re-implements, spending a second agent pass on work already done)",
        getattr(project, "name", "?"), sandbox,
    )


def _warn_unhonoured_knobs(project, sandbox: str, knobs: dict) -> None:
    """Say so when the registry declares box knobs the chosen box cannot apply.

    A WARNING, where `box.image` RAISES, and the asymmetry is the point: the image decides what
    code runs, so accepting one and running another is a lie about the work. These bound resources
    — a misconfiguration to correct, not a reason to stop a delivery. What is not acceptable is
    silence: a `network:` nobody applies means an egress restriction somebody believes is in place
    is not."""
    from openfactory.adapters.sandbox.registry import box_traits

    try:
        if box_traits(sandbox).honours_image:
            return
    except ValueError:
        return  # an unknown box is the box registry's error to report, with its own list

    # `extra_env` is honoured by EVERY box, so it must never appear in this list. It used to be
    # container-only, and when the worktree learned it (the judging roles run there, and a Bedrock
    # deployment's credential arrives through it) this warning kept naming it — telling an operator
    # their credential was "IGNORED" at the exact moment it was being passed. A warning that is
    # wrong in the reassuring direction is a bug; one that is wrong in the alarming direction sends
    # somebody to fix what already works.
    unhonoured = sorted(set(knobs) - _EVERY_BOX_HONOURS)
    if not unhonoured:
        return
    log.warning(
        "project %r declares box %s, but this deployment's box is %r, which applies none of them "
        "— they are IGNORED, so whatever they were meant to bound is not bounded",
        getattr(project, "name", "?"), ", ".join(f"`{k}`" for k in unhonoured), sandbox,
    )


#: A clone URL, in either shape git accepts: `scheme://host/path` or `user@host:path`.
_URL = re.compile(r"^[a-z][a-z0-9+.-]*://|^[^/\\]+@[^/\\]+:")


def looks_like_a_clone_url(repo_path: str) -> bool:
    """Whether this is something to FETCH rather than a directory to read.

    A local path that happens to point at a git directory is still a path — `/srv/acme.git` is not
    fetched. Only a URL is."""
    return bool(_URL.search((repo_path or "").strip()))


def resolve_repo_path(project, *, token: str | None = None, cache_key: str | None = None) -> Path:
    """The DIRECTORY this project's code is in, fetching it if all we have is a URL (#65).

    `openfactory project add --help` says "Local path or clone URL", and only the first half was
    implemented: the URL was handed to `Path()`, which collapsed `https://` to `https:/`, and the
    platform then reported *"your repository has no manifest at
    https:/github.com/o/n.git/.sdlc/project.yaml"* — blaming the client for looking in the wrong
    place ourselves.

    It matters beyond the message. `ContainerSandbox.prepare` builds its workspace with
    `git clone --local <repo_path>`, which needs a real directory. On a laptop the operator already
    has a checkout and on Fargate the task clones before starting, so the gap was invisible in both
    deployments that existed — and total in the one we hand a company, where nothing clones and the
    stack comes up healthy and cannot run a ticket.

    `RepoCache` does the fetching: a stable path across calls, content replaced by atomic swap so a
    reader is never pulled out from under, and never raising. It was built for the product module's
    documentation repository, which is the same problem.

    RAISES when a URL cannot be fetched, rather than returning the cache's `None`. A None reaching
    `git clone --local` is the mangled-path failure again one layer down; a sentence naming the
    reference is what somebody can act on.

    THE CREDENTIAL IS A DEPLOYMENT FACT, so an unset `token` resolves this installation's own
    rather than fetching anonymously. `load_manifest` calls this with no token — it is reached from
    `doctor`, `conformance` and the panel, none of which hold one — and a private repository would
    otherwise fail there with a permissions error while `build_runner` succeeded, which is the
    worst kind of inconsistency to debug. An explicit token still wins, so the job path passes the
    one it already minted instead of paying for a second.
    """
    raw = (project.repo_path or "").strip()
    if not looks_like_a_clone_url(raw):
        return Path(raw).expanduser()
    if token is None:
        from openfactory.credentials import deployment_forge_token, forge_token_for

        # `deployment_forge_token`, NOT `github_app_token_from_env` (#162). The fallback is "what
        # can this DEPLOYMENT mint for this project's forge", and the answer for a non-GitHub axis
        # is nothing — a token from the wrong system is worse than none, because it fails as a 401
        # that reads like a revoked credential rather than as a missing one.
        token = forge_token_for(project) or deployment_forge_token(project)

    from openfactory.loader import load_manifest_base_branch
    from openfactory.runtime.repo_cache import RepoCache

    # `cache_key` because one PROJECT can own several repositories (C-18): a card qualified with
    # `owner/name#n` is worked against that repo, and two repositories sharing one checkout key
    # would hand the second job the first one's tree — the same file names, the wrong code.
    # `default=""` — the repository's OWN default branch when the registry names none (#162). This
    # asked for `main` and a client on `master` could not be fetched at all: the clone named a
    # branch that does not exist and the error read as "it could not be fetched", which sent
    # somebody to check the URL and the credential.
    checkout = RepoCache().sync(cache_key or project.name, _authenticated(project, raw, token),
                                load_manifest_base_branch(project, default=""))
    if checkout is None:
        raise RuntimeError(
            f"project {project.name!r} is registered as {raw!r} and it could not be fetched. "
            "Check the URL and the forge credential this deployment holds — the fetch happens on "
            "the WORKER, so a clone that works on your machine says nothing about it"
        )
    return checkout


def _authenticated(project, url: str, token: str | None) -> str:
    """`url` carrying `token` if this project's forge owns the host — ASKED, not spelled (#162).

    WHAT THIS USED TO BE was a credential-forwarding primitive: it injected
    `x-access-token:<token>@` into ANY `https://` URL, on a neutral path, with one vendor's
    spelling. Two ways that goes wrong and both are reachable:

      · a project registered as GitHub whose `repo_path` names another host receives this
        deployment's App token there — and `project init` registers `kind="github"` for every URL
        that is not an Azure one, so a GitLab path arrives here labelled GitHub;
      · an Azure project got GitHub's spelling, which Azure accepts (it ignores the username), so
        the weld LOOKED correct on the second vendor while the credential resolution beside it was
        the thing actually at fault.

    THE TOKEN IS HANDED TO `build_forge`, NOT TO THE URL. Which credential ends up on it is the
    ADAPTER's decision — the Azure row refuses an ambient GitHub token outright — so a caller that
    passes the wrong axis's secret gets an unauthenticated URL rather than a wrapped leak.

    A FORGE WE CANNOT BUILD LEAVES THE URL ALONE rather than falling back to the old injection.
    `build_forge` raises on an unknown kind on purpose, and a registry row nobody implements must
    not be the one case that still forwards a credential to an arbitrary host."""
    if not token:
        return url
    from openfactory.adapters.forge.registry import build_forge

    try:
        return build_forge(project, token=token).authenticated_url(url)
    except Exception as exc:  # noqa: BLE001 — no forge is an unauthenticated URL, never a raise
        log.warning("no forge to authenticate %s with for %s (%s) — cloning without a credential",
                    url.split("://", 1)[-1].split("/")[0], getattr(project, "name", "?"),
                    str(exc)[:120])
        return url


def resolve_box_image(project=None, *, explicit: str | None = None,
                      sandbox: str | None = None) -> str:
    """WHICH IMAGE the box runs — decided here and nowhere else (ADR-0037 D4).

    Most specific wins:

        `explicit`            an operator overriding for one run (`--image`)
        `project.box.image`   what this client's stack needs
        `OPENFACTORY_SANDBOX_IMAGE`  a deployment-wide default
        `DEFAULT_BOX_IMAGE`   the framework's own

    THIS IS A BUG FIX BEFORE IT IS A FEATURE. The name was a literal in six places and
    `OPENFACTORY_SANDBOX_IMAGE` — which `docker-compose.yml` sets — was read by none of them, so the
    OSS
    distribution ran an image different from the one it declared and no deployment could change the
    box at all. `io.py`'s own docstring names that defect (C-13, *"a configuration that looks
    configured and is ignored"*): it was fixed there for `OPENFACTORY_SANDBOX` and left standing
    one line
    below for the image.

    BLANK IS NOT A CHOICE. An empty or whitespace value is somebody who started typing, not a
    request for the empty image; it falls through. Any other reading eventually runs
    `docker run ''`.

    A BOX THAT CANNOT HONOUR THE DECLARATION REFUSES IT, rather than ignoring it. `fargate` runs
    the whole job inside a task whose image is baked into the task definition; `worktree` has no
    image at all. Silently accepting `box.image` for either would recreate C-13 in the release that
    fixes it — and `worktree` is the CLI's default while both live deployments are fargate, so
    between them that covers nearly every run.

    THE QUESTION IS ASKED OF THE BOX, not of a vendor name. `BoxTraits.honours_image` exists so a
    new box cannot join the registry without answering it; the first version of this checked
    `sandbox == "fargate"` and therefore let `worktree` — the default — ignore the declaration in
    silence, which is the same defect the check was written to prevent.

    NEVER CALL THIS FROM A WORKFLOW BODY. It reads the environment, so it would replay differently
    on a worker started with different configuration — the rule `adapters/sandbox/registry.py`
    states. Resolve at launch, stamp the answer into the job input.
    """
    import os

    from openfactory.adapters.sandbox.registry import DEFAULT_BOX_IMAGE, box_traits

    declared = (getattr(getattr(project, "box", None), "image", None) or "").strip()
    kind = (sandbox or "").strip().lower()
    if declared and kind:
        try:
            honours = box_traits(kind).honours_image
        except ValueError:
            # An unknown kind is the box registry's error to report, with its list of what IS
            # supported. Turning it into a confusing image error here would bury the real one.
            honours = True
        if not honours:
            raise ValueError(
                f"project {getattr(project, 'name', '?')!r} declares box.image={declared!r}, but "
                f"this deployment's box is {kind!r}, which cannot honour it — so the declaration "
                "would be silently ignored. Use the 'container' box, or remove box.image "
                "(ADR-0037 D1; the cloud path is phase 2)."
            )

    for candidate in (explicit, declared, os.environ.get("OPENFACTORY_SANDBOX_IMAGE")):
        if (candidate or "").strip():
            return candidate.strip()
    return DEFAULT_BOX_IMAGE


def github_app_token_from_env() -> str | None:
    """Auto-mint a GitHub App installation token from env vars, if all present."""
    from openfactory.credentials import app_id, app_installation_id, app_private_key

    aid, key, inst = app_id(), app_private_key(), app_installation_id()
    if not (aid and key and inst):
        return None
    from openfactory.adapters.github_app import mint_installation_token

    return mint_installation_token(app_id=aid, private_key=key, installation_id=inst)[0]


def notifier_for_project(project=None):
    """A project's push channel (ADR-0015) — resolved by the notifier REGISTRY
    (`adapters/notify/registry.py`), which is where the rows, the declared deployment-wide
    fallback and the add-on lookup live since 2026-08-26. This name stays because the eight call
    sites that speak
    unprompted (impediment diagnosis, deploy outcomes, PR ready, prod approval) call it, and a
    composition root that knew Slack's env vars by heart was an if-chain no stranger could join."""
    from openfactory.adapters.notify.registry import build_notifier

    return build_notifier(project)


def notifier_from_env():
    """Project-less callers: the declared fallback kind (`OPENFACTORY_NOTIFIER_FALLBACK`, a row on
    the notifier axis) or Null. A channel's own routing needs a project's coordinates — use
    notifier_for_project(project)."""
    return notifier_for_project(None)


def _bot_token_provider():
    """A callable that mints/refreshes the GitHub App installation token on demand, or
    None if App creds aren't configured. Used so a job that outlives the ~1h token still
    authenticates its late push/PR (engineering.md #4)."""
    from openfactory.credentials import app_id, app_installation_id, app_private_key

    aid, key, inst = app_id(), app_private_key(), app_installation_id()
    if not (aid and key and inst):
        return None
    from openfactory.adapters.github_app import GitHubAppTokenProvider

    return GitHubAppTokenProvider(app_id=aid, private_key=key, installation_id=inst).token


def build_runner(project, issue: str, *, sandbox: str, image: str, review: bool, events=None,
                 repo_key: str | None = None):
    """Assemble a JobRunner for one ticket: tracker + forge + agent + sandbox +
    reviewer + manifest + bot identity, credentials from env. `events` overrides the
    default journal (e.g. a Tee that also streams to stdout in a Fargate task).

    `repo_key` NAMES WHICH OF THE PROJECT'S REPOSITORIES this run works in (C-18). One product can
    own several — a card qualified `owner/name#n` is worked against its own — and two of them must
    share neither a checkout nor a container name. Absent → the project's name, which is what every
    single-repo project has always used, so nothing moves for them."""
    from openfactory.adapters.agent import build_executor, build_reviewer
    from openfactory.adapters.forge.registry import build_forge
    from openfactory.adapters.sandbox.registry import build_sandbox
    from openfactory.adapters.tracker.registry import build_tracker
    from openfactory.credentials import (
        bot_identity,
        deployment_forge_provider,
        deployment_forge_token,
        deployment_tracker_provider,
        forge_token_for,
        tracker_token_for,
    )
    from openfactory.loader import load_manifest
    from openfactory.observability.registry import journal_for
    from openfactory.orchestrator import JobRunner
    from openfactory.paths import events_file, project_log_dir

    # RESOLVED, not assumed to be a directory. A registered clone URL is fetched here, once, so
    # every consumer below — the manifest reader, the box's `git clone --local`, the worktree root
    # — gets a real path instead of `https:/github.com/...` (#65).
    repo_path = resolve_repo_path(project, token=forge_token_for(project)
                                  or deployment_forge_token(project), cache_key=repo_key)
    # The REGISTRY decides which box — a ternary here meant any unknown kind silently produced a
    # worktree, which isolates the code state and nothing else. Untrusted work outside a sandbox,
    # from a typo (C-10).
    # `project=` so the box carries WHOSE it is. Without it the container is named from the branch
    # alone (`openfactory/<issue>`), and issue numbers are per-repository — one deployment hosts N
    # projects, so two clients' ticket #12 were literally the same container name.
    #
    # And the registry's `box:` knobs are FORWARDED, not merely declarable. `BoxConfig` shipped with
    # network / cache_volume / cpus / memory and this call passed none of them — the same defect
    # D4 had just fixed for `image`, one field over, in the change that fixed it. Only the keys the
    # operator actually set are passed, so an absent block leaves every default exactly where it
    # was and no project that exists today moves.
    declared = getattr(project, "box", None)
    knobs = {
        key: value
        for key in ("network", "cache_volume", "cpus", "memory")
        if (value := getattr(declared, key, None)) is not None
    }
    # `box.env` — the NAMES of variables this project's box may receive (harness via Bedrock or
    # a gateway, a client's scanner credentials). Forwarded like every other knob so a box that
    # cannot honour it says so instead of silently not passing what the operator declared.
    if declared_env := tuple(getattr(declared, "env", None) or ()):
        knobs["extra_env"] = declared_env
    # The harness toolbox (ADR-0037 D2) is a DEPLOYMENT fact, not a project one: it is the same
    # volume for every project on this worker, and a client has no business naming it. Absent →
    # the box mounts nothing and the harness has to be in the image, which is the pre-D2 world and
    # still what a local `openfactory run` against a worktree does.
    if toolbox_volume := (os.environ.get("OPENFACTORY_TOOLBOX_VOLUME") or "").strip():
        knobs["toolbox"] = toolbox_volume
    if knobs:
        _warn_unhonoured_knobs(project, sandbox, knobs)
    _warn_if_a_pause_will_cost_a_second_pass(project, sandbox)
    # `project=repo_key or name` for the same reason the checkout is keyed that way: the container
    # is named `openfactory-<project>-<issue>`, and a multi-repo product's `-api#1` and `-web#1`
    # are two
    # different jobs that would otherwise ask docker for one name.
    sb = build_sandbox(sandbox, image=image, project=repo_key or project.name,
                       root=repo_path.parent / ".openfactory-worktrees", **knobs)
    # THE PROVIDER IS THE AXIS VENDOR'S OWN, OR NONE. This was `prov = _bot_token_provider()` —
    # the GitHub App minter, re-minting during a long job (H3) — handed to BOTH axes for every
    # kind, so a third-party forge add-on with no credential of its own received a callable that
    # mints GitHub tokens, and only the shipped Azure and Jira rows knew to refuse it (measured
    # 2026-08-24). Each axis now asks the credential registry for ITS vendor's provider, which
    # is the App minter for the reference vendor and None for a vendor that declares none.
    return JobRunner(
        project=project,  # ADR-0027: the gate needs to know whose board this is
        # the REGISTRY decides which provider — the factory composes a runner, it does not pick
        # a vendor (a client on Jira changes one registry value and nothing here)
        tracker=build_tracker(project, token=tracker_token_for(project),
                              token_provider=(None if tracker_token_for(project)
                                              else deployment_tracker_provider(project))),
        forge=build_forge(project, token=forge_token_for(project),
                          token_provider=(None if forge_token_for(project)
                                          else deployment_forge_provider(project))),
        # WHICH harness writes the code is config, not an import (agent/registry.py)
        agent=build_executor(project, log_dir=project_log_dir(project)),
        sandbox=sb,
        manifest=load_manifest(project, repo_root=repo_path),
        repo_path=repo_path,
        # the reviewer is its OWN role: a project can review with a different
        # harness from the one that wrote the code, which is what makes the
        # prompt's "you did NOT write this code" structurally true.
        reviewer=build_reviewer(project) if review else None,
        events=events or journal_for(events_file(project, issue)),
        bot=bot_identity(),
        # THE PROJECT'S CHANNEL, not the project-less fallback. `notifier_from_env`'s own
        # docstring says it: "Slack routing needs a project's channel — use
        # notifier_for_project(project)" — and both builders called the other one with `project`
        # right there in scope. Everything these two runners escalate ("staging deploy/health
        # failed", "prod verification failed — rolling back", "awaiting a human's approval") went
        # to a NullNotifier and was dropped, silently, unless a global Telegram happened to be set.
        # The instruction was written down and not followed, in the file that wrote it.
        notifier=notifier_for_project(project),
    )


def build_promotion_runner(project, issue: str):
    """Assemble a PromotionRunner (post-merge: staging observe → prod release)."""
    from openfactory.adapters.environment.registry import build_observer
    from openfactory.adapters.forge.registry import build_forge
    from openfactory.adapters.tracker.registry import build_tracker
    from openfactory.credentials import (
        deployment_forge_provider,
        deployment_forge_token,
        deployment_tracker_provider,
        forge_token_for,
        tracker_token_for,
    )
    from openfactory.loader import load_manifest
    from openfactory.observability.registry import journal_for
    from openfactory.orchestrator.promotion import PromotionRunner
    from openfactory.paths import events_file

    # WHAT THIS DEPLOYMENT CAN MINT FOR THIS PROJECT'S FORGE — `None` for a vendor whose
    # credential row declares no mint (#162). It was `github_app_token_from_env()`,
    # unconditional: an Azure project with no forge credential of its own handed a GitHub App
    # token to its observer and to the repo fetch, which is the cross-vendor leak one axis over.
    # It also spent an HTTPS round trip minting a token for a forge that could never use it.
    app_tok = deployment_forge_token(project)  # observer takes a static token (short op)
    # Resolved here too: the promotion path reads the manifest for the deploy/verify commands, and
    # a URL-registered project would otherwise look for it under `https:/...` (#65).
    repo_path = resolve_repo_path(project, token=forge_token_for(project) or app_tok)
    return PromotionRunner(
        # the REGISTRY decides which provider — the factory composes a runner, it does not pick
        # a vendor (a client on Jira changes one registry value and nothing here). The re-minting
        # provider is the AXIS VENDOR's own (the App minter on the reference vendor, None on a
        # vendor that declares none) — see `build_runner` for the measurement.
        tracker=build_tracker(project, token=tracker_token_for(project),
                              token_provider=(None if tracker_token_for(project)
                                              else deployment_tracker_provider(project))),
        forge=build_forge(project, token=forge_token_for(project),
                          token_provider=(None if forge_token_for(project)
                                          else deployment_forge_provider(project))),
        observer=build_observer(project, token=forge_token_for(project) or app_tok),
        manifest=load_manifest(project, repo_root=repo_path),
        events=journal_for(events_file(project, issue)),
        # AND WHICH LANGUAGE IT SAYS ALL OF THAT IN (#160). Every sentence the promotion runner
        # produces is unprompted, and most land on the TICKET — the one surface a project has
        # whether or not a channel is configured, and so the one where an English-only narration
        # reached a client who had declared otherwise.
        language=str(getattr(project, "language", "") or ""),
        # THE PROJECT'S CHANNEL, not the project-less fallback. `notifier_from_env`'s own
        # docstring says it: "Slack routing needs a project's channel — use
        # notifier_for_project(project)" — and both builders called the other one with `project`
        # right there in scope. Everything these two runners escalate ("staging deploy/health
        # failed", "prod verification failed — rolling back", "awaiting a human's approval") went
        # to a NullNotifier and was dropped, silently, unless a global Telegram happened to be set.
        # The instruction was written down and not followed, in the file that wrote it.
        notifier=notifier_for_project(project),
    )
