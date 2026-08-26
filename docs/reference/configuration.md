# Configuration

Three places, and **which one a thing lives in is a decision, not an accident**:

| | who owns it | why |
|---|---|---|
| **the manifest** — `.openfactory/project.yaml`, in your repository | the client's team | it describes the *work*: how to install, how to validate, what the components are |
| **the registry** — `registry.yaml`, on the deployment | the operator | it describes the *installation*: credentials, which board, which harness, which box |
| **the environment** — `.env`, SSM, Secrets Manager | the operator | secrets, and only secrets |

The boundary between the first two is a **security boundary**. The manifest lives in the repository
the agent edits, so anything an agent could rewrite to its own advantage belongs in the registry.
`box.image` is the sharpest case: an agent able to set it would be choosing its own root filesystem,
turning *"the agent wrote the wrong code"* into *"the agent picked the machine"*.

---

## The manifest

31 fields, **all optional** — an empty file loads. The ones that matter:

```yaml
version: 1
base_branch: main
merge_policy: human          # human | auto

setup:
  - "pip install -e '.[dev]'"

validate:                    # the REAL quality floor: the platform runs these
  test: "pytest -q"          # and reads the exit codes. It does not trust the
  security: "bandit -r . -ll -q"   # agent to have run them.
  lint: "ruff check ."
  type: "mypy ."

docs:
  constraints: docs/adr/**   # always loaded — the constitution

components: {}               # only if polyglot or with risk zones
  # backend: { path: app/, stack: python, risk: normal }
  # infra:   { path: terraform/, stack: terraform, risk: high }
```

**`merge_policy: human`** is the recommended first setting: the bot opens the PR, a person merges.
`auto` merges when gates are green, review did not reject, and no high-risk component was touched.

**A `risk: high` component stays human-gated even on `auto`.**

**`validate` is the whole integration.** Commands are shell strings and only the exit code is read.
That is what makes any stack work at the calling surface — and it is also the entire extent of the
stack knowledge, so a language the presets do not know still works, it just brings its own commands.

The floor (`openfactory conformance`) requires `test` and `security`. Note that it is a command somebody
runs, not a gate on the job path — see [05](../STATUS.md).

**A field name typo is fatal here** (`extra="forbid"`), deliberately: the manifest is in your
repository, in your diff, in your review. The one trap is that `validation:` is silently accepted as
a synonym for `validate:`.

