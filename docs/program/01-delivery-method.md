# OpenFactory Delivery Method

This document defines the process that certified partners follow when they deploy OpenFactory
for a customer. It is the reference for the role certifications (a person is certified on the
phases they perform), for partner audits (a partner is audited on the artefacts each phase
produces) and for hosting conformance (a hosting provider is audited on phases 4 to 6).

The method wraps the platform's own onboarding path ([ONBOARDING.md](../ONBOARDING.md)) with the
steps a customer organisation needs before and after it: qualification, assessment, design,
pilot, hand-over, support and maintenance. It does not restate how the platform behaves. Where a
phase depends on platform behaviour, it links to the document that describes it.

## Phases

| phase | outcome | primary artefact |
|---|---|---|
| 0. Qualify | decision to run an assessment | Qualification note |
| 1. Assess | readiness findings and a costed proposal | Assessment report |
| 2. Design | every deployment decision recorded and signed | Deployment design record |
| 3. Implement | a proven deployment, a completed pilot, a hand-over | Pilot report, Operations runbook |
| 4. Operate | day-to-day operation to a defined cadence | Operator's log |
| 5. Support | incidents handled to a support tier | Support ticket record |
| 6. Maintain | the deployment kept current, proven and recoverable | Maintenance calendar |
| 7. Expand and renew | scope grown on evidence; annual review | Updated design record |

Each phase below lists entry criteria, activities, artefacts, evidence and exit criteria. The
evidence column names the platform command whose output is attached to the sign-off. Profile
differences (Light, Standard, Enterprise) are noted at the end of each phase; see
[02-profiles.md](02-profiles.md) for the profile definitions.

Three rules apply to every phase:

1. The platform proposes; the customer reviews and merges. A partner does not merge into a
   customer repository.
2. Nothing is picked up before the box is proven, and no agent spend is committed before a
   costed rehearsal. The pilot has a budget cap.
3. Every exit criterion is a command output or a signed document, not a status update.

---

## Phase 0: Qualify

**Purpose.** Decide whether an assessment is worth running.

**Entry criteria.** A first contact with the organisation.

**Activities.** Answer the four qualification questions:

| question | why it matters | disqualifying answer |
|---|---|---|
| Is there a repository with a test command that runs on a clean clone? | The quality floor requires `validate.test`. There is no default. | No tests, and no plan to add them. |
| Can the coding agent reach its model provider from where the factory would run? | The agent is a remote service. Air-gapped networks are not supported ([architecture §5](../architecture.md)). | No route and no gateway the security team will approve. |
| Which forge and tracker are in use? | The core ships GitHub, Jira and Azure DevOps. Others require an add-on. | Another forge, with no budget for an add-on. |
| Who will review and merge the pull requests? | The factory produces reviewed pull requests. Someone must read them. | Nobody with the time. |

**Artefact.** [Qualification note](templates/00-qualification-note.md): the four answers, the
suggested profile, the assessment scope and price.

**Exit criteria.** The sponsor agrees to an assessment with a defined scope and a named customer
contact, or the note records why not.

**Profiles.** On Light, the qualification is a self-check by the person who will run the
deployment.

---

## Phase 1: Assess

**Purpose.** Establish whether and how the factory can work on the customer's codebase, what it
will cost, and what the customer must change first.

**Entry criteria.** Qualification note. Read access to the repositories in scope. Two hours with
the developers who maintain them.

### 1.1 Organisation

Record on the [Readiness scorecard](templates/01-readiness-scorecard.md):

- How work flows today: where tickets originate, who writes acceptance criteria, how changes
  reach production, who may merge, current branch protection.
- Named people for each role: operator, requesters, reviewers, product owner, release
  approvers.
- Constraints: data residency, egress policy, whether a bot may create repositories, whether a
  GitHub App may be installed, approved model routes (direct, Bedrock, Vertex, gateway), budget
  authority for agent spend.
- The sponsor's objective (throughput, cost per ticket, backlog age, on-call load). The pilot
  targets in 3.6 are derived from this.

### 1.2 Codebase

