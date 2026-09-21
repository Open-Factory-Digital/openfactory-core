# Feature coverage

This table lists every capability the platform ships and maps each one to the phase of the
[delivery method](01-delivery-method.md) that introduces it, the role responsible for it, the
[profiles](02-profiles.md) where it is expected, and the command or file that evidences it. A
certified implementation accounts for every row at its claimed profile: required rows are in
place, recommended rows have a recorded decision, and not-applicable rows have been stated to the
customer. Exam domains in [03-role-certifications.md](03-role-certifications.md) are derived
from this table.

Rows reflect the public tree at `openfactory` 0.3.0. Capabilities carried by add-on packages are
marked *(add-on)*. Known limitations from [STATUS.md](../STATUS.md) are listed at the end.

Legend: **L** Light, **S** Standard, **E** Enterprise. **●** expected, **○** decided per
deployment, **–** not applicable.

## A. Installation and distribution

| capability | what it is | phase | owner | L | S | E | evidence |
|---|---|---|---|---|---|---|---|
| one-machine door | the factory on one machine: `local` tracker, forge and board; `worktree` box; no Docker | 3.1 | operator | ● | – | – | `openfactory up`, `doctor` |
| compose stack | Temporal, its database and UI, the worker, the panel, the box image, the cli image | 3.1 | operator | ○ | ● | ● | `docker compose ps` |
| one-line installer | resolves the release, verifies checksums, pulls images, runs `preflight` and `init`, starts the stack; `--dry-run`, `--version`, `--force`, `--uninstall`, `--` for unattended `init` | 3.1 | operator | ○ | ● | ○ | the installer's output |
| version pinning and checksums | `OPENFACTORY_VERSION` written into `.env.compose`; `SHA256SUMS` verified; assets from the release, never the site | 3.1 / 6.1 | operator | ○ | ● | ● | `.env.compose` |
| published images | worker, panel (same image), sandbox, cli, base — multi-arch on GHCR | 3.1 | operator | ○ | ● | ● | `docker images` |
| `openfactory init` | writes the deployment's environment file from answers; every answer is a flag; refuses without a terminal naming the flag | 3.1 | operator | ● | ● | ● | `.env.compose` |
| `openfactory preflight` | nine machine checks: daemon, compose, architecture, ports, disk, work dir, box image, env file, agent credential; `--json` is a versioned contract | 3.1 | operator | ● | ● | ● | its output |
| upgrade path | re-run the installer with `--force`, or `git pull && up -d --build` for a checkout; `doctor` opens with the build it runs | 6.1 | operator | ● | ● | ● | `doctor`'s first line |
| host work directory | `OPENFACTORY_WORK_DIR`, a real host directory the worker and the box both see at the same path | 3.1 | operator | ● | ● | ● | `ls -ld` |
| named volumes | state, toolbox, logs, engine database survive `down` | 3.1 / 6.4 | operator | ○ | ● | ● | `docker volume ls` |
| contributor build | `--profile build` builds base, sandbox and cli from a checkout | 3.1 | developer | ○ | ○ | ○ | `make build` |
| cloud realisation *(add-on)* | the reference deployment on one cloud: a remote box runner, a managed metrics table, a session store, a token pool | 2.1 / 3.1 | architect | – | – | ○ | the add-on's own documents |

## B. Provider axes

