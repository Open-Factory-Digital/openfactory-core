# Deployment configuration — every knob of a running installation

> **Not the one you want first.** If you are setting up a project, read
> [`reference/configuration.md`](reference/configuration.md) — it explains the three places
> configuration lives (the manifest, the registry, the environment) and who owns each. THIS file is
> the operator's reference for a deployment that already exists: infrastructure, parameters,
> rotation, and the optional modules.

> **It drives `infra/`, which is not in this tree.** That directory and the deployment it stands
> up ship with the `openfactory-aws` **add-on package** — one cloud realisation, never the
> platform ([STATUS.md](STATUS.md) lists what leaves with it). Every `infra/…` path below is a
> path inside that package's checkout, and every parameter store, region and console name with
> it; a deployment on your own machines has none of them and configures itself through
> `.env.compose` and the registry.

Every knob of the deployed system and how to change it. The examples use `eu-west-2`; use your
own region. All AWS commands assume your credentials are exported. Nothing here is a console
click — the durable config is IaC (`infra/terraform/`) + a few SSM parameters. See also
the `openfactory-aws` package's own `docs/runbook.md` (incident response on that deployment) and
[`glossary.md`](glossary.md).

> **`SSM_PREFIX` — the parameter namespace you own.** Every secret below lives at
> `<SSM_PREFIX>/<name>`. It is terraform's `ssm_prefix` variable and, for `infra/deploy.sh`, the
> `OPENFACTORY_SSM_PREFIX` environment variable; both default to `/openfactory`. Nothing here names a namespace
> belonging to somebody else — you create these parameters in your own account. Export it once and
> every command on this page copy-pastes:
>
> ```bash
> export SSM_PREFIX="/openfactory"   # the default; or whatever namespace your deployment owns
> ```

---

## 1. Agent credential pool (token failover)

The coding agent's credentials live in **SSM Parameter Store** (SecureString, free) as a
**JSON array** — so one exhausted or revoked token fails over to the next before the job
pauses (see [`autonomous-flow.md`](autonomous-flow.md)).

- **Parameter:** `$SSM_PREFIX/agent-tokens`
- **Format:**
  ```json
  [
    {"id": "primary", "type": "subscription", "token": "sk-ant-oat01-..."},
    {"id": "backup",  "type": "subscription", "token": "sk-ant-oat01-..."}
  ]
  ```
  - `type`: `subscription` (sets `CLAUDE_CODE_OAUTH_TOKEN`) or `api` (sets `ANTHROPIC_API_KEY`).
  - Order matters: the agent tries them top-down, rotating on a rate-limit / auth stop.
    Only when **all** are spent does the job pause (30-min durable backoff).
- **Set / update the pool:**
  ```bash
  POOL='[{"id":"primary","type":"subscription","token":"<TOKEN-A>"},
         {"id":"backup","type":"subscription","token":"<TOKEN-B>"}]'
  aws ssm put-parameter --region eu-west-2 --name "$SSM_PREFIX/agent-tokens" \
      --type SecureString --value "$POOL" --overwrite
  ```
  Picked up **per job launch** — no redeploy. A single token is fine (`[{...one...}]`);
  add more only when you want failover / more throughput.
- **Get a subscription token:** `claude setup-token` (on a machine logged into the plan).
- **No pool set?** The agent falls back to the single `$SSM_PREFIX/claude-oauth-token` (§2).

---

## 2. Secrets

All secrets are **SSM Parameter Store SecureString** (free; the platform moved off Secrets
Manager, which charges $0.40/secret/mo and none of its rotation is used here). ECS injects them
into the worker / sandbox / panel at task start via the execution role.

| Parameter | What it is | Rotate when |
|---|---|---|
| `$SSM_PREFIX/agent-tokens` | the agent token **pool** (§1) | a token is revoked / you add capacity |
| `$SSM_PREFIX/claude-oauth-token` | single Claude token (fallback) | ~1y, or on revoke |
| `$SSM_PREFIX/temporal-api-key` | Temporal Cloud API key | **~90 days** (Cloud keys expire) |
| `$SSM_PREFIX/bot-app-private-key` | GitHub App private key (PEM) | on GitHub App key rotation |