For each repository, on a checkout, with its developers present, run the platform's read-only
session:

```bash
openfactory env read <path>       # proposed manifest, with file, line and confidence per field
openfactory env context <path>    # survey: modules by churn, entry points, invariants, open questions
```

Record:

| finding | consequence |
|---|---|
| The real `setup:` and `validate.test` commands, and whether they pass on a clean clone | The box proof (3.3) runs these. A suite that only passes on one machine is the first work item. |
| Stack, and whether the stock box image carries its toolchain | A stack outside the stock image needs a customer image (`box.image`), designed in 2.4. |
| CI: which workflows exist, which are disabled, which checks run on every PR | Required status checks (2.6). `onboard` does not propose commands found only in disabled workflows. |
| Repository shape: monorepo with components, or one product across repositories | `components:` or one board with cards that carry their repository ([ONBOARDING §10](../ONBOARDING.md)). |
| Test suite side effects | A suite that writes to shared systems cannot run in the rehearsal without `--no-gates` and cannot be a gate until isolated. |
| Existing documentation (ADRs, architecture, guidelines) | Targets for `docs.constraints`, `docs.architecture`, `docs.guidelines`. |
| Module map coverage | The map reads Python, TypeScript/JavaScript and C#. Other stacks get a structural map or none. |
| High-risk areas | `risk: high` components (auth, billing, migrations, infrastructure) stay human-gated under any merge policy. |

### 1.3 Tooling and security

- Forge and tracker access path: organisation or personal account; GitHub App or PAT. The App
  permission table is in [docs/setup/github.md](../setup/github.md). Azure DevOps uses one PAT
  ([docs/setup/azure-devops.md](../setup/azure-devops.md)).
- Where the factory will run: laptop, server, cloud account, cluster. The Docker socket mount
  must be accepted in writing, or a remote box add-on used.
- Egress: the harness endpoint, the forge and tracker, and package registries. Note any proxy,
  TLS-intercepting CA or private registry ([architecture §5](../architecture.md)).
- Identity for the panel: per-person tokens, or OIDC on Enterprise.
- Where secrets will live and who can read them.

On Enterprise, complete the [Security review checklist](templates/03-security-review-checklist.md)
with the customer's security team.

### 1.4 Cost estimate

| line | basis |
|---|---|
| Agent spend per merged ticket | The rehearsal cost (3.4) on a synthetic ticket, then the pilot median (3.6). The published reference in [knowledge-layer.md](../knowledge-layer.md) is one codebase, n = 8. |
| Infrastructure | A host on Light; a small always-on worker plus ephemeral boxes on a cloud. |
| People | Operator hours per week (phase 4), reviewer time per PR, partner fees. |

### 1.5 Report

**Artefact.** [Assessment report](templates/02-assessment-report.md): scorecard, per-repository
findings, recommended profile and shape, prerequisite work with owners, risks, cost estimate,
proposed pilot with targets.

**Exit criteria.** The sponsor accepts the report and funds design and implementation, or the
report lists the prerequisites and the engagement pauses with a review date.

**Profiles.** Light: 1.1 is a conversation, 1.2 is the two commands, the report is one page.
Enterprise: 1.3 includes the signed security checklist; 1.4 includes model-route and cloud costs.

---

## Phase 2: Design

**Purpose.** Record every deployment decision before installation so that implementation is
execution and the operator inherits a document.

**Entry criteria.** Accepted assessment report.

**Artefact.** [Deployment design record](templates/04-deployment-design-record.md) with the
sections below. Each entry is a decision and its reason.

