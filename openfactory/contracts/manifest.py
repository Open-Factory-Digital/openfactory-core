"""The project manifest — `.openfactory/project.yaml`.

This is the project's *plug* into the framework contract (ADR-0001 D-1/D-3). The
framework owns the shape (which slots exist, which are required); the project
fills it in. Nothing project-specific lives in the framework — it all lives here,
versioned inside the project repo.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from openfactory.contracts.state import RiskLevel

# A typo in `.openfactory/project.yaml` must FAIL LOUD, not silently apply a default — a dropped
# `max_cost:`/`repair_attempts:` is exactly the kind of "surprise" that lets a runaway job or a
# mis-scoped merge through unnoticed. `extra="forbid"` turns any unknown key into a load error
# the moment the manifest is parsed (in the Fargate task, before any agent runs). (D-1/D-3)
_STRICT = ConfigDict(extra="forbid")
_STRICT_BY_NAME = ConfigDict(populate_by_name=True, extra="forbid")


class DocRoles(BaseModel):
    """Docs are addressed by *role*, not by location (ADR-0001 D-9).

    Each field is a glob the framework resolves inside the project repo. A project
    keeping ADRs in `decisions/` just points `constraints` there. Absent roles are
    fine (optional), but absence has a price: a stronger human gate.
    """

    model_config = _STRICT

    constraints: str | None = None  # ADRs — the constitution; always loaded, all of them
    architecture: str | None = None  # large; pulled on demand via the derived index
    guidelines: list[str] = Field(default_factory=list)  # small; the executor's manual


class ComponentDocs(BaseModel):
    model_config = _STRICT

    architecture: str | None = None


class Component(BaseModel):
    """A stack-homogeneous area of the repo (ADR-0001 D-6).

    front/back/devops are not different agents — they are different manuals +
    permissions + risk that the same worker wears depending on what the diff
    touches. IaC is just a component with a terraform stack and risk=high.
    """

    model_config = _STRICT_BY_NAME

    path: str  # glob; used to map a diff back to the components it touched
    stack: str  # references a framework preset (python/node/terraform/...)
    # YAML key is `validate:`; the attribute is `validation` to avoid shadowing
    # pydantic's BaseModel.validate.
    validation: dict[str, str | Gate] = Field(default_factory=dict, alias="validate")
    guidelines: list[str] = Field(default_factory=list)
    docs: ComponentDocs = Field(default_factory=ComponentDocs)
    risk: RiskLevel = RiskLevel.NORMAL


class Environment(BaseModel):
    """A deploy target the framework observes (ADR-0001 D-12). The pipeline deploys;
    the framework only reads status + probes health."""

    model_config = _STRICT

    #: Where a MACHINE checks: probed with a GET, and only its status code is read.
    health_url: str | None = None
    #: Where a PERSON looks: the address a human is sent to when asked to confirm the change is
    #: right. Rendered to people and never fetched.
    #:
    #: NOT `health_url`, and the distinction is the whole point (#122). A health endpoint is a
    #: probe target — `/api/v1/health`, a 200 and a JSON body — and sending somebody there to
    #: validate a feature is sending them to the wrong page. The pilot's own staging deploy has
    #: both: it smoke-tests `https://stg.example.com/api/v1/health` and the thing a person needs
    #: to open is `https://stg.example.com`.
    url: str | None = None
    #: The DEPLOYMENT ENVIRONMENT's own name at the provider (a GitHub environment, an Azure
    #: Pipelines environment) whose status is read. Not a workflow file — that was in this
    #: repository's own example for months.
    deploy_ref: str | None = None
    #: WHO confirms this stage is right. `product` means a person is asked to look at it before
    #: the change goes any further (#122).
    #:
    #: A `Literal`, NOT AN OPEN STRING — the process audit (2026-08-17) caught the first cut
    #: taking any text and comparing `== "product"` downstream, so `validate_with: Product` (a
    #: typo) silently meant "nobody is asked": the exact silent-disable this field's own card was
    #: opened to kill. The schema is strict about KEYS everywhere; a value that changes who gets
    #: asked deserves the same loud refusal.
    #:
    #: Optional, and the default is what matters more than the field: with nothing declared, the
    #: LAST pre-production stage is the one somebody is asked to confirm. A shop whose flow ends
    #: at staging declares no production at all, so before this the only validation loop in the
    #: platform — the one behind the production gate — was reachable exclusively by the projects
    #: that least needed it.
    validate_with: Literal["product"] | None = None


class PostMergeDeploy(BaseModel):
    """Configures the post-merge deploy WATCH (ADR-0005). The project's own CI runs the
    deploy (e.g. a `deploy` workflow that fires on push to main); the platform only observes
    that run on the merge commit and reports its outcome. Watching NEVER gates the floor — a
    ticket is done at merge; this runs async and can only notify. Opt-in per project."""

    model_config = _STRICT

    workflow: str  # the deploy workflow's file/name, matched via `gh run list --workflow`
    env: str = "dev"  # label for notifications ("dev deploy ok"); no behavioural effect
    #: Where a PERSON looks once this deploy is green — and the reason this field exists at all
    #: (#122). The operator asked, before his first merge: *"a deploy to staging happens, and I
    #: have not seen anywhere that picks up the staging domain so somebody can be asked to
    #: validate it"*. He was right: the outcome was reported as a CI run URL, which tells a
    #: reviewer whether the pipeline was green and nothing about whether the product is right.
    #:
    #: ON THIS OBJECT AND NOT ONLY ON `Environment`, because this is the lever most repositories
    #: can actually use. Observing an `Environment` needs the provider to RECORD a deployment —
    #: a GitHub environment, an Azure Pipelines environment — and a repository that simply
    #: deploys from a workflow records none at all (measured on the pilot's: 0 deployments, 0
    #: environments, and a working staging site). Putting the address only where the chain lives
    #: would have offered it exclusively to the shops that need it least.
    #:
    #: Empty means nobody is sent anywhere, and the message says the deploy is green WITHOUT
    #: inventing a place to look.
    url: str = ""
    # Bounded [1, 720] min: 0 would fire an instant spurious "timeout"; a week-long watch at the
    # 1-min deploy poll would itself hit Temporal's history-event ceiling (~day 3) — same class
    # of bug as the merge-watch. 12h is plenty to observe any real deploy.
    timeout_minutes: int = Field(30, ge=1, le=720)


class PreflightConfig(BaseModel):
    """The pre-Fargate sizing gate (ADR-0013 D2): an INVEST judgment on the ticket TEXT plus a
    read-only blast-radius estimate over the worker's cached checkout — BEFORE any task spin-up.
    `enabled: false` is the kill-switch (jobs run exactly as before); `code_check: false` keeps
    the cheap text layer but skips the repo exploration."""

    model_config = _STRICT

    enabled: bool = True
    code_check: bool = True


#: The manifest schema versions THIS build understands.
#:
#: `.openfactory/project.yaml` is the platform's most-used public API: the one file every client
#: writes,
#: living in the client's own repository, outside our release cycle. On publication its shape
#: becomes a compatibility commitment whether or not anybody decided to make one.
#:
#: THE COMPATIBILITY RULE, so a future change knows which side of the line it is on:
#:
#:   stays version 1   adding an OPTIONAL field · widening what a field accepts · a new component
#:                     key · a default that changes nothing a manifest already relies on
#:   needs a bump      removing or renaming a field · narrowing what one accepts · changing what
#:                     an existing field MEANS · a default whose new value changes behaviour for
#:                     a manifest that does not mention it
#:
#: `extra="forbid"` already catches a field we do not know. It cannot catch a field whose meaning
#: changed under a name we do — which is why the version exists and why an unknown one must raise
#: rather than be tolerated. Same rule as ADR-0022 for provider kinds: a wrong version does not
#: fail like a missing one, so the error names what IS supported and is actionable at load time.
SUPPORTED_MANIFEST_VERSIONS: frozenset[int] = frozenset({1})


class Gate(BaseModel):
    """One validation command and the policy around it.

    `validate:` values were bare strings, so every gate BLOCKED and every failure fed the repair
    loop. That is right for `test` and wrong for the thing C-37 exists to allow: a security or
    licence scan on a real codebase starts noisy, and a scanner wired as a blocking gate on day
    one is the first thing a client turns off — after the platform has spent agent money trying to
    "fix" a CVE in a transitive dependency it cannot fix.

    ADVISORY runs it, reports it, and stops there: it never fails the job, never blocks the merge,
    never triggers repair. The evidence still lands where a human reads it, which is the whole
    point — an advisory result nobody sees is a log, not a gate.

    Backward compatible by construction: a plain string is still a blocking gate with the default
    timeout, so no existing manifest changes meaning.
    """

    command: str
    #: report, never block, never repair. Default False — a gate that silently stopped blocking
    #: would be the worse direction of this change.
    advisory: bool = False
    #: A scan measured in minutes must not borrow the test suite's wall. None → the default.
    timeout_minutes: int | None = None


class Manifest(BaseModel):
    model_config = _STRICT_BY_NAME

    #: Schema version. Absent means 1 — every manifest in the field today omits it, and refusing
    #: those would break every existing client to gain a guarantee about the future.
    version: int = 1

    @field_validator("version")
    @classmethod
    def _version_is_supported(cls, v: int) -> int:
        if v not in SUPPORTED_MANIFEST_VERSIONS:
            known = ", ".join(str(n) for n in sorted(SUPPORTED_MANIFEST_VERSIONS))
            raise ValueError(
                f"manifest version {v} is not supported by this build — known: {known}. "
                "A manifest written for a newer platform may mean something different by a field "
                "this build already understands, so it is refused rather than guessed at."
            )
        return v
    setup: list[str] = Field(default_factory=list)  # how to install deps
    base_branch: str = "main"

    # Repo-wide validation (e.g. a repo-wide `make test` run across the whole repo).
    # Per-component validation adds to this; the framework runs the union applicable
    # to the touched components. YAML key `validate:`; attribute `validation` to
    # avoid shadowing BaseModel.validate.
    validation: dict[str, str | Gate] = Field(default_factory=dict, alias="validate")

    docs: DocRoles = Field(default_factory=DocRoles)
    components: dict[str, Component] = Field(default_factory=dict)

    # WHAT THIS PROJECT IS — the class, resolved as a cascade layer (`policy/profiles.py`).
    #
    # A PLAIN STRING AND DELIBERATELY NOT AN ENUM. `poc | legacy | greenfield | mobile` is wrong at
    # the first client with a nature nobody anticipated, which is the same reason the concept
    # taxonomy is open: every company will have its own. The core ships worked examples; a client
    # writes theirs in `.openfactory/profiles/` and that layer wins.
    #
    # ABSENT IS ORDINARY. Most projects need no profile and `None` means exactly that — it is not
    # the same fact as naming a profile that does not resolve, which is a hold (`ProfileError`),
    # because a project that believes it runs under rules the platform never applied is the one
    # failure this must not degrade into silence.
    profile: str | None = None

    # Knowledge Layer (ADR-0017 · ADR-0035 · docs/knowledge-layer.md). On every merge that changes
    # sources the platform regenerates the deterministic module map and publishes it to a dedicated
    # `openfactory-knowledge` branch in THIS project's repo (§23); each job then injects it so the
    # agent
    # LOCATES code faster and verifies against the real files (§7 — the code stays ground truth,
    # the map only says where to look).
    #
    # ON BY DEFAULT since 2026-08-02 (ADR-0035). It shipped opt-in with an A/B behind it, on
    # the rule that the layer does not advance until cost per ticket drops. It dropped. The product
    # owner: *"this has already proven very efficient… we had left it in A/B mode, but now it is
    # for real."*
    #
    # Turning it on cannot make a run worse than leaving it off, and that is a property rather than
    # a hope: the bundle is injected ONLY when its checksums prove it describes that job's own
    # checkout, and a missing, stale or orphaned bundle degrades to injecting nothing (§12) rather
    # than to an error. That freshness gate is what makes a default safe.
    #
    # `false` remains available for a project that wants it off. By hand:
    # `openfactory knowledge build|check <project>`.
    knowledge_map: bool = True

    # ADR-0019 — this repo's documentation/requirements repository, `owner/name`. A CLAIM, not an
    # authorization: the deployment's registry decides which docs repo a project may use, and a
    # claim that disagrees turns the product module OFF rather than redirecting it (anyone with
    # write access here could otherwise point it at any repository at all).
    #
    # Declared here anyway, because it answers a question the registry cannot: someone who clones
    # this repo can find its requirements without access to the factory's configuration. And since
    # both sides declare it independently, a disagreement becomes DETECTABLE instead of silent.
    docs_repo: str | None = None

    # Optional project-level tightening of permissions (never loosening — D-2).
    permissions: dict[str, object] = Field(default_factory=dict)

    # Scope-explosion threshold (ADR-0001 D-6): abort to refinement past this. Enforced in
    # `orchestrator.validation.scope_explosion`, checked against the diff right after execution —
    # before suppression-repair or review spend anything on a ticket that already needs a human's
    # judgment about SCOPE, not a fix. `None` (either field) means this project has not opted in.
    max_touched_components: int | None = None
    max_diff_lines: int | None = None

    # DEPRECATED (ADR-0013, owner decision): file/step COUNT is no longer a sizing criterion.
    # Sizing is INVEST-only (one cohesive, independent, testable outcome) — a rename or a
    # legitimately full-stack feature may touch many files and still be ONE ticket. Kept only so
    # existing project.yaml files that set them still load; nothing reads them now. Remove later.
    max_plan_files: int | None = None
    max_plan_steps: int | None = None

    # Economic ceiling per ticket (ADR-0002): the true runaway guard, independent of turn
    # mechanics. Cumulative agent spend (plan + execute + repair) past this holds the job
    # for a human. None = no ceiling.
    max_cost_usd: float | None = None

    # ADR-0014: single-agent execution. With a frontier model the plan→execute SPLIT costs a
    # handoff — the planner reads the repo, understands it, serialises a text plan (lossy), and a
    # SECOND cold agent re-reads the same files and re-derives the context. A capable model plans
    # AS it codes, in one warm context. Default False = single agent (investigate+plan+implement
    # in one pass). True = the dedicated read-only planner runs first (KEEP AGNOSTIC: a client on
    # a weaker model that flails without an explicit plan sets this True). Also requires the
    # adapter to expose plan(); an adapter without it is single-agent regardless.
    planner_stage: bool = False

    # ADR-0014: review posture. "advisory" (default) — the review still runs and its findings are
    # POSTED to the PR as a comment, but it NEVER triggers the repair loop, NEVER requests changes,
    # and NEVER blocks auto-merge. The real quality floor is deterministic (tests · lint · type ·
    # security · CI) plus the executor's own TDD; an LLM reviewing LLM output is a fuzzy, expensive
    # layer, so it informs a human instead of gating autonomously. "blocking" — the old behaviour
    # (bounded review-repair + request-changes + gates auto-merge), for teams that want it or a
    # weaker model. "off" — skip the review entirely.
    review_mode: Literal["advisory", "blocking", "off"] = "advisory"

    # Bounded review-repair (ADR-0006): under review_mode="blocking", on a REJECTED review with
    # actionable findings, feed them back to the executor for this many autonomous fix attempts (+
    # an independent re-review) before handing the PR to a human. Default 1 — the review is
    # subjective, so more rounds risk executor<->reviewer ping-pong. 0 disables. Ignored unless
    # review_mode="blocking".
    review_repair_max_attempts: int = Field(1, ge=0, le=10)

    # Suppression-repair (ADR-0011): when a diff ADDS a gate-suppression (# pragma: no cover /
    # noqa / type: ignore / nosec), the executor gets this many autonomous passes to RESOLVE it
    # in the sandbox — remove the ones it can make properly testable, keep+justify the genuinely
    # untestable wiring — before it ever reaches a human. Default 1; 0 disables (straight to the
    # old human-review behaviour). A coverage pragma that survives is then vetted by the reviewer.
    suppression_repair_max_attempts: int = Field(1, ge=0, le=10)

    # ADR-0013: pre-Fargate sizing gate + effort governance + autonomous recovery.
    preflight: PreflightConfig = Field(default_factory=PreflightConfig)
    # The ticket-wide effort budget (cumulative agent turns across executor + repairs +
    # recoveries + resumes). THIS is the size/effort governor — the per-invocation turn cap is
    # only an anti-runaway backstop. On a subscription, turns are the honest effort currency.
    effort_budget_turns: int = Field(400, ge=50, le=5000)
    # Autonomous stuck-recovery ladder (D5): continue-session, then a fresh recovery pass.
    # 0 disables (a stop goes straight to a resumable hold).
    recovery_max_attempts: int = Field(2, ge=0, le=5)
    # After an autonomous split (D3), send the children straight to TO-DO in order (True, the
    # lights-out flow — single-line strict runs them one at a time, each on the prior's merge)
    # or leave them in Backlog for a human to sequence (False).
    split_to_todo: bool = True

    # On-demand e2e (ADR-0008): a ticket carrying `e2e_label` is NOT implemented — the platform
    # just DISPATCHES `e2e_workflow` (a workflow_dispatch GitHub Actions workflow), watches it,
    # and reports pass/fail on the ticket. Lets e2e leave the every-PR CI (heavy) and run
    # deliberately via a labelled ticket. None workflow → the e2e-ticket path is off.
    e2e_label: str = "e2e"
    e2e_workflow: str | None = None  # e.g. "e2e.yml"

    # PR merge posture (ADR-0001 D-12). Default is human-on-PR: the bot opens the PR,
    # posts the review, requests reviewers, and stops. `auto` lets the bot merge when
    # the review is not rejected, all validations pass, and no touched component is
    # high risk.
    merge_policy: Literal["human", "auto"] = "human"
    reviewers: list[str] = Field(default_factory=list)  # requested on the human path

    # Bounded repair loop (ADR-0001 D-12): on failed validation the agent gets up to
    # this many fix attempts before the job fails. 0 disables repair.
    repair_max_attempts: int = Field(2, ge=0, le=10)

    # Post-merge deploy WATCH (ADR-0005). When the project deploys itself via its own CI
    # (e.g. a GitHub Actions `deploy` workflow on push to main), the platform OBSERVES that
    # deploy and NOTIFIES its outcome — it never blocks: the merge already frees the floor for
    # the next ticket, and the watch runs async (an abandoned child workflow). None = off.
    post_merge_deploy: PostMergeDeploy | None = None

    # Promotion to environments (ADR-0001 D-12). The framework triggers merge/tag and
    # observes; the pipeline executes. Prod is human-gated by default.
    environments: dict[str, Environment] = Field(default_factory=dict)
    #: The promotion chain, DECLARED BY THE CLIENT, in order — `promote: [dev, qa, prod]` (#109).
    #: The LAST entry is production: the human gate sits before it, always, whatever it is called
    #: — which is what lets a regulated client's manifest agree with their change-management
    #: document instead of renaming their homologação to `staging` to satisfy ours. Empty (the
    #: default) derives the chain from the two fixed names, exactly as the tail always behaved:
    #: `staging` observed if declared, `prod` gated if declared — the default is the product.
    promote: list[str] = Field(default_factory=list)
    prod_tag_prefix: str = "v"  # tag = <prefix><version>; triggers the prod pipeline
    # Prod is human-authorized, always — only these logins may approve a release
    # (they also authenticate with a password; see openfactory/approvals.py). No auto-to-prod.
    prod_approvers: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _the_chain_names_only_declared_environments(self) -> Manifest:
        """A `promote:` step with no `environments:` entry is a mistake, not configuration.

        REFUSED, unlike the inert-environment WARNING one door over, and the asymmetry is earned:
        an extra environment nobody watches degrades observability; a chain step that names
        nothing would have the tail 'verify' a stage with no deploy ref and no health URL — a
        vacuous green in the exact place a regulated client put the stage BECAUSE it must be
        checked. Duplicates are refused for the same reason a board refuses two same-named
        columns: the order IS the meaning."""
        undeclared = [n for n in self.promote if n not in self.environments]
        if undeclared:
            raise ValueError(
                f"promote: names {undeclared}, but environments: declares no such entry — every "
                f"step of the chain needs the environment it promotes into (declared: "
                f"{sorted(self.environments) or 'none'})")
        dupes = sorted({n for n in self.promote if self.promote.count(n) > 1})
        if dupes:
            raise ValueError(
                f"promote: lists {dupes} more than once — the chain is an order, and a stage "
                f"cannot come both before and after itself")
        return self

    def promotion_chain(self) -> tuple[list[str], str | None]:
        """`(stages_to_observe_in_order, production_or_None)` — the one answer the tail walks.

        DECLARED chain: everything before the last is observed in order; the last IS production,
        by definition (#109 — *"portão humano antes do último"*). A client with environments but
        no production simply does not declare `promote:`.

        DERIVED (no `promote:`): the two fixed names, exactly the tail's historical shape —
        `staging` observed when declared, `prod` gated when declared, either alone still meaning
        what it always meant. A staging-only project finishes at merge with no gate to nowhere;
        a prod-only project gates immediately."""
        if self.promote:
            return list(self.promote[:-1]), self.promote[-1]
        stages = ["staging"] if "staging" in self.environments else []
        return stages, ("prod" if "prod" in self.environments else None)

    def where_a_person_looks(self, stage: str) -> str:
        """The address a HUMAN opens to check this stage, or "" when the project declared none.

        ONE RESOLVER, because the address has three possible homes and every reader that picked
        one for itself would disagree with the others (#122):

            environments[stage].url    the declaration, per stage — what a chain of `dev, qa,
                                       producao` needs, since each is a different place to look;
            post_merge_deploy.url      for the ONE stage that watch is about. It exists because
                                       most repositories record no deployment at all — they just
                                       deploy from a workflow — so the `environments:` route is
                                       offered exclusively to shops that need it least.

        `ProductConfig.staging_url` is the third and is NOT here on purpose: it lives on the
        deployment's registry rather than on the client's manifest, cannot express more than one
        stage, and is deprecated. The one caller that still reads it does so as a fallback, says
        so in its log, and only after asking this.

        NEVER `health_url`. A probe target is where a machine sends a GET and reads a status code;
        sending a person to `/api/v1/health` to confirm a feature is right is sending them to the
        wrong page. Both exist on the pilot's own staging deploy and they are different strings.
        """
        env = self.environments.get(stage)
        declared = str(getattr(env, "url", "") or "") if env else ""
        if declared:
            return declared
        watch = self.post_merge_deploy
        if watch and str(getattr(watch, "env", "") or "") == stage:
            return str(getattr(watch, "url", "") or "")
        return ""

    def stage_a_person_confirms(self) -> str:
        """Which stage somebody is asked to look at before the change goes further, or "".

        DECLARED WHEN IT MATTERS, DERIVED WHEN IT DOES NOT. `validate_with: product` on an
        environment says "a person confirms this one"; with nothing declared it is the LAST
        pre-production stage, which is what every shop means by "the test environment" and is the
        stage a production gate already implicitly asks about.

        THE POINT OF DERIVING IT is the case the card was opened for: a shop whose flow ENDS at
        staging declares no production, so the only validation loop that existed — the one behind
        the production gate — was unreachable for exactly the projects that most needed somebody
        to look. A stage nobody is gating still deserves an ask."""
        stages, production = self.promotion_chain()
        chosen = [name for name in stages
                  if str(getattr(self.environments.get(name), "validate_with", "") or "")
                  == "product"]
        if chosen:
            return chosen[-1]
        if stages:
            return stages[-1]
        # THE DERIVED CHAIN KNOWS TWO NAMES AND A COMPANY IS NOT OBLIGED TO USE THEM. With no
        # `promote:`, `promotion_chain` observes `staging` and gates `prod` — so a shop whose only
        # environment is called `qa`, or `homologacao`, yields no stages at all, and asking off the
        # chain alone would have left them exactly where this card found them: with a real test
        # environment and nobody ever sent to it. *"other companies may have another one, and I
        # have not seen anywhere this would work."*
        #
        # ONLY THE ASK IS WIDENED, never the observation: this decides who is invited to look, and
        # what the platform CHECKS is still `promotion_chain`'s answer. Production is excluded —
        # it has its own human gate and is nobody's staging.
        declared = [name for name in self.environments if name != production]
        if declared:
            return declared[-1]
        watch = self.post_merge_deploy
        return str(getattr(watch, "env", "") or "") if watch else ""

    @model_validator(mode="after")
    def _inherit_the_deployment_floor(self) -> Manifest:
        """Merge the deployment's default gates into repo-wide `validate:` for every role this
        file leaves undeclared (`org_defaults/floor.yaml`).

        HERE, AND NOT IN THE LOADER, FOR ONE MEASURED REASON. The floor is inspected by
        `policy/conformance._effective_validation` and EXECUTED by
        `orchestrator/validation.applicable_validations` — and those two functions share exactly
        one input: this object's `validation` mapping. A default installed anywhere else satisfies
        one of them and not the other, which is the failure this platform has shipped ~21 times:
        conformance reporting a floor that is met while nothing runs, or a gate running that the
        floor cannot see. Merging into the model puts it in the one place both must read, along
        with `box_prove.gate_commands`/`_hash_commands`, so the proof covers the gate a job will
        actually run rather than a shorter list.

        REPO-WIDE IS THE POINT, not a shortcut. `applicable_validations` builds its map as preset
        (for touched components) → repo-wide → per-component overrides; a value merged into a
        component's stack preset would only run when a diff happened to reach that component,
        which is a coverage rule, not a floor. Repo-wide runs on every diff there is.

        THE PROJECT ALWAYS WINS. A role the file declares is left exactly as written — the merge
        only ever adds keys that are absent — so this can never change what an existing manifest
        means for a role it has an opinion about. That is also the entire override protocol: to
        replace a deployment default, declare that role.

        WHY `model_fields_set` IS PUT BACK. `declared_keys()` one method below exists to tell
        "the client wrote `validate:`" from "the client never wrote it", because **read, nothing
        there** and **never written** are different facts and `doctor`/`env check` report them
        differently. Assigning to a field marks it as set, so merging a default would make every
        manifest in the fleet claim it had declared `validate:` — the inherited gate would erase
        the very evidence that it was inherited. So the flag is restored to what the FILE said.
        """
        # A LATE IMPORT, not a style choice: `openfactory.policy.__init__` imports `conformance`,
        # which
        # imports `openfactory.contracts` — importing it at module scope here is a cycle that fails
        # at
        # interpreter start. The read behind it is cached for the process.
        from openfactory.orchestrator.validation import (
            as_gate,  # lazy pkg; pure functions only (C-21)
        )
        from openfactory.policy.presets import load_preset, org_default_validation

        defaults = org_default_validation()
        if not defaults:
            # None (unreadable) and {} (nothing declared) both mean nothing to merge. They are NOT
            # the same event, and they are told apart where it matters: `org_default_validation`
            # logs OPENFACTORY_FLOOR_UNREADABLE for the first and `policy/conformance.check` reports
            # it as
            # an error against the INSTALL. Here the behaviour is identical and correct — inherit
            # nothing, and let `floor_reason` refuse a project with no `security` of its own,
            # exactly as it did before this file existed.
            return self
        inherited = {role: gate for role, gate in defaults.items() if role not in self.validation}
        if not inherited:
            return self

        # THE INVARIANT THIS BLOCK EXISTS TO KEEP, and it is the whole reason the loop below is not
        # one line: **inheriting a floor gate never REMOVES a command that would already have run.**
        #
        # Without it the merge is a silent downgrade. `applicable_validations` resolves preset →
        # repo-wide → per-component, so a role placed repo-wide beats the same role in a touched
        # component's stack preset: a project with `stack: python` would have lost the preset's
        # `bandit`, and `box_prove.component_gates` — which skips any gate the repo-wide map
        # already carries — would have stopped proving it exists at all. The client asked for
        # neither, and nothing would have said so.
        #
        # So before the default goes repo-wide, the command that WOULD have run for each component
        # is pinned to that component, where per-component precedence keeps it winning for its own
        # diffs. The floor then covers exactly the gap: diffs that reach no declared component,
        # which is where a repo-wide `security` was missing in the first place.
        for role in inherited:
            for comp in self.components.values():
                if role in comp.validation:
                    continue  # already explicit — the component's own value was always going to win
                preset_gate = load_preset(comp.stack).get("validate", {}).get(role)
                if preset_gate is not None:
                    # THE PRESET'S VALUE VERBATIM, not `as_gate(...)` of it, and a guard caught the
                    # difference. `box_prove.component_gates` returns whatever this map holds and
                    # is annotated `dict[str, str]`; its caller does not normalise (#99 §6.7), so
                    # converting the `python` preset's plain `"bandit -r . -ll -q"` into a `Gate`
                    # here would have handed `run_in_box` an object whose repr is not a command —
                    # a new instance of a live defect, introduced by the fix for another one.
                    # Verbatim also makes the invariant literal: consumers see the same object
                    # they saw before anything was inherited.
                    comp.validation[role] = preset_gate

        declared_in_file = "validation" in self.model_fields_set
        # A MAPPING BECOMES A `Gate` via the one function that knows both shapes. This value never
        # passes through pydantic validation — `validate_assignment` is off, so whatever is put
        # here is what every consumer gets — and a consumer reading `.advisory` off a raw dict
        # would get an AttributeError at the worst moment: inside a job, deciding whether to block.
        self.validation = {**self.validation,
                           **{role: as_gate(gate) for role, gate in inherited.items()}}
        if not declared_in_file:
            self.__pydantic_fields_set__.discard("validation")
        return self

    @property
    def declared_base_branch(self) -> str:
        """The base branch the FILE names, or `""` when it names none.

        `base_branch` has the schema default `"main"`, so `manifest.base_branch` is byte-identical
        whether a client wrote `base_branch: main`, wrote nothing, or created the file with
        `touch`. That is the three-answers collapse this contract's `declared_keys` was written
        about — and it cost a real defect: two callers re-synced their checkout whenever
        `manifest.base_branch` differed from the branch they had landed on, read the DEFAULT as a
        declaration, and re-cloned a `master` client at the literal `main`. The clone names nothing
        there, so the cache was deleted and the round degraded — on every ticket, hourly, having
        just resolved the right branch one line above.

        `""` IS THE USEFUL ANSWER, not a failure: it means "I have no opinion, keep what you have",
        which is exactly what a caller that already holds a correct checkout needs to hear.
        """
        return self.base_branch if "base_branch" in self.declared_keys() else ""

    def declared_keys(self) -> tuple[str, ...]:
        """The keys the FILE actually set, in the file's own vocabulary — sorted.

        THIRTY-ONE FIELDS AND NOT ONE REQUIRED, so `Manifest()` is a fully legal object that says
        nothing at all: it loads, `validate:` is `{}`, and `all([])` is True — which is how a
        project could reach auto-merge on a quality floor that was the empty set (#102, and the
        `all([])` half is `tests/test_the_floor_is_enforced_where_the_money_is.py`). Nothing on the
        model can tell those two worlds apart. `self.validation == {}` is byte-identical whether
        the client wrote `validate: {}` deliberately, wrote nothing, or created the file with
        `touch`. **Read, nothing there** and **never written** are different facts, and a caller
        that wants to say so out loud has to ask a question the field values cannot answer.

        THE FIELDS ARE STAYING OPTIONAL, and this method is the reason it costs nothing to keep
        them that way. Making them required was tried on the neighbouring contract and reverted —
        `contracts/project.py` carries the note: `Project.tracker` has a `default_factory` that
        several hundred tests inherit, and that many mechanical edits is that many chances to
        quietly change what a test asserts. The protection belongs at the seams that spend money
        (`policy/conformance.py::floor_reason`, before an agent pass) and at the seam a human runs
        before the first ticket (`doctor.py::_manifest`) — and a seam can only refuse what it can
        SEE. This is what it sees.

        WHY `model_fields_set` AND NOT A DIFF AGAINST `Manifest()`. `loader.load_manifest` builds
        this with `Manifest(**data)`, so the set is exactly the YAML mapping's own keys. Diffing
        values against a fresh default instead cannot tell `merge_policy: human`, typed on purpose
        by someone who considered the choice, from the default nobody thought about — the very
        distinction this exists to make.

        The names are mapped back through the aliases because a human is going to go looking for
        them in their own file: the field is `validation`, the key they wrote and must find is
        `validate`. (A manifest built by `model_copy(update=...)` would also list the updated keys.
        No caller on the load path does that; if one appears, it is declaring those keys as far as
        this method is concerned, which is the honest reading anyway.)
        """
        fields = type(self).model_fields
        return tuple(sorted(
            (fields[name].alias or name) if name in fields else name
            for name in self.model_fields_set
        ))