**Set / rotate any of them:**
```bash
aws ssm put-parameter --region eu-west-2 --name "$SSM_PREFIX/<name>" \
    --type SecureString --value "<value>" --overwrite
# PEM from a file:
aws ssm put-parameter --region eu-west-2 --name "$SSM_PREFIX/bot-app-private-key" \
    --type SecureString --value "$(cat key.pem)" --overwrite
```
After rotating a secret the **worker/panel materialize it at startup**, so force a fresh
task to pick it up:
```bash
aws ecs update-service --cluster openfactory-sandbox --service openfactory-worker --force-new-deployment
aws ecs update-service --cluster openfactory-sandbox --service openfactory-panel  --force-new-deployment
```
Sandbox (job) tasks read the current value per launch — no action needed.

---

## 3. The panel (deployed)

The panel runs on **AWS App Runner** (`openfactory-panel`) — a managed container host that gives
a **stable HTTPS URL** out of the box, so a link shared with a partner never breaks. It's
gated by a **token**, not by IP (right for dynamic IPs + sharing). App Runner can't run
ARM, so the panel uses a dedicated **amd64** build of the worker image (worker/jobs stay
ARM/Graviton). Defined in `infra/terraform/panel_apprunner.tf`, OFF by default.

- **Build the amd64 panel image + deploy:**
  ```bash
  SHA=$(git rev-parse --short HEAD); ECR=<your-aws-account-id>.dkr.ecr.eu-west-2.amazonaws.com
  aws ecr get-login-password --region eu-west-2 | docker login --username AWS --password-stdin "$ECR"
  docker build --platform linux/amd64 --build-arg BASE_PLATFORM=linux/amd64 --provenance=false \
      -f docker/worker.Dockerfile -t "$ECR/openfactory-worker:${SHA}-amd64" .
  docker push "$ECR/openfactory-worker:${SHA}-amd64"

  cd infra/terraform
  export TF_VAR_panel_apprunner_image_tag="${SHA}-amd64"
  export TF_VAR_panel_token="$(python3 -c 'import secrets;print(secrets.token_urlsafe(24))')"
  terraform apply -var image_tag=<current-worker-sha>       # image_tag = the ARM worker tag
  echo "panel token: $TF_VAR_panel_token"                   # keep it — it's the access key
  terraform output -raw panel_apprunner_url                 # → https://xxxx.eu-west-2.awsapprunner.com
  ```
  - `panel_token` → `OPENFACTORY_PANEL_TOKEN`. **All `/api/*` routes require it** (reads too); the
    HTML shell is open but useless without it. Sent as a Bearer header (fetch) or a
    same-origin cookie / `?token=` (SSE). Share the **URL + this token** with viewers.
  - **`OPENFACTORY_PANEL_TOKENS` — one secret per person (C-26).** Prefer this: with the shared token
    alone, everybody holding it is the same person, so *who approved that production release* has
    no answer. Rows are `token:id[:display]`, comma-separated:

    ```
    OPENFACTORY_PANEL_TOKENS="s3cret-a:ana:Ana Lima,s3cret-b:leo:Leo Martins"
    ```

    Every action's audit line then names the person instead of the word `panel`. The shared token
    keeps working alongside it (a caller presenting it is recorded as `anonymous`, and one
    `OPENFACTORY_IDENTITY_ANONYMOUS` log line says so), so a deployment can migrate without an outage —
    and **either variable alone closes the panel**. With *neither* set the panel is open, which is
    the local-development posture and must not be the production one.
  - **`OPENFACTORY_PRODUCT_TOKENS` / `OPENFACTORY_PRODUCT_TOKEN` — a credential that is NOT an operator's.**
    Same two shapes as above, for somebody who writes requirements and does not run the floor —
    a business analyst, typically. A caller presenting one may use the five product actions
    (`product_status`, `product_ask`, `product_propose`, `product_accept`, `product_drop`) and is
    refused every other row **by name**: `merge`, `skip`, the production-release gate.

    ```
    OPENFACTORY_PRODUCT_TOKENS="s3cret-c:bia:Bia Rocha"
    ```

    This is a different question from `admin`, and both answers are needed. The holder *is* an
    admin of the product area — accepting a requirement is the most consequential act there — and
    still cannot land a pull request. Before these existed the only way to let a BA propose a
    requirement was to hand over the panel token, which also handed over the merge button.

    A secret configured in **both** a panel variable and a product one resolves to the **product**
    credential: a copy-paste mistake must not be able to widen a BA into an operator. And these
    variables **count as configuration** — a deployment that sets only these is closed, not open.
  - `OPENFACTORY_IDENTITY` names the identity provider; `local` (the default) is the variables above.
    OIDC/SAML/EntraID are add-ons registered as `identity.<kind>` in the `openfactory.adapters`
    entry-point group (`openfactory/identity/registry.py` consults it), not a second gate. A
    provider that asserts groups grants a scope by naming it (`product`); groups it does not
    recognise are ignored rather than treated as areas.
  - The URL is **stable** — it doesn't change on redeploy/restart.