**The promotion chain is yours to name** (#109). `environments:` declares the deploy targets the
platform observes after a merge; `promote: [dev, qa, producao]` declares the order it walks them,
and the LAST entry is production — a human approves it from the panel, always, whatever your shop
calls it, so the manifest agrees with your change-management document instead of renaming a stage
to satisfy ours. A chain step with no matching environment is refused with both sides named; an
environment declared but absent from the chain is warned as unwatched, never silently accepted.
Omit `promote:` and the two fixed names apply — `staging` observed if declared, `prod` gated if
declared.

**Measured limitation — one base branch.** `base_branch` is both where the factory's PRs land and
where the release tag is cut. A two-branch flow (integration `develop` + release `main`) cannot be
expressed: with the integration branch as base the release tag lands on the integration tip, and
with the release branch as base the factory's PRs bypass integration. If your shop runs two
branches, point the factory at the branch releases actually cut from and let your own CI carry
integration — and raise it during onboarding rather than discovering it at the first release.

---

## The registry

```yaml
projects:
  acme:
    name: acme
    repo_path: /var/lib/openfactory/repos/acme      # local path
    tracker: { kind: github, repo: acme/api,
               options: { board_owner: acme, board_number: "3" } }
    harness: codex                            # or per role, below
    language: pt-BR                           # when an agent SPEAKS FIRST (unset: en)
    box:
      image: mycorp.azurecr.io/ci-base:2026.7 # what your CI already runs on
      network: openfactory-egress                    # bound what agent code can reach
      cache_volume: openfactory_cache                # skip a full install per job
      cpus: "4"
      memory: "8g"
```

**The registry NAMES a credential; it never HOLDS one.** Every axis takes an `options.token_env`
(the channel takes `bot_token_env` / `app_token_env`) naming the environment variable that
carries the secret:

```yaml
    tracker: { kind: azure_devops, repo: Deskline,     # the ADO PROJECT — work items live here
               options: { organization: acme, token_env: ACME_ADO_PAT } }
    forge:   { kind: azure_devops, repo: dsk-api,          # the git repository inside it
               options: { organization: acme, project: Deskline, token_env: ACME_ADO_PAT } }
```

(`openfactory project add` writes exactly this shape from a `dev.azure.com` clone URL — the
complete ADO walkthrough, `work_item_type`, `state_map` and the multi-repo `areas` map included,
is [docs/setup/azure-devops.md](../setup/azure-devops.md).)

That is what lets ONE deployment drive projects on different vendors — and it is not a
refinement, it is a correctness fix: with a single process-wide token, a worker serving a GitHub
project and a Jira project authenticated both with whichever one the environment happened to
carry, and the Jira board came back with an empty queue (found live, fx-jira 2026-08-05). Name
nothing and the axis falls back to the deployment-wide default (`OPENFACTORY_BOT_TOKEN`,
`AZURE_DEVOPS_PAT`…), which is correct exactly while one vendor exists. The registry is also
often gitignored and baked into a worker image — a token written here is a token in an image
layer.

**`harness`** takes one value for everything, or one per role:

```yaml
harness: { executor: codex, reviewer: claude_code, techlead: claude_code }
```

The keys are the shipped roles (`executor`, `reviewer`, `techlead`, `product`), `default` for
every role not named, and any role a deployment installed as an add-on (a `role.<name>` entry
point — [configuration §11](../configuration.md)). A key that is none of these is **warned by
name** when the registry loads; it configures nothing.

**`model`** — which model that harness runs — takes the same two shapes, in the harness's OWN
naming (each CLI names models differently; a Bedrock inference profile ARN is a legitimate
value). You never have to edit this by hand: `openfactory project add --model <m>` sets the
blanket form at registration, and `openfactory project set-model <name> <m> [--role executor]`
changes it later — per role too — from the CLI.

Keeping an *independent* reviewer on a different engine from the one that wrote the code is what
makes the review prompt's *"you did NOT write this code"* structurally true. Rotating between
harnesses never touches an image — they are mounted, not baked ([ADR-0037](../adr/0037-the-box.md)).

**`box`** is only honoured by the container box. On a Fargate deployment `box.image` **raises**
rather than being ignored, and the other four warn — a setting that looks configured and is not is
this codebase's most expensive recurring defect, and refusing loudly is cheaper than a silent lie.

**`channel`** — where the factory speaks to *this project's* humans. It is deliberately absent
from the example above: unset means **the panel**, the one surface that always exists, and that
is the shape a stranger should copy. `channel: <kind>` names a row on the channel axis, and so
does a chat coordinate on its own — `channel_id` (still accepted under its old spelling
`slack_channel`) implies the chat kind, which is exactly why it cannot sit in a starter example:
a kind no installed package declares is **refused by name** when the channel is built, naming
the package that carries the row. Put a chat coordinate in the registry of a deployment that
installed that add-on; the worker keeps serving every other project through the panel either way.

**`language`** is a default, not a hard setting, and the difference matters: it only governs an
agent SPEAKING FIRST — an announcement, a diagnosis, a question nobody prompted. A reply always
mirrors whatever language the human just wrote in, regardless of this. It lives here rather than
in the manifest because it is about how the factory talks to *this project's humans* — the same
axis as `channel_id`, not the code — and it reaches every human-facing role (tech-lead and
product); the coding phases are untouched. `openfactory project add --language <code>` sets it from the
CLI too.

**An unknown key here is IGNORED and reported by name**, not fatal — the opposite of the manifest,
and for a concrete reason: this file is often gitignored and baked into a worker image, so nobody
reviews it, and one stale line becoming an outage is a failure the operator could not have caught.

---

## The environment

Secrets and deployment coordinates. The ones you will actually set:

| | |
|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` / `ANTHROPIC_API_KEY` | the harness. Irreducible |
| `OPENFACTORY_GH_APP_ID` · `OPENFACTORY_GH_APP_KEY` *(path)* or `OPENFACTORY_GH_APP_KEY_CONTENT` *(the PEM)* · `OPENFACTORY_GH_APP_INSTALLATION_ID` | the GitHub App |
| `OPENFACTORY_BOT_TOKEN` | a static forge/tracker token instead of the App. `OPENFACTORY_TRACKER_TOKEN` / `OPENFACTORY_FORGE_TOKEN` override per axis |
| `OPENFACTORY_BOT_NAME` · `OPENFACTORY_BOT_EMAIL` · `OPENFACTORY_BOT_LOGIN` | who the factory commits as |
| *(the chat channel's variables)* | **not read by the core.** The rows that read them ship in the `openfactory-slack` add-on package and declare their own names (`plugins.environment`); the package's README lists them. Setting them on a core without the package switches nothing on — the channel is the panel and the notifier is the panel's |
| `OPENFACTORY_PANEL_TOKEN` | **unset means the panel is OPEN** — and it is the SHARED token; approvals recorded under it have no name |
| `OPENFACTORY_PANEL_TOKENS` | per-person panel identity, `token:id:display,...` — the only way "who approved that release" has an answer |
| `OPENFACTORY_PRODUCT_TOKEN` / `OPENFACTORY_PRODUCT_TOKENS` | the product-owner surface (`/product/<name>`). The shared form is read-only in practice — writes check `product.admins` against the per-person `id` ([06](product-role.md)) |
| `OPENFACTORY_PROD_APPROVERS` | deployment-wide release allowlist (the manifest's `prod_approvers` is the per-project form) |
| `OPENFACTORY_APPROVERS` / `OPENFACTORY_APPROVERS_FILE` | the hashed release passwords, when `~/.openfactory/approvers.json` cannot be mounted |
| `OPENFACTORY_SANDBOX` | which box every job runs in: `worktree` \| `container` \| the kind an installed box add-on registers (`fargate`, from the AWS add-on). Unset → `container`. **Never inferred** — a cloud deployment DECLARES `OPENFACTORY_SANDBOX=fargate`; setting only the add-on's cluster coordinates leaves every job in a local container |
| `OPENFACTORY_TOKEN_POOL_SOURCE` | where the panel reads the agent-token pool from (count and ids, never a value): `env` (the default — this process's environment) \| the kind an installed add-on registers (`ssm`, from the AWS add-on). Unset → `env`. Never inferred — the reference cloud deployment declares `ssm` |
| `OPENFACTORY_SANDBOX_IMAGE` | deployment-wide box image; a project's `box.image` wins |
| `OPENFACTORY_METRICS_SINK` · `OPENFACTORY_METRICS_DB` | `sqlite` locally, `dynamodb` in the cloud, `null` for neither |
| `OPENFACTORY_NOTIFIER_FALLBACK` | the deployment-wide fallback notifier, as a KIND on the notifier axis — where speech goes when a project's own channel cannot carry it, and where a project with no channel is spoken to. Unset → the panel. `telegram` is the row the `openfactory-slack` package declares (it reads `OPENFACTORY_TELEGRAM_BOT_TOKEN` and `OPENFACTORY_TELEGRAM_CHAT_ID`; the core reads neither). A declared kind nobody installed, or a row that cannot post, is a warning naming what is missing — never silently the panel |
| `OPENFACTORY_LOG_DIR` | where the job journals are written and read — the panel's **Logs** button, and the free counterpart of a cloud log group. The worker and the panel must agree |
| `OPENFACTORY_SESSION_STORE` · `OPENFACTORY_RESUME_DIR` | where a paused agent session waits so the next run continues it instead of replanning: `file` (the default — a directory on this machine) or `s3`. Unset → `s3` if `OPENFACTORY_RESUME_BUCKET` is set, else `file` |
| `OPENFACTORY_REGISTRY` · `OPENFACTORY_REGISTRY_SEED` | where the registry is read and what seeds it on first boot |
| `OPENFACTORY_TOOLBOX` · `OPENFACTORY_TOOLBOX_VOLUME` | the harness toolbox: where the worker keeps it, and the docker volume name it mounts into boxes |
| `TEMPORAL_ADDRESS` · `TEMPORAL_NAMESPACE` | the durable engine. Compose sets these to its own container |
| `OPENFACTORY_MAX_CONCURRENT_JOBS` · `OPENFACTORY_MAX_TURNS` · `OPENFACTORY_AGENT_TIMEOUT` | the throttles |

There are around seventy `OPENFACTORY_*` variables in total; the rest are per-job values the runtime sets
for itself inside a box, or cloud-only coordinates (`OPENFACTORY_FARGATE_*`, `OPENFACTORY_RESUME_BUCKET`,
`OPENFACTORY_*_LOG_GROUP`) that a local deployment never reads — a cloud-only *coordinate*, never a
cloud-only *capability*: every one of them has a free counterpart above, because a deployment with no
cloud may cost you a vendor and must never cost you a feature.

**Precedence, where it exists**, is always most-specific-wins: an explicit CLI flag, then the
project's registry entry, then a deployment-wide environment variable, then the framework's default.