| capability | what it is | phase | owner | L | S | E | evidence |
|---|---|---|---|---|---|---|---|
| tracker: `local`, GitHub Issues, Jira, Azure DevOps work items | where tickets are read and written | 2.2 | architect | ● (`local`) | ● | ● | the registry |
| board: `local`, GitHub Projects v2, Jira status, Azure Boards | the columns a card moves through; six on GitHub Projects, five states on Azure | 2.2 / 3.2 | architect, operator | ● | ● | ● | `doctor` `board_columns` |
| forge: `local`, GitHub, Azure Repos | branches, pull requests, merges, tags | 2.2 | architect | ● | ● | ● | `doctor` `forge_access` |
| CI observer: `none`, GitHub Actions, Azure Pipelines | read-only observation of the client's pipeline; `none` is a declaration, not a gap | 2.2 / 2.7 | architect | ● (`none`) | ● | ● | `doctor` `ci_declared` |
| harness: Claude Code, Codex, Kimi, OpenCode | the coding agent, per project and per role | 2.2 | architect | ● | ● | ● | the registry `harness:` |
| model per role | `model:` per role, passed verbatim; Bedrock, Vertex and gateway routes are values | 2.2 / 3.7 | architect | ○ | ● | ● | `project set-model` |
| reviewer engine | the independent review on a different harness or model from the executor | 2.2 | architect | ○ | ● | ● | the registry |
| channel: panel; Slack *(add-on)* | where people talk to the factory; the panel is always there | 2.2 | architect | ● (panel) | ● | ● | `channel:` |
| notifier: panel; Slack, Telegram *(add-on)* | the push half; the deployment-wide fallback is declared, never inferred | 2.2 | operator | – | ○ | ○ | `OPENFACTORY_NOTIFIER_FALLBACK`, `doctor` |
| sandbox: `worktree`, `container`; a remote box *(add-on)* | where a job runs; the box's traits decide what gates apply | 2.4 | architect | ● | ● | ● | `OPENFACTORY_SANDBOX` |
| telemetry: SQLite, memory, null; a managed table *(add-on)* | where cost and job metrics are written and read | 2.9 | operator | ● (SQLite) | ● | ● | `OPENFACTORY_METRICS_SINK` |
| event sinks: file, stdout, tee, memory, null | the journal | 2.9 | operator | ● (file) | ● | ● | `OPENFACTORY_LOG_DIR` |
| identity: `local`, OIDC | who a person on the panel is | 2.3 | architect, security | – | ● (`local`) | ● (OIDC) | `OPENFACTORY_IDENTITY` |
| credential rows: local, GitHub, Jira, Azure DevOps | how each vendor's credential is minted or discovered | 2.3 | architect | ● | ● | ● | `credentials.py` |
| session store: file; an object store *(add-on)* | where a paused session crosses boxes | 2.9 | operator | ● (file) | ● | ○ | `OPENFACTORY_RESUME_DIR` |
| token pool: env; a parameter store *(add-on)* | the failover pool | 2.3 | operator | – | ○ | ● | `OPENFACTORY_AGENT_TOKENS` |
| add-on entry points | `openfactory.adapters` group; `<axis>.<kind>`; a built-in row wins a collision; an unknown kind refuses by name | 2.2 / 7 | developer | – | ○ | ○ | `conformance-adapter` |

## C. Project registration and configuration