- **Update the panel after code changes:** rebuild the amd64 image with a new tag and
  re-apply with the new `TF_VAR_panel_apprunner_image_tag` (auto-deploy is off, so the tag
  change is what rolls it).
- **Turn OFF:** `unset TF_VAR_panel_apprunner_image_tag` → `terraform apply` → the service
  is destroyed.
- **Cost:** ~$5–8/mo (0.25 vCPU / 0.5 GB; active vCPU billed only while someone's viewing).
- **Note:** an older Fargate-based panel (`panel_service.tf`, gated by `panel_allowed_cidr`)
  is kept OFF as a fallback; App Runner is the deployed one.

---

## 4. Prod-release approvers (panel)

Only relevant when a project promotes to prod. Approvers authenticate the durable
approval signal.
```bash
export TF_VAR_prod_approvers="alice,bob"   # comma-separated logins → OPENFACTORY_PROD_APPROVERS
```
Locally: `openfactory approver add <login>` (password prompt; salted-KDF stored).

---

## 5. Projects

A project is **data, not code**. Two places, both committed:

1. **`deploy/registry.yaml`** (baked into the worker image) — the platform's list of
   projects: name, repo, board owner/number, forge/tracker.
2. **`.openfactory/project.yaml`** in *that* project's repo — its gates, validation commands,
   reviewers, environments, and `merge_policy`.

**Add a project:** edit both, then `infra/deploy.sh` (rebuilds the image with the new
registry). Locally you can also register via the panel's **New project** or
`openfactory project add ...`.

Key `.openfactory/project.yaml` fields. The manifest is **strict** — an unknown key (a typo like
`max_cost:`) fails the manifest load, it is never silently ignored:
```yaml
merge_policy: auto        # auto-merge green + approved PRs; or `human`
environments: {}          # map of name → target; e.g. {staging: {...}, prod: {...}}. Empty → stop at the PR.
# NOTE: the durable merge-wait (14d) and prod-approval window (3d) are workflow-level
# defaults, NOT manifest fields — do not set them here.

# Cost ceiling (ADR-0002). Opt-in (unset → off).
# max_cost_usd: 8.0       # per-token (API) billing only — see note below

# DEPRECATED — `max_plan_files` and `max_plan_steps` are still ACCEPTED by the manifest and are
# read by NOTHING (ADR-0013: sizing is INVEST-only — a rename or a legitimately full-stack
# feature may touch many files and still be one ticket). They were documented here as a live
# blast-radius gate, so a project could set them, load cleanly, and run with no ceiling at all
# while believing it had one. The loader now says so out loud when a manifest declares them.
# Use `max_cost_usd` for a real ceiling.

# Bounded review-repair (ADR-0006). On a REJECTED review with actionable findings, the
# executor gets this many autonomous fix attempts (+ an independent re-review) before the PR
# is handed to a human. Default 1 (the review is subjective — more rounds risk ping-pong);
# 0 disables (straight to human). Tune per project.
review_repair_max_attempts: 1

# On-demand e2e (ADR-0008). A ticket with the `e2e_label` isn't implemented — the platform
# DISPATCHES this workflow (a workflow_dispatch GitHub Actions workflow), watches it, and
# reports pass/fail on the ticket. Lets e2e leave the heavy every-PR CI. Unset workflow → off.
e2e_workflow: e2e.yml     # the workflow to dispatch (gh workflow run)
e2e_label: e2e            # the board/issue label that routes a ticket to "just run e2e"

# Post-merge deploy WATCH (ADR-0005). Opt-in; unset → no watch. After the bot merges to
# main, the repo's OWN CI deploys; the platform observes that run on the merge commit and
# notifies its outcome. It NEVER blocks — the merge already freed the floor.
post_merge_deploy:
  workflow: deploy.yml    # the deploy workflow to observe (gh run list --workflow)
  env: dev                # label for the notification ("dev deploy ok")
  timeout_minutes: 30     # give up watching after this → notify a timeout, never hang
```

> **`review_repair_max_attempts` — react to a rejection, once (ADR-0006).** A rejected review
> with concrete findings gets one bounded autonomous fix + a fresh re-review before parking for
> a human, so the common case (a fixable rejection) self-heals and the floor-at-merge queue
> keeps flowing. The cap is the anti-ping-pong mechanism; raise it only if usage shows it helps.
>
> **It requires `review_mode: blocking`, and the default is `advisory`.** Under `advisory` the
> review is reported and never gates, so a rejection has nothing to react to and this loop never
> runs — on default settings, no ticket has ever self-healed from a rejected review. Documenting
> the attempt count without the mode that reaches it described a behaviour no default deployment
> has.

> **`e2e_workflow` — deliberate e2e, not every-PR (ADR-0008).** e2e is heavy, so it comes off
> the PR CI and runs when you drop an `e2e`-labelled ticket: the platform dispatches the
> workflow, watches it, and comments pass/fail on the ticket (DONE / ON_HOLD). Pair it with a
> `workflow_dispatch` e2e workflow in the repo and dropping e2e from the required checks.

> **Why these matter (ADR-0002 → superseded on sizing by ADR-0013).** Sizing now happens
> BEFORE any Fargate: the worker's pre-flight gate (`preflight: {enabled, code_check}`)
> judges the ticket text (INVEST) and the real blast radius over a cached checkout — an
> oversized ticket is SPLIT autonomously into `Plan Na/Nb` children (Backlog + notify), an
> unsizable one parks with questions. The in-run plan gate remains as a second net during
> the transition. Effort is governed by the TICKET-wide `effort_budget_turns` (default
> **400**, cumulative across executor + repairs + recoveries + resumes); a stop mid-work
> triggers the autonomous recovery ladder (`recovery_max_attempts`, default **2**:
> continue-session, then a fresh recovery pass) and ANY stop preserves the partial work
> (resumable hold). The per-invocation turn cap is only a runaway disjuntor (default
> **200**, tune with `OPENFACTORY_MAX_TURNS`) — never a task-size limit.
>
> **`max_cost_usd` is opt-in and only meaningful under per-token (API) billing.** On a
> Claude **subscription** the reported cost is notional, so leave it unset — the sizing gate
> and the turn cap are the runaway guards. `myapp` (subscription) leaves it unset.
>
> **`post_merge_deploy` observes, it never blocks (ADR-0005).** When the repo deploys itself
> on push to main, the platform spawns an *abandoned* durable child at merge that polls the
> deploy run on the merge commit and notifies success / failure / timeout. The job itself
> completes at merge, so the floor is freed for the next ticket immediately — the watch is
> off the critical path. Leave it unset for repos with no self-deploy (or no dev to watch).

### Project knowledge — what the planner & executor read

Process (plan → TDD) is framework-wide (§10); **the project's own architecture,
constraints, and conventions live in the project's repo** and are declared under `docs:`
in `.openfactory/project.yaml`. `build_context` assembles them into the `AgentContext` that
**both the planner and the executor** receive — so the planner plans *respecting* the
architecture and the executor implements *following* it. Three tiers, by hardness/size:

```yaml
docs:
  constraints:  docs/adr/**            # the CONSTITUTION — hard rules (ADRs).
                                       #   Loaded IN FULL, always, into every prompt.
  guidelines:                          # HOUSE RULES the agent can't guess. Inlined.
    - .openfactory/guidelines/execution.md    #   e.g. "100% coverage enforced", "reserve the
                                       #   migration number", "i18n strings in 4 bundles"
  architecture: docs/architecture/**   # the BIG docs. Turned into a derived INDEX (path
                                       #   + summary); the agent reads the full doc ON
                                       #   DEMAND when a ticket touches that area.
```

| Tier | For | How it reaches the agent | Example |
|---|---|---|---|
| **constraints** | inviolable rules | full text, every prompt | "money is Decimal", "writes emit an event" |
| **guidelines** | house rules, small | inlined in the prompt | "reads go through the cache layer", "100% coverage" |
| **architecture** | large design docs | an index; read in full on demand | "docs/architecture/realtime-events.md — the WS push topology" |

Rules of thumb: a rule that must **never** be broken → an **ADR** (constraint). Something
the agent **can't guess and CI enforces** → a **guideline** (keep it tight — it's in
every prompt). A subsystem's design the agent should **read when relevant** → an
**architecture** doc (can be long — it's only pulled when the diff touches that area).
This keeps prompts small while the full knowledge base stays reachable.

#### `knowledge_map` — the generated module map (opt-in, OFF by default)

The three tiers above are HAND-WRITTEN by the project. A fourth input is GENERATED: a
deterministic map of "where things live" (ADR-0017, `docs/knowledge-layer.md`).

```yaml
knowledge_map: true      # default false — nothing is generated, fetched or injected
```

With it on, the platform regenerates the map after every merge that changes sources and
publishes it into the project's **context repository**, at `.okf/repos/<owner>--<name>/` —
never into the project's own repo (that requires `product.docs_repo` to be set; see
`openfactory onboard`). Each job then fetches that map and injects it — **but only if the
checksums prove it still describes the job's own checkout**. A missing, stale, or inconsistent map
injects nothing and the agent searches the code as before, so turning this on cannot make a job
worse than not having it.