| section | contents |
|---|---|
| 2.1 Shape and topology | Door (one machine, compose on one host, compose on a server, cloud add-on). Location of worker, panel, engine and boxes. Ports. `OPENFACTORY_WORK_DIR`. Disk budget (about 8 GB for images). Named volumes. |
| 2.2 Provider axes | One row per axis from the [STATUS table](../STATUS.md): tracker, board, forge, CI observer, harness per role with `model:`, reviewer engine, channel, sandbox, telemetry sink, identity. Only kinds the deployment will carry; unknown kinds refuse at startup. |
| 2.3 Credentials | For each credential: holder, location, permitted actions, which process can read it, rotation schedule. Follows the rule in [operations.md](../operations.md): the box holds only the harness credential; the host holds everything that can touch the board, the remote or a merge. |
| 2.4 The box | Stock image or customer image; toolchain the proof pins; `box.network`; `box.cache_volume` and package-manager variables; CA trust for re-signing networks; who builds and rebuilds a customer image. |
| 2.5 Manifest and quality floor, per repository | `setup:`, `validate:` (`test` required, no default; `security` inherited unless declared; `lint`, `type` where present), `advisory: true` gates, `components:` with `risk:`, `docs:` roles, `knowledge_map`, `e2e_label` and `e2e_workflow`, ticket language. |
| 2.6 Merge policy, branch protection, CI | `merge_policy: human` for the pilot. Conditions for `auto` (phase 7). `review_mode`. The branch-protection standard in [operations.md](../operations.md): PR required with zero required human reviews, linear history, auto-merge enabled, head branches deleted on merge, App granted Checks: Read. Required status checks chosen from checks that run on every PR and are deterministic. |
| 2.7 After the merge | Nothing, `post_merge_deploy:`, or `environments:` plus `promote:` with a named production approver. The stage a person validates (`validate_with: product`) and its `url:`. A promotion chain runs only on a remote box; a local box uses the deploy watch. |
| 2.8 Product role | On or off. Context repository: existing, created by the factory, or created by the customer's process and declared. The three declarations in [product-role.md](../reference/product-role.md). Admins. Baseline adoption plan. |
| 2.9 Operations | Operator and backup. Cadences (phase 4). Log locations. Retention. Backup set (6.4). Upgrade policy (6.1). Support tier and escalation path (phase 5). |
| 2.10 Cost governance | Monthly budget. Token pool. `OPENFACTORY_MAX_CONCURRENT_JOBS` (default 1). `effort_budget_turns`, `repair_max_attempts` per project. Who is notified on budget exhaustion. Weekly cost review owner. |

Credential summary by profile:

| credential | Light | Standard and Enterprise |
|---|---|---|
| Coding agent | The person's own login | Subscription token or API key in the secret store; token pool where limits are hit ([rotation-and-retention.md](../rotation-and-retention.md)) |
| Forge | None (local repository) | PAT for trials; GitHub App for production use, with the documented permission table and never `workflows` |
| Tracker | None | The App, or the classic PAT a personal-account board requires; the Azure DevOps PAT |
| Panel | Open on a laptop | `OPENFACTORY_PANEL_TOKEN` or per-person tokens; OIDC on Enterprise |
| Product | Not used | Per-person entries in `OPENFACTORY_PRODUCT_TOKENS`; ids listed in `product.admins` |
| Release approvers | Not used | `openfactory approver add` (scrypt-hashed), or `OPENFACTORY_APPROVERS` from the secret store |
| `box.env` | As the setup requires | The explicit allow list of variables the container box may receive |

**Exit criteria.** The record is reviewed by the operator and the implementer, and on Enterprise
by the customer's security reviewer. Every open question has an owner and a date. On Enterprise
the security review is signed before phase 3.

**Profiles.** Light: the record is the annotated environment file plus the manifest, with a short
page for 2.3, 2.6 and 2.9.

---

## Phase 3: Implement

**Purpose.** Install the deployment as designed, onboard each project, prove and rehearse it,
run a pilot, and hand over.

**Entry criteria.** Signed design record. Credentials obtained. Prerequisite work from the
assessment done.

### 3.1 Install

| profile | steps |
|---|---|
| Light, one machine | `pip install -e '.[runtime]'`, `openfactory init`, `openfactory up` ([one-machine.md](../setup/one-machine.md)) |
| Light or Standard, compose | `curl -fsSL https://openfactory.digital/install.sh \| sh`, or the pinned commands in the [README](../../README.md) with checksums verified; `openfactory init` writes `.env.compose` |
| Enterprise | The compose stack on the designed host, or the add-on's reference deployment. Version pinned in `.env.compose`. Images from the registry named in the design. Panel behind the designed identity. |

