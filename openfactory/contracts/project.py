"""Project registration — the framework manages *many* projects.

The framework knows nothing about any specific project; it knows about a registry
of projects, each pointing at providers along independent axes (ADR-0001): a
tracker (where tickets live), a forge (where code/PRs live), and a CI/deploy
provider (what it observes). GitHub often fills all three, but they are separable
(e.g. Jira tracker + GitHub forge). Adding a project is data, not a code change.
A project becomes runnable only once its `.openfactory/project.yaml` passes conformance.
"""

from __future__ import annotations

import logging
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from openfactory import namespace
from openfactory.contracts import aliases
from openfactory.contracts.product import ProductConfig


class ProviderRef(BaseModel):
    #: WHICH provider. The default stays — deliberately, and this is where the protection moved.
    #:
    #: Removing it was tried and reverted: it breaks 320 tests, because `Project.tracker` has a
    #: `default_factory` and every construction in the suite inherits it. Three hundred mechanical
    #: edits is three hundred chances to quietly change what a test asserts, and it would buy
    #: nothing — the failure ADR-0022 §1 names is *a deployment silently getting the wrong client*,
    #: and that is now refused one layer down: `build_tracker` and `build_forge` no longer fall
    #: back to a default, so an unset or empty kind RAISES at startup naming what IS supported.
    #:
    #: What remains is a convenience default on a model, with the real gate below it. Making the
    #: model itself strict is worth doing when `Project.tracker` loses its default_factory — a
    #: separate change, with its own card.
    kind: str = "github"  # github | gitlab | jira | jenkins | ...
    repo: str | None = None  # e.g. "owner/name"; or a project key for a tracker
    options: dict[str, str] = Field(default_factory=dict)


class FactoryBoard(BaseModel):
    """Where the FACTORY reports its own impediments — never the client's board (ADR-0027).

    The product owner named the gap the day the product role went blind mid-conversation and told
    the CLIENT about it: *"her looping with the client, nobody resolving anything, nobody knowing
    what is going on… that should be a support ticket — maybe we need a board for the factory
    itself."*

    Why a TICKET and not a Slack message: a chat line has no owner, no state and no history, so it
    scrolls away and the stall goes back to being silent — the one thing this platform promises not
    to do. Why not the client's board: a client's board carries the client's product, and eleven
    smoke-test tickets already taught that lesson once.

    Why the platform's own repository is the natural home: an impediment IS a platform defect, and
    the fix happens there — so the improvement history accumulates where improvements are made,
    instead of in a third place somebody has to remember to open.

    Per DEPLOYMENT, not global: two installations must never see each other's operational trouble.
    """

    #: where impediments are filed. A `ProviderRef` like every other axis, so a Jira deployment
    #: files them in Jira without a line of new code.
    tracker: ProviderRef | None = None

    #: the label that marks a ticket as the factory's own, so it never reads as product work
    label: str = "fabrica"

    #: WHO IS ACCOUNTABLE for the factory's health — a forge login, resolved to a channel id
    #: through `people`. An impediment with no owner is the silent wait wearing a hat, which is the
    #: whole failure this exists to end. Empty is allowed and says so loudly when one is filed.
    supervisor: str = ""