| capability | what it is | phase | owner | L | S | E | evidence |
|---|---|---|---|---|---|---|---|
| `project init` | register, create the board with the platform's columns, scaffold the manifest; converges | 3.2 | implementer | ● | ● | ● | `project list` |
| `project add` | register against an existing board or none; `--repo`, `--board-owner`, `--board-number`, `--work-item-type`, `--token-env`, `--model`, `--language` | 3.2 | implementer | ○ | ○ | ○ | `project list` |
| `project set-model`, `set-language`, `remove`, `list` | registry edits without YAML | 3.2 / 4 | operator | ● | ● | ● | `project list` |
| the manifest (`.openfactory/project.yaml`) | 31 optional fields; `extra="forbid"`; the client's file in the client's repository | 2.5 / 3.2 | implementer, developers | ● | ● | ● | `conformance <project>` |
| `setup:` and `validate:` | shell strings; only the exit code is read; `test` has no default | 2.5 | implementer | ● | ● | ● | `box prove` |
| gates with `advisory: true` and `timeout_minutes` | a gate that reports and never blocks | 2.5 | implementer | ○ | ● | ● | the manifest |
| `components:` with `path`, `stack`, `risk`, per-component gates and guidelines | a monorepo with several stacks and risk zones | 2.5 | implementer | ○ | ● | ● | the manifest |
| `docs:` roles: constraints, architecture, guidelines | what the coding agent reads; 8,000 characters per file | 2.5 | implementer | ○ | ● | ● | the manifest |
| `protected_paths` | human-gated paths; the floor's `.openfactory/**` is inherited | 2.5 | architect | ○ | ● | ● | the manifest |
| budgets: `effort_budget_turns`, `repair_max_attempts`, `recovery_max_attempts`, `review_repair_max_attempts`, `suppression_repair_max_attempts`, `max_cost_usd`, `max_diff_lines`, `max_touched_components`, `max_plan_files`, `max_plan_steps` | how much a ticket may spend before it parks | 2.10 | architect, operator | ○ | ● | ● | the manifest |
| `preflight:` sizing config, `split_to_todo`, `planner_stage` | whether tickets are sized and split before a box is launched | 2.5 | architect | ○ | ● | ● | the manifest |
| `review_mode`: advisory, blocking, off | whether the reviewer can stop a merge | 2.6 | architect | ○ | ● | ● | the manifest |
| `merge_policy`: human, auto | who merges | 2.6 / 7 | sponsor, architect | ● | ● | ● | the manifest's history |
| `e2e_label`, `e2e_workflow` | the on-demand e2e ticket that dispatches the client's own workflow | 2.5 | implementer | – | ○ | ● | the manifest |
| `post_merge_deploy:` | watch one deploy workflow and report | 2.7 | implementer | ○ | ● | ○ | the manifest |
| `environments:` + `promote:` + `prod_tag_prefix` + `prod_approvers` | the promotion chain with a human production gate | 2.7 | architect | – | ○ | ● | the manifest, `doctor` `post_merge` |
| `knowledge_map`, `okf_concept_budget`, `okf_gate` | the module map and its gate stance | 2.5 | implementer | ○ | ● | ● | the manifest |
| `docs_repo:` | the source repository's pointer to its context repository; the one line the platform never writes | 3.2 | developers | – | ● (if product) | ● | the manifest |
| `profile:` (`prototype`, `regulated`) | a deployment profile that may only strengthen the floor | 2.5 | architect | ○ | ○ | ● | `org_defaults/profiles/` |
| presets (python, node, terraform, security-oss) | stack command tables the manifest may draw on | 2.5 | implementer | ○ | ○ | ○ | `openfactory/presets/` |
| the registry (`registry.yaml`) | the operator's file: credentials by name, board, harness, box, people, product; unknown keys ignored and reported | 2.2 / 2.3 | operator | ● | ● | ● | `deploy/registry.yaml.example` |
| `box:` in the registry: `image`, `network`, `cache_volume`, `cpus`, `memory`, `env` | the box's shape, outside the agent's reach | 2.4 | architect | ○ | ● | ● | the registry |
| `people:` map | forge login → channel id; names the requester the gather asks | 2.3 | operator | – | ○ | ● | the registry |
| `accepts_test_work`, `factory_board` | the partner's test-bench project and the factory's own impediment board | 4 | operator | – | ○ | ● | the registry |
| the environment (`.env.compose`) | secrets, and only secrets; `--env-file`, never `.env` | 2.3 | operator | ● | ● | ● | `ls -l .env.compose` |
| per-role env overrides | `OPENFACTORY_HARNESS_<ROLE>`, `OPENFACTORY_<ROLE>_MODEL` beat the registry for the whole worker | 2.2 | operator | – | ○ | ○ | `.env.compose` |
| org defaults: `engineering.md`, `tdd.md`, role prompts, `floor.yaml`, requirements template | the deployment's doctrine, baked into the worker image | 2.5 / 3.7 | architect | ○ | ● | ● | `openfactory/org_defaults/` |
| language (`en`, `pt-BR`) | the language an agent speaks first; replies mirror the human; Gherkin in both | 3.2 | operator | ● | ● | ● | `project set-language` |

## D. First-time setup and proof