Evidence: `openfactory preflight` reports nothing missing; the panel answers; `docker compose ps`
shows the stack healthy. Record the installed version in the design record.

### 3.2 Register and onboard

Run on the worker. The compose stack keeps its own registry; a project registered on a laptop is
not visible to it.

```bash
openfactory project init <name> <clone-url>
openfactory doctor <name>
openfactory onboard <name> --yes [--source owner/repo ...]
```

`onboard` reads the manifest from the code, proves it in the real box, generates the module map,
creates or uses the context repository, proposes the backfill, and opens one pull request per
repository with the proof result in the body. The customer reviews and merges. Check
`validate.test` most carefully. The `docs_repo:` line in each source repository is written by the
customer, not by the platform; it is on the implementer's checklist.

When the developers are available, the manual session (`env read`, `env apply --yes`) may replace
or precede `onboard` for the manifest, and `env context --ask --write` for the backfill.

Evidence: merged pull requests; `doctor` reports the manifest as merged.

### 3.3 Prove the box

```bash
openfactory box prove <name> [--repo owner/repo]
openfactory box status <name>
```

One proof per repository. A failed proof on a command that needs changing is normal: edit the
manifest, commit, re-prove. On the container box, no card is picked up until every repository is
proven. On a remote box add-on the proof does not gate pickup and must be run by hand; the design
record names who runs it after each change ([STATUS.md](../STATUS.md)).

Evidence: `box status` green per repository, with the pinned toolchain.

### 3.4 Check and rehearse

```bash
openfactory env check <name>                        # exit 0 only when pickup is unblocked
openfactory env rehearse <name>                     # prints the cost; runs nothing
openfactory env rehearse <name> --yes [--no-gates]  # full loop on a synthetic ticket in a throwaway clone
```

The rehearsal touches no tracker, branch, pull request or board. Its cost is the first entry in
the cost governance section.

Evidence: rehearsal output attached to the implementation log.

### 3.5 First ticket

A small real card with an objective and acceptance criteria, moved to the pickup column, under
`merge_policy: human`. Watch it on the panel through spec, box, code, gates, pull request and
independent review. The customer merges. Walk the reviewers through the pull request body.

Evidence: the merged pull request; the card in Done; the job's Logs page.

### 3.6 Pilot

Ten to thirty real tickets over two to six weeks, chosen by the customer's product owner, under
human merge. Measure against the targets set in the assessment:

| measure | source |
|---|---|
| Tickets picked up, merged, parked, skipped | Panel floor; Logs page |
| Median time to pull request | Cost dashboard |
| Median agent cost per merged ticket | Cost dashboard |
| Park rate by class (transient, credential, environment, requirement, code, unknown) | Tech-lead escalations on the cards |
| Review rejection rate; repair passes | Pull request bodies |
| Operator hours per week | Operator's log |

**Artefact.** [Pilot report](templates/05-pilot-report.md): results against targets, what parked
and why, manifest changes made, recommendation (go, go with changes, no-go).

### 3.7 Hand-over and go-live

Complete the [Operations runbook](templates/06-operations-runbook.md) from the design record and
the pilot findings. The operator runs one week with the implementer available. Support (phase 5)
is activated.

**Exit criteria (go-live gate).** `doctor` green on every project. Every proof current. Pilot
report accepted. Runbook handed over. Support contract active. The backup set (6.4) taken once
and restored once.

**Profiles.** Light: the pilot is five tickets in one week; hand-over is the operator reading the
runbook. Enterprise: 3.1 is performed on a non-production deployment first; the pilot runs per
project with a security sign-off on the first pull request; hand-over includes a DR test.

---

## Phase 4: Operate

**Purpose.** Run the deployment so that every parked card is answered and cost stays within
budget.

Operator cadences (recorded in the runbook):