Leave it off unless you are measuring: the flag exists to be A/B'd on the cost dashboard, and
the layer does not advance until cost/ticket actually drops. Build a map by hand any time with
`openfactory knowledge build <project>` / inspect it with `openfactory knowledge check <project>`.

---

## 6. The autonomous trigger (poller)

The board scan runs as a **Temporal Schedule**. Create / update it (idempotent):
```bash
python -m openfactory.runtime.temporal.schedule --every-minutes 3 --sandbox fargate
```
Every tick scans each project's **TO-DO** column and starts a job per card. Overlap
policy SKIP + a 2-min per-poll timeout, so a stuck poll never blocks the next. Pause it in
the Temporal Cloud UI (Schedules → `openfactory-poller`) to halt pickup without stopping in-flight
jobs.

---

## 7. Temporal Cloud connection

Set on the worker/panel (Terraform vars + task env) and in local `.env`:
```
TEMPORAL_ENDPOINT=<namespace>.tmprl.cloud:7233
TEMPORAL_NAMESPACE=<namespace>
TEMPORAL_API_KEY=<from $SSM_PREFIX/temporal-api-key>
```
The panel's **Engine ↗** deep-links resolve automatically: a `*.tmprl.cloud` endpoint →
the Cloud console; anything else → the local dev-server UI.