| capability | what it is | phase | owner | L | S | E | evidence |
|---|---|---|---|---|---|---|---|
| `env read` | proposes the manifest field by field with file, line and confidence; writes nothing | 1.2 | architect | ● | ● | ● | its output |
| `env context` (`--ask`, `--write`) | the backfill: survey, architecture overview, glossary, invariants, open questions; citations checked against the filesystem; history read for churn | 1.2 / 3.2 | architect | ○ | ● | ● | the five documents |
| `env apply` (`--yes`, `--accept`, `--set`, `--force`, `--out`, `--pr`) | writes the manifest into a checkout, or proposes it as a pull request from the worker | 3.2 | implementer | ● | ● | ● | the diff or the pull request |
| `onboard` (`--yes`, `--source`, `--skip-context`) | per repository: read, prove in the real box, map, propose in one pull request; create-or-use the context repository; propose the backfill; disabled CI demoted to a question | 3.2 | implementer | ○ | ● | ● | the pull requests |
| `box prove` (`--repo`, `--image`, `--sandbox`, `--ref`) | image → toolbox → contract → setup → validate → harness auth → trust store; zero tokens on the container box; pins the toolchain | 3.3 | implementer, operator | ● | ● | ● | `box status` |
| `box status` | whether the proof holds, what moved, what it is pinned to | 3.3 / 6.2 | operator | ● | ● | ● | its output |
| `box answer` | the one check that spends tokens: can the harness log in | 3.3 | operator | ● | ○ | ○ | its output |
| pickup gate | a card on an unproven repository is held by name (container box) | 3.3 | operator | – | ● | ● | `doctor` `box_proof` |
| `env check` | one composed verdict, and where it was measured; exit 0 only when pickup is unblocked | 3.4 | implementer | ● | ● | ● | its exit code |
| `env rehearse` (`--yes`, `--no-gates`) | the whole loop on a synthetic ticket in a throwaway clone; prints the cost first | 3.4 | implementer | ● | ● | ● | its output |
| `doctor` | docker, harness, manifest, quality floor, forge access, board columns, post-merge, product link; plus processes, agent credential, CI declared, box proof, API budget, merge gates when they apply | 3.2 onwards | operator | ● | ● | ● | its output |
| `floor` | is the factory working, the panel's answer from the terminal | 4 | operator | ● | ● | ● | its output |
| `knowledge build` (`--publish`, `--repo`), `check`, `inventory`, `gate`, `check-concepts` | the module map: deterministic, zero tokens, refreshed after merges, published to the knowledge branch of the context repository | 3.2 / 4 | implementer | ○ | ● | ● | the knowledge branch |
| `product declare`, `product init` (`--create-context`, `--write`) | the context repository: existing, created, or created by the client's process | 3.2 / 7 | implementer | – | ○ | ● | `product init` output |
| `bot-token` | mints an App installation token; the App smoke test | 3.1 | operator | – | ● | ● | a printed token |

## E. The engineering loop