| cadence | activity |
|---|---|
| Continuous | Panel attention bar: cards in Needs Action, pull requests waiting for merge, the production gate. |
| Daily | Logs page for the previous day. Answer parked cards on the card and return them to TO-DO. Token-pool state on the panel. |
| Weekly | Cost dashboard against budget. Recurring failures reported by the tech lead. `doctor` per project. `box status` per repository. API budget line. |
| Monthly | Release notes reviewed; upgrade decided (6.1). Credentials near expiry rotated. Retention and disk checked. |
| Quarterly | Merge-policy review (phase 7). Manifest review with the developers. Runbook re-read. |

Division of responsibility, per [agents.md](../agents.md):

- The factory resolves transient and credential failures itself (wait, rotate, resume).
- Environment, code, requirement and unknown failures park with a named person and a proposed
  decision. The operator routes them.
- Production is released only from the panel by a named approver with a password.
- A card labelled `factory-test` is refused on a customer board. The factory's own test cards
  run on the partner's test-bench project.

Requesters write an objective and acceptance criteria on every card, answer refinement questions
on the card, then move it back to TO-DO. Reviewers read the pull request body (validations,
review, touched components, cost) before the diff.

Evidence: the operator's weekly log; the cost dashboard history; no card in Needs Action older
than the support tier's response time.

---

## Phase 5: Support

**Purpose.** Handle the questions and failures the platform escalates within a committed time,
and route platform defects to the maintainers.

The severities, tiers, response times and process are defined in
[06-support-and-maintenance-standard.md](06-support-and-maintenance-standard.md). The method
requires:

1. A named first line: the operator on Light; a partner support desk on Standard and Enterprise.
2. Severities mapped to the platform's failure classes as the standard defines them.
3. The tech lead's escalation text as the starting point of every ticket.
4. An escalation path to the maintainers. Platform defects are filed with the journal excerpt
   and the version. Security findings follow [SECURITY.md](../../SECURITY.md).
5. A ticket record with class, remedy and outcome. Recurring entries become maintenance items.

---

## Phase 6: Maintain

**Purpose.** Keep the deployment current, proven and recoverable.

### 6.1 Upgrades