---

## 8. The deployment-wide fallback notifier (optional)

Where the tech-lead's unprompted speech goes when a project's own channel cannot carry it, and
where a project with no channel at all is spoken to (needs-refinement / on-hold / paused /
PR-ready / prod-approval). It is a **declared kind** on the notifier axis, never inferred from a
provider's variables:

```bash
OPENFACTORY_NOTIFIER_FALLBACK=telegram     # a row the `openfactory-slack` package declares
OPENFACTORY_TELEGRAM_BOT_TOKEN=<bot token>  # read by that row, not by the core
OPENFACTORY_TELEGRAM_CHAT_ID=<chat id>
```

Unset → the panel is the last resort (its attention inbox shows everything). A declared kind
nobody installed, or one whose row cannot post, is a warning in the worker's log naming what is
missing — the package to `pip install`, or the variable — and the speech goes to the panel
until it is filled in. On the reference cloud deployment the terraform sets the three from
`telegram_bot_token` / `telegram_chat_id` in `deployment.tfvars`.

---

## 9. Alerting & budget (already on)

`infra/terraform/alerting.tf`: an SNS topic + EventBridge rule (task stopped non-zero) →
email, a worker-error log alarm, and a `$50/mo` AWS budget at 80%. Point the email at
yourself:
```bash
export TF_VAR_alert_email="you@example.com"
infra/deploy.sh
```