| capability | what it is | phase | owner | L | S | E | evidence |
|---|---|---|---|---|---|---|---|
| the poller | takes the pickup column one card at a time; resumes paused tickets; `poller status`, `pause`, `resume` | 4 | operator | ● | ● | ● | `poller status` |
| `run <project> <issue>` | one ticket, right now, in this process; `--sandbox`, `--image`, `--review` | 3.5 | implementer | ● | ○ | ○ | its exit code |
| the spec gate | objective and acceptance criteria required; headings matched by meaning in English or Portuguese; a refusal names what it found | 3.5 / 4 | requesters | ● | ● | ● | the card's comment |
| pre-flight sizing | INVEST judgement on the worker before any box: fit, split into ordered children, or unclear → Needs Action; a degraded sizer is loud | 4 | operator | ● | ● | ● | the card's comment |
| the seven stations | spec, prep, plan, code, test, review, PR | 3.5 | all | ● | ● | ● | the panel |
| the box (ephemeral) | clone, setup, the agent, the gates; torn down after | 3.5 | operator | ● | ● | ● | `docker ps` during a job |
| the quality floor on the job path | `test` and `security` required; an unmet floor holds the ticket before an agent runs; no switch | 2.5 | architect | ● | ● | ● | the card's hold message |
| bounded repair | validation fails → up to `repair_max_attempts` fix passes | 4 | operator | ● | ● | ● | the pull-request body |
| the independent review | spec + diff + gate results, never the author's reasoning; a decision, a score, findings tied to criteria; review-repair on concrete findings | 3.5 | developers | ● | ● | ● | the pull-request body |
| re-review | replaces a stale verdict after a repair pass; costs one model pass; never spent for you | 4 | developers | ○ | ● | ● | the panel |
| suppression handling | `noqa`, `type: ignore`, `nosec` disarm auto-merge and route to a human; a coverage pragma needs a vetting review | 2.6 | architect | ● | ● | ● | the pull-request body |
| the pull request body | validations, the review, touched components, cost, dropped workflow changes | 3.5 | developers | ● | ● | ● | the pull request |
| the `workflows` refusal | any `.github/workflows/**` change reverted before commit and listed as a human to-do | 2.3 | security | ● | ● | ● | the pull-request body |
| CI-aware repair | a red CI on the bot's pull request is repaired, not merged past (needs Checks: Read) | 2.6 | operator | – | ● | ● | the pull-request history |
| merge on current base | rebase before merge; squash; head branch deleted | 2.6 | operator | ● | ● | ● | the forge |
| auto-merge conditions | gates green, review not rejected (blocking), no hard suppression, vetted pragma, nothing high-risk, no protected hit, floor readable, census not shrunk, profile allows | 2.6 / 7 | architect | ○ | ● | ● | `merge_policy.py`'s table in the PR body |
| human merge from the panel or chat | Merge, Adjust…, Discard on the attention bar; the same rows by typed assent through the same credential check; a question never acts | 4 | developers | ● | ● | ● | the panel |
| one job at a time | `OPENFACTORY_MAX_CONCURRENT_JOBS`, default 1, deployment-wide; the floor frees at merge | 2.10 | architect | ● | ● | ● | `.env.compose` |
| token-pool rotation | cyclic failover; continues the session; one lap then pause; growing backoff; perfect resume | 6.2 | operator | – | ○ | ● | the panel's `index/N` |
| pause and resume | partial code pushed, session kept, resumed with `--resume`; `OPENFACTORY_RESUME_DIR` swept after 7 days | 4 | operator | ● | ● | ● | the panel |
| recovery ladder | continue the same session, then a fresh recovery pass that may simplify scope, within `effort_budget_turns`; partial work preserved | 4 | operator | ● | ● | ● | the card's comment |
| Needs Action | a parked card with a decision-shaped message; Resume, Skip | 4 | operator, requesters | ● | ● | ● | the board |
| the on-demand e2e ticket | an e2e-labelled card dispatches the client's workflow and reports | 4 | developers | – | ○ | ● | the card |
| multi-repository products | one registration, one board, the card carries its repository; per-repository manifest, proof, map, pull request; Area Path on Azure | 2.5 / 3.2 | architect | – | ○ | ● | `onboard --source` |
| the `factory-test` refusal | a test card is refused on a board that did not declare `accepts_test_work` | 4 | operator | ● | ● | ● | the card's refusal |
| cost per job | recorded per job to the metrics sink; the cost dashboard by period, model, harness | 4 | operator | ● | ● | ● | `/api/metrics` |

## F. After the merge

| capability | what it is | phase | owner | L | S | E | evidence |
|---|---|---|---|---|---|---|---|
| nothing follows, said so | a project with no environments finishes at the merge and the ticket says nobody is watching | 2.7 | implementer | ● | ○ | ○ | the ticket |
| deploy watch | finds the workflow run on the merge commit, follows it, reports success, failure or timeout; a `url:` turns the report into a request | 2.7 | implementer | ○ | ● | ○ | the ticket |
| promotion chain | every pre-production stage observed in order (deployment status, then health URL); the last name is production; parks at the gate; `validate_with: product`; only on a remote box | 2.7 | architect | – | ○ | ● | the panel |
| the production gate | a named approver, a password, a version; tags `<prefix><version>`; observes; rolls back a red production | 2.3 / 2.7 | approver | – | ○ | ● | the release form, the tag |
| `approver add`, `list`, `remove` | the approver store; `OPENFACTORY_APPROVERS` wins while set | 2.3 | operator | – | ○ | ● | `approver list` |
| a person asked to look | the operator on the panel; the client through the product channel, in their language, at the `url:` | 2.7 | product owner | – | ○ | ● | the message |

## G. Roles, people and authorisation