class BoxConfig(BaseModel):
    """WHERE this project's work is built, tested and written (ADR-0037 D1).

    DEPLOYMENT CONFIGURATION, AND THAT IS A SECURITY BOUNDARY, NOT A FILING PREFERENCE. The obvious
    home for this is `.openfactory/project.yaml` — it sits beside `setup:` and `validate:`, which
    are the
    commands that run inside it. But that file lives in the repository the EXECUTOR edits. An agent
    able to write `box.image` is an agent choosing its own root filesystem, which turns "the agent
    wrote the wrong code" into "the agent picked the machine". The registry is operator-owned and
    the agent cannot reach it, so it lives here — the same reason `harness` already does.

    Everything is optional, and the empty case is the pilot: no `box:` block at all resolves to the
    framework's image and today's behaviour, so this field costs no migration.
    """

    # `ignore`, NOT `forbid`, and the reason is written down one file over. `registry.py:150`:
    # *"making an unknown key fatal would turn one stale line into an outage the operator could not
    # have reviewed, since the file is invisible to every test and reviewer."*
    # `deploy/registry.yaml`
    # is gitignored and baked into the worker image. This shipped as `forbid` for one afternoon, and
    # a mistyped `netwrok:` made `ProjectRegistry.list()` raise — every project unloadable, on a
    # worker whose registry nobody can open.
    #
    # Ignored is not silent: `_report_keys` names the key, exactly as it does for `Project`.
    model_config = ConfigDict(extra="ignore")

    #: The image the box runs. What this client's own CI already uses is the intended answer —
    #: their toolchain, their CA bundle, their private-registry access, maintained by them and
    #: already trusted. Unset → `OPENFACTORY_SANDBOX_IMAGE`, then the framework's default.
    #:
    #: Resolution is `factory.resolve_box_image`, in ONE place, because this used to be a literal
    #: in six (C-13).
    image: str | None = None

    #: The network the box joins. `bridge` (the default) is full outbound internet, which the
    #: harness requires — this is how a deployment substitutes an egress-restricted network or a
    #: proxy. Named here rather than assumed, because `container.py` used to claim it denied
    #: egress by default and did not.
    network: str | None = None

    #: A docker volume for the dependency cache, so a job does not pay a full install every time.
    #: Unset by default: sharing a cache ACROSS projects is a deployment's decision, and a shared
    #: one is a channel between two clients' builds.
    cache_volume: str | None = None

    cpus: str | None = None
    memory: str | None = None

    #: NAMES of environment variables the box may receive — never their values (the registry is
    #: baked into the worker image; a value written here is a secret in an image layer, the same
    #: rule as `tracker.options.token_env` and ADR-0015's `bot_token_env`).
    #:
    #: WHY THIS EXISTS (the harness axis, 2026-08-05). The box passed through exactly two
    #: hard-coded credentials (CLAUDE_CODE_OAUTH_TOKEN / ANTHROPIC_API_KEY), which quietly assumes
    #: every deployment authenticates the harness the same way. The first enterprise client does
    #: not: Claude reaches them through Bedrock (`CLAUDE_CODE_USE_BEDROCK`, `AWS_REGION`, the AWS
    #: credential set) or through an LLM gateway (`ANTHROPIC_BASE_URL`, a gateway key). The same
    #: seam is what lets a client's security scanners authenticate inside the box
    #: (`BLACKDUCK_URL`/`BLACKDUCK_API_TOKEN`, …) without the platform learning any vendor's name.
    #:
    #: OPT-IN AND OPERATOR-OWNED, deliberately: every name listed here is a value agent-written
    #: code can read from inside the box, so listing one is a security decision — which is exactly
    #: why it lives in the registry and not in the client repo's own manifest.
    env: list[str] = Field(default_factory=list)


log = logging.getLogger("openfactory.contracts.project")

#: Names a preview may never be handed, whatever the registry lists — the factory's own
#: credentials. Prefixes are matched by `startswith`; `ProjectRegistry.list()` also refuses every
#: project's `token_env`, which only the registry as a whole knows.
PREVIEW_ENV_DENIED_PREFIXES = ("OPENFACTORY_", "TEMPORAL_", "ANTHROPIC_", "CLAUDE_")
PREVIEW_ENV_DENIED = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "GH_TOKEN", "GITHUB_TOKEN",
                      "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
                      "AZURE_DEVOPS_PAT", "JIRA_API_TOKEN")
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def preview_name_refused(name: str) -> str:
    """Why a name may not reach a preview, or "" when it may."""
    if not _ENV_NAME.fullmatch(name or ""):
        return "not an environment variable name"
    if name in PREVIEW_ENV_DENIED or name.startswith(PREVIEW_ENV_DENIED_PREFIXES):
        return "a credential of the factory's own"
    return ""