---

## 10. Coding agent roles (planner → executor)

The coding agent runs as a **two-stage pipeline**: a **planner** (read-only — investigates
and drafts a short, testable plan) then an **executor** (implements the plan with TDD).
Both are **harness-neutral role prompts** in `openfactory/org_defaults/roles/planner.md` and
`executor.md` — each adapter renders the *same* roles its own way (`claude -p`, `codex exec`,
`kimi -p`). That's what keeps the pipeline portable: the roles are the source of truth, the
adapter is the projection. **Which harness** renders them is §11.

- **Customize a role:** edit the neutral prompt (`openfactory/org_defaults/roles/*.md`). It reaches
  the workers on the next image build/deploy; locally it takes effect immediately.
- **A model per role** (plan cheap/fast, execute strong) — env vars the adapter reads:
  ```bash
  # local (.env or export):
  OPENFACTORY_PLANNER_MODEL=claude-opus-5    # investigate + draft the plan
  OPENFACTORY_EXECUTOR_MODEL=claude-opus-5   # implement with TDD
  ```
  **In prod** they're Terraform vars injected into the sandbox task env, both defaulting to
  `claude-opus-5`:
  ```bash
  export TF_VAR_planner_model="claude-opus-5"; export TF_VAR_executor_model="claude-opus-5"
  infra/deploy.sh
  ```
  Value = anything `claude --model` accepts. **Use an explicit model id, never a family alias
  like `opus`.** An alias is resolved by whichever Claude Code CLI version the worker image
  pins, so the factory's real model silently becomes a side effect of an image bump — that is
  how it sat on Opus 4.8 for a while after Opus 5 shipped. An explicit id makes the model a
  deliberate decision and an upgrade a reviewable one-line diff. Empty → the CLI default.
  Verified: the adapter emits `--model <value>` for the planner call and the executor call.
- **In the panel:** the live feed labels each action **PLANNER** / **EXECUTOR** (the thing
  that changes line to line); the **harness** (Claude Code) is shown once, in the cockpit.
- **Independent review is *not* one of these two stages** — it is its own harness role
  (§11), configurable separately precisely so the reviewer can be a different engine from the
  one that wrote the code.
- **Adding roles / harnesses:** neither edits a file of ours. A new role is a `role.<name>`
  entry point in the `openfactory.adapters` group whose builder returns a `RoleSpec` — its
  prompt, its own two env names, whether a person reads its answers, an optional default
  harness (§11, *Add-on roles*); a new harness is a `harness.<kind>` entry point in the same
  group, or, inside this repository, one entry in `openfactory/adapters/agent/registry.py` plus
  its module. The shipped roles and the rest of the pipeline don't change.

---

## 11. Which harness plays each role (executor · reviewer · techlead)