| capability | what it is | phase | owner | L | S | E | evidence |
|---|---|---|---|---|---|---|---|
| the executor | writes the diff; plan, execute, repair, continue, recover; in the box | 3.5 | – | ● | ● | ● | `roles/executor.md` |
| the reviewer | judges the diff; prompt built, never a file a deployment can soften | 3.5 | – | ● | ● | ● | `reviewer/harness.py` |
| the tech lead | sizes, advises, diagnoses, chats; classifies failures transient, credential, environment, requirement, code, unknown; remembers what failed twice; outcome observed, never self-reported | 4 / 5 | operator | ● | ● | ● | the card's escalation |
| the product role | PO, BA and delivery manager at once; answers with requirement numbers; reads the board; proposes the queue; chases once; announces; asks whether it worked | 7 | product owner | – | ○ | ● | `/product/<name>` |
| add-on roles | `role.<name>` entry points returning a RoleSpec | 7 | developer | – | – | ○ | `conformance-adapter` |
| the panel | the floor, each job's pipeline, attention, one-click resume/skip, production approval, the board, the pull-request page, Logs, product | 4 | all | ● | ● | ● | `http://<panel>` |
| per-person identity | `OPENFACTORY_PANEL_TOKENS`, `OPENFACTORY_PRODUCT_TOKENS`; a shared token is read-only by construction | 2.3 | operator | – | ● | ● | `.env.compose` |
| `people invite`, `people list` | invitation-based registration under the `local` identity row; 7-day invites, 30-day sessions, 12-character passwords | 2.3 | operator | – | ● | ○ | `people list` |
| OIDC | issuer, PKCE, group mapping; an unverified email refused unless declared | 2.3 | security | – | – | ● | `/auth/login` |
| authorisation | `may(subject, project, scope)`; an empty allowlist means nobody; `admins` and `product.admins` on the project | 2.3 | operator | ● | ● | ● | `policy/authz.py` |
| the action layer | every capability reachable from the CLI (`act`), the panel and a channel, implemented by none of them; `actions` lists the catalogue | 4 | operator | ● | ● | ● | `openfactory actions` |
| confirmations | a click that names what was shown; a typed yes read by a model; one confirmation from somebody who may; an unauthorised yes does not consume the proposal | 4 / 7 | product owner | – | ● | ● | the panel |
| the operator's conversation and staged suggestions | the tech-lead thread kept server-side; a suggestion lives 12 hours and retires as superseded, answered or expired, always with its reason | 4 | operator | ● | ● | ● | `/api/messages/<project>` |
| conversation memory | verbatim record, per-thread working memory, 180-day retention, per-person threads, `forget-conversations` | 6.3 | operator | ○ | ● | ● | `project forget-conversations` |
| the open-loop ledger | what the factory asked and is waiting to hear; closed by observation | 4 | operator | ○ | ● | ● | `/api/loops/<project>` |

## H. Product and requirements

| capability | what it is | phase | owner | L | S | E | evidence |
|---|---|---|---|---|---|---|---|
| the context repository | requirements, glossary, domain facts, the module map; `sources:` lists the implementing repositories | 3.2 / 7 | product owner | – | ○ | ● | `.openfactory/product.yaml` |
| three declarations that agree | registry, context repository, source manifests; a mismatch is a sentence naming both sides | 7 | implementer | – | ○ | ● | `product init` |
| the requirement lifecycle | proposed → accepted → broken down → queued → delivered → released; `product accept`, `break-down`, `promote`, `release`, `drop` | 7 | product owner | – | ○ | ● | the context repository's history |
| the brownfield baseline | `product baseline`: observations with evidence `asked`, `tested`, `code`; one pull request; coverage declared; accepting files no work | 7 | product owner | – | ○ | ● | the pull request |
| `product status`, `requirements`, `pending`, `parked`, `queue`, `ask` | the product surface from the terminal | 7 | product owner | – | ○ | ● | their output |
| defects, learned facts, decisions | filed and recorded through confirmation; a decision asked for is chased once at 48 hours | 7 | product owner | – | ○ | ● | the board, the context repository |
| card correction | replaces what a card says before the factory takes it up; refused after | 4 | product owner | – | ○ | ● | the card's comment |
| delivery acceptance | the client is asked whether it worked; silence never counts | 7 | product owner | – | ○ | ● | the message |
| weekly triage | only what is new; the rest a count | 7 | product owner | – | ○ | ● | the message |

## I. Knowledge

| capability | what it is | phase | owner | L | S | E | evidence |
|---|---|---|---|---|---|---|---|
| the module map | `modules.yaml` + `manifest.yaml`, per repository, deterministic; Python, TypeScript/JavaScript, C# read; others structural | 3.2 | implementer | ○ | ● | ● | `.okf/repos/<repo>/` |
| freshness | judged on the job's own checkout from the sources; a map that cannot be proven fresh is not served | 4 | – | ○ | ● | ● | the journal's arm |
| the A/B readout | per arm n, mean, median for cost, wall-clock, turns; no verdict computed | 4 | operator | – | ○ | ● | `/api/metrics` |
| the concept gate | `okf_gate` off, advise, enforce; stance green, amber, dark | 2.5 | architect | – | ○ | ○ | `knowledge gate` |