def _names_by_service(v) -> dict[str, dict[str, str]]:
    """`{svc: [NAME]}` or `{svc: {CONTAINER_NAME: WORKER_NAME}}` → `{svc: {container: worker}}`,
    minus every name a preview may never receive (dropped and said, never fatal: one bad line in a
    registry nobody can open must not make every project unloadable)."""
    out: dict[str, dict[str, str]] = {}
    for svc, names in (v or {}).items():
        pairs = names.items() if isinstance(names, dict) else ((n, n) for n in names or [])
        kept: dict[str, str] = {}
        for container, worker in pairs:
            why = preview_name_refused(str(container)) or preview_name_refused(str(worker))
            if why:
                log.warning("OPENFACTORY_PREVIEW_ENV_REFUSED %s=%s for %r — %s", container, worker,
                            svc, why)
                continue
            kept[str(container)] = str(worker)
        out[str(svc)] = kept
    return out


class PreviewPolicy(BaseModel):
    """What the OPERATOR decides about a project's previews (ADR-0050 D6, D8, D9).

    In the registry, never the manifest: every field here is either a secret's name, a gate, a
    network or a limit, and the agent edits the manifest. `extra="ignore"` like `BoxConfig`, for
    the same reason: the registry is baked into the image, and one mistyped key must not make every
    project unloadable (`ProjectRegistry._report_keys` names it instead)."""

    model_config = ConfigDict(extra="ignore")

    #: D9 — the factory never merges a pull request of this project on its own; a person looks at
    #: the preview and merges.
    required: bool = False
    #: How long a preview stays up, in hours. Clamped to [1, 168].
    hours: int = 24
    #: Per service (`"*"` = every service): the names a service may receive at RUN time. The map
    #: form says which WORKER variable holds the value, so two projects on one worker can hold
    #: different `DATABASE_URL`s: `{api: {DATABASE_URL: ACME_PV_DATABASE_URL}}`.
    env: dict[str, dict[str, str]] = Field(default_factory=dict)
    #: Names that ALSO reach a BUILD of a service from the change. Empty by default, and it should
    #: stay so unless a build truly needs one: an unmerged Dockerfile with internet access can read
    #: a build argument, and it lands in the image's history.
    build_args: dict[str, dict[str, str]] = Field(default_factory=dict)
    #: An operator docker network the services also join, for egress. Empty: a preview reaches
    #: nothing outside itself. `bridge` and `host` are refused.
    network: str = ""
    cpus: str = "2"
    memory: str = "2g"
    memory_total: str = "8g"
    max_services: int = 12
    pids_limit: int = 512
    tmpfs_size: str = "256m"
    #: What stays after `cap_drop: ALL` — what the official store images need to switch user.
    caps: list[str] = Field(default_factory=lambda: [
        "CHOWN", "DAC_OVERRIDE", "FOWNER", "SETGID", "SETUID", "NET_BIND_SERVICE"])
    start_timeout_minutes: int = 30
    upstream_timeout_seconds: int = 180
    keep_failed_minutes: int = 30

    @field_validator("hours", mode="before")
    @classmethod
    def _hours_in_bounds(cls, v):
        try:
            return min(max(int(v), 1), 24 * 7)
        except (TypeError, ValueError):
            return 24

    @field_validator("env", "build_args", mode="before")
    @classmethod
    def _names(cls, v):
        return _names_by_service(v)

    @field_validator("network")
    @classmethod
    def _not_the_hosts(cls, v: str) -> str:
        v = (v or "").strip()
        if v in ("bridge", "host") or (v and not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", v)):
            log.warning("OPENFACTORY_PREVIEW_NETWORK_REFUSED %r — a preview joins an operator "
                        "network by name, never `bridge` or `host`", v)
            return ""
        return v

    def names_for(self, service: str, *, build: bool = False) -> dict[str, str]:
        table = self.build_args if build else self.env
        return {**table.get("*", {}), **table.get(service, {})}


class Project(BaseModel):
    # `populate_by_name` so code constructs with the FIELD name. A registry file may still carry an
    # old key a vendor named; it is folded into its new place (`contracts/aliases.py`) and named by
    # the registry, for one minor version. Extra keys stay IGNORED rather than forbidden: the
    # registry that would break is gitignored and baked into the worker image, so a fatal unknown
    # key would be an outage nobody could have reviewed. `ProjectRegistry.list()` reports them by
    # name instead — visibility without the outage.
    model_config = ConfigDict(populate_by_name=True)

    name: str  # unique handle, e.g. "acme", "podbeam"
    repo_path: str  # local path or clone URL of the project repo

    #: the factory's own support board. Absent → impediments are logged and nothing is filed, which
    #: is exactly today's behaviour and is stated rather than assumed.
    factory_board: FactoryBoard | None = None

    # Independent provider axes. If only some are given, missing ones fall back to
    # `tracker` (the common single-vendor case), so callers can set one and get all.
    tracker: ProviderRef = Field(default_factory=ProviderRef)
    forge: ProviderRef | None = None
    ci: ProviderRef | None = None

    #: which conversation provider carries this deployment's channels — "" = the panel, the
    #: reference surface every deployment has (ADR-0038). A chat add-on is DECLARED here by the
    #: kind its package registers; it is never inferred from a coordinate the project carries
    #: (#266 slice 6, ADR-0051 D16). The channel registry dispatches on this. An audit found the
    #: first registry reading a field that did not exist: the "unknown channel raises" branch was
    #: reachable only from a test's fake, and plugging Telegram in would have required inventing
    #: the very field the dispatch presupposes.
    channel: str = ""

    #: forge login → channel user id, declared by the deployment. WHAT SOMEBODY DECLARES BEATS
    #: WHAT THE MACHINE INFERS, and this is the difference between the mention feature working and
    #: being decorative: matching by email needs a PUBLIC email, matching by name needs a filled-in
    #: profile, matching by handle needs `octocat` on GitHub to be `octocat` on Slack.
    #: In the pilot workspace none of the three held — both profiles are private and both handles
    #: are shortened — so every question went out as plain text with nobody notified. You cannot
    #: ask a client's team to align their handles or expose their emails; you CAN write four lines
    #: of config once. Inference stays as the fallback for whoever is not listed.
    people: dict[str, str] = Field(default_factory=dict)

    #: Relative to the repo root. The default is `.openfactory/project.yaml`, the product's own
    #: name (#106 item 5); a repository still on the directory's former name is REFUSED by
    #: `openfactory/namespace.py` with a sentence saying what to rename — nothing under the old
    #: name is read. An EXPLICIT value here is never second-guessed — this field exists so a
    #: client can put the file where their own conventions say, and a fallback that overrode
    #: that would be the platform deciding it knows better than the configuration it was given.
    manifest_path: str = namespace.MANIFEST
    enabled: bool = True

    #: Whether this project's board may receive work that exists to TEST THE FACTORY (ADR-0027).
    #:
    #: FALSE BY DEFAULT, and the default is the whole point. Proving the pipeline works needs a
    #: real ticket in a real repository going through the real pipeline — and for months the only
    #: repository at hand was the pilot's. Eleven smoke-test tickets ("live autonomy demo", "panel
    #: e2e test", "autonomy proof") went through planning, execution, review and merge, and landed
    #: eleven constant-returning endpoints in a client's accounting product. `/healthz/ready`
    #: answers `{"ready": true}` without touching a dependency, in production, because we needed
    #: something to watch the pipeline with.
    #:
    #: Nobody decided that. There was simply no field to consult, so the question was never asked —
    #: the same shape as every other defect in this codebase's ledger: the information existed and
    #: nothing looked at it. A project that has not opted in is a CLIENT, and its board carries its
    #: product and nothing else.
    accepts_test_work: bool = False

    # WHICH HARNESS plays each role (openfactory/adapters/agent/registry.py). ONE line for the
    # common
    # case — a deployment that uses a single harness everywhere, including a client that has no
    # Claude account at all:
    #
    #     harness: codex
    #
    # …or per role, when they genuinely differ (e.g. keep an INDEPENDENT reviewer on a different
    # engine from the one that wrote the code):
    #
    #     harness: {executor: codex, reviewer: claude_code, techlead: claude_code}
    #
    # Roles: `executor` writes code, `reviewer` reviews the diff, `techlead` judges (sizing,
    # impediment diagnosis, Slack). Unset → the default harness.
    #
    # A DEPLOYMENT-level choice, so it lives in the registry beside the board and Slack
    # coordinates, not in the client's `.openfactory/project.yaml`: a client declares what to
    # validate,
    # not which model writes its code, and the credentials belong to whoever runs the factory.
    harness: str | dict[str, str] | None = None

    # WHICH MODEL that harness runs, in exactly the same two shapes as `harness` above:
    #
    #     model: claude-fable-5                          # every role
    #     model: {executor: gpt-5, reviewer: claude-opus-5}
    #
    # THE STRING IS THE HARNESS'S OWN, and deliberately not validated here. Each CLI names models
    # differently — `sonnet` for Claude, `provider/model` for OpenCode, a full Bedrock inference
    # profile ARN when a client runs the harness against their own AWS account. A registry that
    # policed the value would have to learn every vendor's catalogue and would reject the exact
    # strings the enterprise cases need; passing it through is what keeps the axis agnostic.
    #
    # WHY IT EXISTS (2026-08-05). Every adapter has always ACCEPTED a model, and the registry's
    # builders have always forwarded a `model=` kwarg — but no call site ever passed one, so the
    # only working control was the process-wide `OPENFACTORY_EXECUTOR_MODEL`, which is one value for
    # the
    # whole worker and needs an environment change plus a roll to move. Built, forwarded, reached
    # by nothing: this codebase's signature defect, and here it made a per-client decision
    # unexpressible. It is a per-client decision in two ways that are now concrete — which
    # PROVIDER serves a client (a Bedrock inference profile for one whose IT requires their own
    # AWS account; an Azure/gateway endpoint for another), and which TIER they are paying for
    # (a client buying Fable and a client on a cheaper model share one worker).
    #
    # Deployment-level for the same reason as `harness`: the client declares what to validate, not
    # which model writes its code, and the bill belongs to whoever runs the factory.
    model: str | dict[str, str] | None = None

    #: PROVIDER-SPECIFIC CHANNEL CONFIGURATION, in the add-on's own terms and opaque to the core:
    #: the room it posts to (`channel`, `aliases.ADDRESS`), the environment variables NAMING its
    #: workspace-scoped secrets, whatever else it reads. Options rather than fields, because what a
    #: provider needs is that provider's shape — one vendor has a bot token and an app token,
    #: another has one, the panel has none. Per-project by design (ADR-0015): one deployment hosts
    #: N projects sharing a worker, panel and engine, and each may have its OWN workspace, room and
    #: bot — full isolation on the client-facing surface. The first-class channel id and the two
    #: token fields a vendor shaped were folded in here (#266 slice 6, ADR-0051 D16), and their old
    #: spellings are read as aliases until `aliases.READ_UNTIL`.
    channel_options: dict[str, str] = Field(default_factory=dict)

    #: WHO may make the tech-lead act (resume/skip a parked job) — PEOPLE OF THE PLATFORM, by the id
    #: the identity provider knows them by, never a chat vendor's user id (#266 slice 6, ADR-0051
    #: D16); a chat add-on maps its users to these people itself. Empty = read-only for everyone,
    #: the safe default: anyone can ask, nobody can act until an admin is listed. Never gates
    #: prod-release/merge/deploy (ADR-0016).
    admins: list[str] = Field(default_factory=list)

    # Run the Knowledge Layer A/B on this project: each ticket is assigned an arm so BOTH run under
    # the same platform version, ticket mix and week (openfactory/knowledge/experiment.py). Without
    # it,
    # turning `knowledge_map` on gives a before/after confounded by everything that changed in
    # between — including this platform's own changes.
    #
    # An operator's instrument for a bounded window, not a mode a client is put into: it lives in
    # the registry rather than in the client's manifest, and it is off everywhere by default.
    knowledge_experiment: bool = False

    # The language this project's agents speak when they SPEAK FIRST — an announcement, a
    # diagnosis, a question nobody prompted. A reply always follows the language the person wrote
    # in, whatever this says: someone who asks in English wants an answer in English.
    #
    # A default rather than a hard setting because those two cases genuinely differ, and getting
    # either backwards is immediately visible — a hard setting answers an English question in
    # Portuguese, while no setting at all leaves proactive messages in whatever the model prefers,
    # which for most models means English at a Brazilian client.
    #
    # Applies to every human-facing role (tech-lead and product); the coding phases are untouched.
    #: ENGLISH by default (2026-08-14). `pt-BR` was the first deployment's language wearing a
    #: default's clothes; a client who speaks another one declares it and the registry carries
    #: the decision where anybody can read it.
    language: str = "en"

    # ADR-0019 — the PRODUCT MODULE (the PO/BA role that turns a conversation into a requirement),
    # opt-in per client:
    #
    #     product:
    #       docs_repo: ClientOrg/client-documentation
    #       admins: [ana]
    #
    # Its PRESENCE is what enables the module — a project without this section simply does not have
    # it, and nothing else about the factory changes. Presence rather than a boolean beside it, so
    # the module cannot be half-configured: "enabled: true" with nowhere to write requirements is a
    # state that should not be expressible.
    #
    # Deployment-level for the same reason as `harness`: which repository holds a client's
    # requirements, and who may act on them, involves credentials and isolation that the client's
    # own `.openfactory/project.yaml` has no business naming. What that file DOES declare is the
    # reverse
    # pointer (`docs_repo:`), which this must agree with — see openfactory/product/config.py.
    product: ProductConfig | None = None

    #: WHERE this project's work runs (ADR-0037). Absent → the framework's image and today's
    #: behaviour, which is every project that exists right now.
    box: BoxConfig | None = None

    #: What the operator decides about this project's previews (ADR-0050). Absent is the default
    #: policy; the MANIFEST's `preview:` block is what says a project can be previewed at all.
    preview: PreviewPolicy | None = None

    @model_validator(mode="before")
    @classmethod
    def _read_the_old_keys(cls, data):
        """The keys a vendor named, folded into where they live now (`contracts/aliases.py`).

        `deploy/registry.yaml` is gitignored and baked into the worker image, so a migration that
        required editing it would be a change no test, no CI job and no reviewer could see. The
        old keys keep loading for one minor version — the new spelling winning, the two never
        merged — and `ProjectRegistry` names each one it finds, once, so they drain away rather
        than needing a flag day."""
        return aliases.fold(data, aliases.PROJECT_KEYS)[0]

    @model_validator(mode="after")
    def _default_axes(self) -> Project:
        # forge falls back to the tracker; ci falls back to the FORGE (CI runs where
        # the code is, not where the tickets are). So Jira tracker + GitLab forge
        # yields GitLab ci — matching "repo + actions on GitLab, board on Jira".
        if self.forge is None:
            self.forge = self.tracker
        if self.ci is None:
            self.ci = self.forge
        return self