Three roles, each independently configurable. They are named after what they **do** and after the
prompt files that shape them (`openfactory/org_defaults/roles/*.md`), so what you configure and what
drives its behaviour share a name. Full rationale: **ADR-0018**.

| Role | Does | Stages it serves | Runs in |
|---|---|---|---|
| `executor` | **writes the code** | plan · execute · repair · continue · recover | the ephemeral job box |
| `reviewer` | **reviews the diff** | review | the ephemeral job box |
| `techlead` | **judges** | pre-flight sizing · parked-decision advice · impediment diagnosis · Slack answers | the long-lived worker |

`techlead` includes the **sizer** — same nature (read-only judgment), same place.

### Setting it

In the project's entry in `deploy/registry.yaml`. **One line** covers the common case, where a
deployment uses the same harness everywhere:

```yaml
harness: codex                  # executor, reviewer and techlead
```

Per role, when they differ:

```yaml
harness:
  executor: codex
  reviewer: claude_code         # a genuinely independent second opinion
  techlead: claude_code
```

A key that is not a role is **warned by name** when the registry loads (`harness: {reviewr: …}`
used to load clean and configure nothing); `default` covers every role not named.

### Add-on roles

The role axis is open the same way the harness axis is (2026-08-24). A package that ships an agent
around the core — a QA role, a security reviewer — declares it as an entry point and never edits a
file of ours:

```toml
[project.entry-points."openfactory.adapters"]
"role.qa" = "openfactory_qa:role"     # a builder returning openfactory.adapters.agent.RoleSpec
```

The `RoleSpec` carries what the platform needs to resolve the role: its **prompt**, its **own two
env names** for the harness and model overrides (never a `OPENFACTORY_*` name — that namespace,
its old `SDLC_*` spelling and the variables of the tools the platform drives are reserved, and a
spec claiming one is refused by name; the foreign names are derived from the code's own reads,
never listed by hand, so a variable is reserved the day a module reads it), **`human_facing`** —
whether a person reads its answers
(`False` for a one-word verdict the add-on's own code parses; the project's language directive is
withheld for that role's phases, exactly as it is for the product role's approve/reject verdict),
and an optional default harness. Once installed, `qa` has its own `harness:` / `model:` line,
`openfactory project set-model <name> <m> --role qa` accepts it, and the panel cockpit shows it.

What the core does **not** do for an add-on role is invoke it: the package that ships the role
calls `build_asker(project, role="qa")` itself and does something with the answer. Refused, and
logged once: a shipped role's or prompt's name (`techlead`, `sizer`), `default`, the name of a
phase the platform passes (`size`, `chat`), and a second add-on claiming a variable the first
already reads.

Known values: `claude_code` (default), `codex`, `kimi`. **An unknown value fails the job loudly**
rather than falling back — a run that silently used an engine nobody chose would report clean
numbers for the wrong thing.

Resolution order per role: env override → the project's `harness` → the default. The env vars
`OPENFACTORY_HARNESS_EXECUTOR`, `OPENFACTORY_HARNESS_REVIEWER`, `OPENFACTORY_HARNESS_TECHLEAD` exist **only** as an
escape hatch for a quick experiment (the registry is baked into the worker image, so trying a
harness would otherwise cost a rebuild and a roll). Don't configure a deployment with them.

### What to know before switching

- **A Claude deployment is unaffected.** Where a harness ships its own proven implementation of a
  role, that one is used; the shared implementation serves harnesses that have none (ADR-0018 §3).
- **Same harness for `executor` and `reviewer` is a real reduction.** The review becomes a fresh
  context on the same engine — still useful, no longer an independent second opinion.
- **Codex** has completed real tickets, but its plumbing is not yet at parity: no credential pool,
  no durable cross-container resume, no transcript writing. The *roles* are at parity.
- **Kimi is wired but unproven** — no observed stream output yet. Its read-only guarantee is also
  weaker (a mode, not an enforced policy). Don't put a client on it until a real run.
- **Cost from a harness that reports no price reads UNKNOWN, never `$0.00`.** A zero would make it
  look free and win every comparison.