## J. Operations, security, maintenance

| capability | what it is | phase | owner | L | S | E | evidence |
|---|---|---|---|---|---|---|---|
| credential boundaries | container box by allow list (harness credential + `box.env`); worktree box by deny list, with the published set of thirteen names a worktree workload can read | 2.3 | security | ● | ● | ● | `SECURITY.md` |
| the GitHub App permission table | one home; Checks: Read; Administration write only for creating a context repository; never `workflows` | 2.3 | security | – | ● | ● | `docs/setup/github.md` |
| branch-protection standard | PR required, zero required reviews, linear history, no force push, auto-merge on, head branches deleted | 2.6 | operator | – | ● | ● | the forge |
| egress | harness endpoint, forge and tracker, package registries; `box.network`; a re-signing CA trusted in the client's image; full outbound by default | 2.4 | security | ○ | ○ | ● | the security checklist |
| the panel's token | unset means open; per-person tokens; OIDC | 2.3 | operator | ○ | ● | ● | `.env.compose` |
| secrets in one file | `.env.compose` `0600`, git-ignored, `--env-file`; a secret store on a cloud | 2.3 | operator | ● | ● | ● | `ls -l` |
| the Docker socket trade | root-equivalent on the host; the same trade every compose stack that mounts it makes | 1.3 / 2.1 | security | ○ | ● | ● | the design record |
| journals and the Logs page | every run this deployment made, filterable, each with its own address; a running job streams | 4 | operator | ● | ● | ● | `/logs` |
| the engine's UI | every workflow, retry, activity | 4 | operator | ● | ● | ● | `TEMPORAL_UI_PORT` |
| retention | engine 30 days (only raised), journals until the volume goes, conversations 180 days, resume 7 days, thread 500 rows, suggestion 12 hours | 2.9 / 6.3 | operator | ● | ● | ● | `docker-compose.yml` |
| the backup set | registry, environment, board db, metrics db, approvers, journals, proofs, engine database | 6.4 | operator | ○ | ● | ● | the calendar |
| the impediment board | the factory files its own impediments on its own board and closes them by observation | 4 | operator | – | ○ | ● | `factory_board` |
| the API budget | the tracker's quota watched; the poller pauses before it runs out | 4 | operator | – | ● | ● | `doctor` `api_budget` |
| dependency cache | `box.cache_volume` per project, with the package-manager variables in `box.env` | 2.4 | architect | – | ○ | ○ | the registry |
| security policy | private reporting, 72-hour acknowledgement, the four vulnerability classes, pre-1.0 fixes on `main` only | 6.5 | security | ● | ● | ● | `SECURITY.md` |
| conformance | `conformance <project>` (manifest complete) and `conformance-adapter <kind> <target>` (a port satisfied, findings by name) | 3.2 / 7 | implementer, developer | ● | ● | ● | their exit codes |
| the house test rules | ruff, both orders, `-n auto`, mutation-proven guards, refusals with a remedy | 7 | developer | – | – | – | `CONTRIBUTING.md` |

## Known limitations

From [STATUS.md](../STATUS.md). These must not be presented to customers as available.

- The panel cannot see local jobs on a compose deployment where journals are written beside the
  customer's repository (#67).
- A local-path registration on compose requires the repository on the worker's disk.
- One deployment serves one GitHub organisation (#64).
- `box.image` is honoured only by the container box; on a remote box it raises.
- The box proof gates pickup only on the container box; on `worktree` and remote boxes it is run
  manually.
- `setup:` and `validate:` are shell strings; only the exit code is read.
- The promotion chain runs only on a remote box; a local box uses the deploy watch.
- Cross-repository ordering does not exist.
- One `base_branch` only; a develop-and-main flow cannot be expressed.
- GitLab and Bitbucket are not shipped; an add-on can add them.
- The knowledge map reads Python, TypeScript/JavaScript and C#.

Deliberately not built, and to be stated to every customer: production is never triggered from
chat; the bot never receives `workflows` permission; review is advisory by default; one job at a
time deployment-wide.