- Currency: a supported deployment runs the current release or the previous one, per the
  [release policy](06-support-and-maintenance-standard.md#releases-and-currency).
- Procedure: re-run the installer (compose), or `git pull && docker compose --env-file
  .env.compose up -d --build` for a checkout. Move `OPENFACTORY_VERSION` deliberately. `doctor`
  reports the running build on its first line.
- After every upgrade: `doctor` on every project, `box status` on every repository (a rebuild
  that leaves the toolchain unchanged does not expire the proof), one rehearsal, and any
  behaviour change listed in the release notes applied.
- Do not upgrade while a job holds the floor. Do not skip a minor release.

### 6.2 Proofs and credentials

Re-prove after any change to `setup:`, `validate:`, the toolchain or a customer image digest.
Rotate credentials on the schedule in the design record. GitHub App keys may be regenerated at
any time; recreate the stack afterwards.

### 6.3 Retention and disk

Engine history: 30 days by default, only ever raised. Journals: until the volume is deleted.
Conversations: 180 days. Resume directory: 7 days. Check `docker system df` monthly.

### 6.4 Backup and recovery

Back up the state that has no other copy:

| item | location |
|---|---|
| Registry | `OPENFACTORY_REGISTRY` |
| Environment file | `.env.compose` or the secret store |
| Local board and pull requests (one-machine door) | SQLite file beside the registry |
| Metrics and conversation store | SQLite sink under `OPENFACTORY_STATE_DIR` |
| Approvers | `~/.openfactory/approvers.json` or `OPENFACTORY_APPROVERS` |
| Journals and proofs | Named volumes (`OPENFACTORY_LOG_DIR`) |
| Engine database | The compose stack's `temporal` database volume |

Customer repositories, boards, the context repository and the module map are not in the set;
they live in the forge. Test a restore at go-live and after every major upgrade: restore onto a
clean machine and confirm `doctor` green.

### 6.5 Security

Read [SECURITY.md](../../SECURITY.md) on every release. Review the `box.env` allow list when a
manifest changes. Keep the panel behind a token or identity on any reachable host. Apply security
advisories within the support tier's window.

Evidence: the [maintenance calendar](templates/07-maintenance-calendar.md) with dated rows;
post-upgrade `doctor` and `box status` output; the date of the last restore test.

---

## Phase 7: Expand and renew

- **Move to `merge_policy: auto`** only after a pilot under human merge, with every area the
  customer wants reviewed marked `risk: high`. The conditions `auto` checks are in
  [ONBOARDING §11b](../ONBOARDING.md). Not in the first month.
- **Enable the product role** with a named product owner, a context repository, per-person
  tokens, and a baseline adopted as `observed` and accepted by a person
  ([product-role.md](../reference/product-role.md)).
- **Add projects** with `project init`, `onboard`, `box prove`, and a new row in the design
  record. One deployment serves one GitHub organisation; a second organisation needs a second
  deployment.
- **Introduce multi-repository products, e2e workflows and promotion chains** one at a time,
  each designed in phase 2 and proven.
- **Raise `OPENFACTORY_MAX_CONCURRENT_JOBS`** only after the customer accepts the loss of
  one-job-at-a-time dependency safety. There is no per-project cap.
- **Annual review:** re-measure the pilot metrics for the year, re-sign the design record,
  re-select the support tier, update the list of certified people on the engagement.

---

## Roles and responsibilities

| role | typically | certification |
|---|---|---|
| Sponsor | Customer budget owner | None; signs the gates |
| Solution architect | Partner lead | OpenFactory Certified Solution Architect |
| Implementer | Partner engineer | OpenFactory Certified Implementer |
| Operator | Customer platform engineer, or hosting partner | OpenFactory Certified Operator |
| Security reviewer | Customer security team; the architect on smaller profiles | Solution Architect (security domain) |
| Product owner | Customer product lead | OpenFactory Certified Product Owner |
| Requester / reviewer | Customer developers | OpenFactory Certified Associate |
| Support engineer | Partner desk | Operator, plus the support standard |
| Release approver | Named customer person with a password | Associate; listed in `prod_approvers` |
| Add-on developer | Whoever writes an adapter the core lacks | OpenFactory Certified Developer |
| Trainer | Whoever teaches the courses | OpenFactory Certified Trainer |

On Light one person may hold several roles. Each role must still be assigned to a named person.

### RACI

R = responsible, A = accountable, C = consulted, I = informed.

| phase | sponsor | architect | implementer | operator | security | product owner | developers |
|---|---|---|---|---|---|---|---|
| 0 Qualify | A | R | – | – | – | C | C |
| 1 Assess | A | R | C | C | C | C | C |
| 2 Design | A | R | C | C | C (A for 2.3 on Enterprise) | C | I |
| 3 Implement | A | C | R | C | C | C | R (merge) |
| 4 Operate | I | I | C | R/A | I | R (cards) | R (review) |
| 5 Support | I | C | C | R (first line) / desk | C | I | I |
| 6 Maintain | I | C | C | R/A | C | I | I |
| 7 Expand | A | R | C | C | C | R | C |

## Evidence summary

A partner audit requests the items in this table and nothing else.

| phase | evidence |
|---|---|
| 0 | Qualification note |
| 1 | Assessment report; `env read` and `env context` output per repository |
| 2 | Signed design record |
| 3 | `preflight` and `doctor` output; merged onboarding pull requests; `box status` per repository; rehearsal output; first ticket's pull request; pilot report; runbook; go-live gate |
| 4 | Operator's weekly log; cost dashboard; Needs Action age |
| 5 | Support ticket record with classes and remedies |
| 6 | Maintenance calendar; post-upgrade `doctor` and `box status`; last restore test |
| 7 | Annual review; re-signed design record |

## Related documents

- [01a-feature-coverage.md](01a-feature-coverage.md): every supported capability mapped to the
  phase, role and profile that introduce it.
- [02-profiles.md](02-profiles.md): profile definitions and control catalogue.
- [06-support-and-maintenance-standard.md](06-support-and-maintenance-standard.md): severities,
  tiers, release policy, hosting standard.
- [templates/](templates/): the artefacts named above.