### The four-hour wall

Every harness is stopped after **4h** of wall-clock in one agent call. Claude normally stops on
`--max-turns` long before; for a harness with no turn cap (Codex) this wall *is* the bound. A run
that hits it parks as an impediment with a diagnosis for the tech-lead — not as a rate-limit pause,
because a stuck run does not get better by waiting. Tunable with `OPENFACTORY_AGENT_TIMEOUT` (seconds);
the launcher and Temporal ceilings derive from it automatically, so don't set those by hand.

---

## 12. The product module (PO/BA/PM) — optional per client

The role that turns a conversation into a requirement. **Opt-in**: a project with no `product:`
section does not have the module, and nothing changes for it. Full design: **ADR-0019**.

### Switching it on

The normal path is the command — it writes to the deployment's LIVE registry (the file below is the
seed for a NEW deployment; editing the seed does **not** reach a deployment that is already
running):

```bash
openfactory product declare <project> <owner/repo>            # a context repo that ALREADY exists
openfactory product init <project> --create-context --write   # create one
```

In `deploy/registry.yaml` (the seed), inside the project:

```yaml
product:
  docs_repo: yourorg/myapp-documentation              # required
  admins: [ana]                                       # who may make it WRITE — panel identities
  docs_branch: main                                   # optional
  enabled: true                                       # optional (the incident switch)
```

`admins` are the ids of the surface the module speaks on: the `OPENFACTORY_PRODUCT_TOKENS`
identities on the panel, which is where the module lives unless a chat add-on package is
installed. **There is no chat coordinate here on a core deployment.** `channel_id` (and its
retired spelling `slack_channel`) selects the product's own chat channel, which is one of the
`openfactory-slack` package's rows; pasted into a deployment that does not have that package it
does not switch a channel on — it becomes the product surface's destination, so the module
addresses a chat id where it should address the project.

The **presence** of the section is the switch — there is no "on with nowhere to write". To turn it
off without losing the configuration, `enabled: false`.

The **source** repo declares the other side in its `.openfactory/project.yaml`:

```yaml
docs_repo: yourorg/myapp-documentation
```

And the **documentation** repo declares its members in `.openfactory/product.yaml`:

```yaml
product: myapp
sources:
  - yourorg/myapp
requirements_dir: requirements
```

**All three declarations have to agree.** The registry authorises; the source repo's only confirms
and **never redirects** (otherwise anybody with write access to a source could point the PO at
another repository by editing one line). A divergence **switches the module off** with a message
naming the file to fix, rather than guessing — writing a requirement into the wrong product's
repository is a break in client isolation, not a typo to work around.

### Who may do what

| action | who |
|---|---|
| ask about the product, request a draft | anyone in the channel |
| rewrite a criterion, clarify scope, break down, relate | the PO, on its own (once authorised) |
| record a requirement | a PR on the docs repo → **a human merges** |
| file an issue into **Backlog** | the PO, on its own |
| promote to **TO-DO** | **a human** — this is where the money starts |

An empty `admins` means nobody writes. Switching the module on never hands out authoring
rights by itself.

### Language

Every human-facing role (the tech lead and product) speaks the project's language when it **speaks
first** — a notice, a diagnosis, a question, a summary. When it **answers**, it follows the language
of whoever wrote, even if that is a different one: somebody who asks in English wants an answer in
English.

```yaml
language: en         # `pt-BR`, `es`, … — the project's own
```

It is `Project.language`, in the registry — it applies to the tech lead too, not only to product.
The code phases (plan/execute/repair/review) are **not** affected: touching them would move a path
that already works in production, with no benefit anybody asked for.

Identifiers are never translated in any of these cases — a file name, a requirement number, a
command, an error message.

### Harness

`product` is a fourth axis, beside executor/reviewer/techlead:

```yaml
harness: {executor: claude_code, product: codex}
```

### What it never does

It does not write to a code repo, does not review a diff, does not promote to TO-DO, and does not
treat a `superseded` requirement as current truth (it is kept as history, and stays quotable).
