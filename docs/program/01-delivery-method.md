# The OpenFactory Delivery Method

**The process a certified implementation follows, from the first conversation to the fourth year
of operation.** Certification needs something to certify against: a person is certified for
performing a phase of this method on a real deployment, a partner is certified for running the
whole of it repeatably, and a hosted service is certified for the operate-and-maintain half. The
method is the platform's own onboarding path ([ONBOARDING.md](../ONBOARDING.md)) with the parts
around it that a client organisation needs and the platform cannot supply: the decision to start,
the design of the deployment, the people, the money, the support desk, and the years after go-live.

Seven phases. Each has entry criteria, activities, artefacts, the platform commands that evidence
it, an exit gate, and what changes on the three [deployment profiles](02-profiles.md): **Light**
(one team, one machine or one small stack), **Standard** (a hosted forge, a real board, several
people on one panel) and **Enterprise** (a security review, a cloud or a hardened stack, several
projects, a product owner, a promotion chain).

```
 0 Qualify ─► 1 Assess ─► 2 Design ─► 3 Implement ─► 4 Operate ─► 5 Support ─► 6 Maintain
                                          │              ▲                          │
                                          │              └── 7 Expand & renew ◄─────┘
                                          ▼
                                   go-live gate (the pilot's numbers)
```

Three rules hold on every profile, and a certified implementer is examined on them:

1. **Propose, then be corrected.** The platform reads the repository and proposes the manifest,
   the module map and the context. A person who knows the codebase corrects it. The method never
   writes into a client repository without a review, because the platform does not either.
2. **Nothing is spent before it is proven.** The box is proven, the rehearsal is costed, the
   first ticket is small, and the pilot has a budget. A certified implementation can name what it
   spent at every step.
3. **Evidence is a command's output, not a slide.** Every exit gate below names the command whose
   output is attached to the sign-off. `openfactory doctor` green is a fact; "the environment is
   ready" is a sentence.

---

## 0 · Qualify

**Purpose:** decide in one conversation whether this organisation should run the assessment at
all, so that nobody pays for an assessment of a codebase the factory cannot work on.

**Entry:** a first contact — a request, a lead, an internal proposal.

**The four questions.** Each has a disqualifying answer; a "no" on any of them stops here with a
written reason, and a "not yet" names what would change it.

| question | why it decides | disqualifying answer |
|---|---|---|
| Is there a repository with a test command that a stranger can run? | the quality floor requires `validate.test`; there is no default that tests nothing | "the tests only run on Maria's machine" is *not yet*; "there are no tests and there will not be" is *no* |
| Can the coding agent reach its vendor from where the factory would run? | the agent is a remote paid service; an air-gapped network cannot run this ([architecture §5](../architecture.md)) | no route to the harness endpoint, and no gateway the security team will open |
| Where do the tickets and the code live? | the core ships GitHub, Jira and Azure DevOps; another forge is an add-on someone must write | GitLab, Bitbucket or a custom tracker with no budget for an adapter |
| Who will read the pull requests? | the factory returns reviewed pull requests; a team that will not read them has bought a queue with nobody at the end | no engineer with the time to merge |

**Artefact:** a one-page **Qualification note** ([template](templates/00-qualification-note.md))
with the four answers, the profile it suggests, and the assessment scope.

**Exit:** the sponsor agrees to an assessment with a named scope (which repositories, which
teams) and a named client counterpart.

**Light profile:** the four questions are asked and answered by the same person, often the one
who will run the factory; the note is an email.

---

## 1 · Assess

**Purpose:** find out, with the platform's own tools, whether and how the factory can work on
this codebase, what it will cost, and what the organisation has to change first. The output is a
report a sponsor can decide on and an architect can design from.

**Entry:** the qualification note; read access to the repositories in scope; two hours with the
developers who know them.

### 1.1 The organisation

The assessor interviews and records, on the [Readiness scorecard](templates/01-readiness-scorecard.md):

- **The flow of work today.** Where tickets are born, who writes acceptance criteria, how a
  change reaches production, who may merge, what the branch protection is.
- **The people.** Who will own the deployment (operator), who will write cards (requesters), who
  will read pull requests (reviewers), who owns the product (product owner), who approves a
  production release (approvers). The method needs a name against each; "the team" is not a name.
- **The constraints.** Data residency, egress policy, whether a bot may create repositories,
  whether a GitHub App may be installed on the organisation, which model providers are approved
  (Anthropic direct, Bedrock, Vertex, a corporate gateway), and the budget authority for agent
  spend.
- **The reason.** What the sponsor expects to change: throughput, cost per ticket, on-call
  toil, a backlog that never moves. The pilot's numbers (§3.6) are chosen against this.

### 1.2 The codebase

Per repository in scope, on a checkout, with the developers in the room, using the platform's
read-only session — it writes nothing:

```bash
openfactory env read <path>          # the manifest the platform would propose, field by field, with
                                     # the file and line each was read from and how sure it is
openfactory env context <path>       # the survey: modules by churn, entry points, invariants,
                                     # areas that change and that no test names, open questions
```

The assessor records, per repository:

| finding | what it decides |
|---|---|
| the real `setup:` and `validate.test` commands, and whether they ran green on a clean clone | the box proof (§3.3) will run exactly these; a suite that cannot run on a clean machine is the first work item |
| the stack, and whether the stock box image carries its toolchain | a stack outside the stock image (`.NET`, Java, a private toolchain) needs `box.image` — the client's own image, designed in §2 |
| the CI that exists, which of it is disabled, which checks run on every PR | the merge gates and the required status checks (§2.6); `onboard` demotes commands found only in disabled workflows |
| the shape: monorepo with components, or a product across repositories | `components:` vs one board with cards that carry their repository ([ONBOARDING §10](../ONBOARDING.md)) |
| the test suite's side effects | a suite that talks to a shared database cannot run in the rehearsal without `--no-gates` and cannot be a gate until it is isolated |
| documentation: ADRs, architecture pages, guidelines | what `docs.constraints`, `docs.architecture` and `docs.guidelines` will point at |
| the module map's coverage | the map reads Python, TypeScript/JavaScript and C#; other stacks get a structural map or none |
| protected paths and high-risk areas | `risk: high` components (auth, billing, migrations, infrastructure) that stay human-gated under any merge policy |

### 1.3 The tooling and the security posture

- **Forge and tracker access:** organisation vs personal account, whether a GitHub App can be
  created and installed (the [permission table](../setup/github.md) is the one home of what it
  needs), or a PAT is the only path (Azure DevOps: [one PAT for both](../setup/azure-devops.md)).
- **Where the factory runs:** a laptop, a server, a cloud account, a Kubernetes cluster. The
  Docker socket trade is explained and accepted in writing, or a remote box (the runner the `openfactory-aws`
  add-on carries, or another add-on's) is required.
- **Egress:** the three destinations the factory necessarily reaches — the harness endpoint,
  the forge and tracker, and whatever `setup:` installs — and whether a proxy, a TLS-intercepting
  CA or a private package registry sits in the way ([architecture §5](../architecture.md)).
- **Identity:** who signs into the panel, and how — a token per person, or OIDC against the
  organisation's identity provider on Enterprise.
- **Secrets:** where `.env.compose` or its equivalent will live, who may read it, how it is
  rotated.

### 1.4 The money

A costed estimate, in three lines, from the platform's own numbers and the client's ticket mix:

| line | how it is estimated |
|---|---|
| agent spend per merged ticket | the rehearsal's printed cost (§3.4) on a synthetic ticket, then the pilot's median (§3.6); the [knowledge layer's measurement](../knowledge-layer.md) is the only published reference and it is one codebase, n = 8 |
| infrastructure | nothing beyond a machine on Light; a small always-on worker and ephemeral boxes on a cloud |
| people | an operator's hours per week (§4), the reviewers' time per pull request, the partner's implementation and support fees |

### 1.5 The report

**Artefact:** the **Readiness assessment report** ([template](templates/02-assessment-report.md)):
the scorecard, per-repository findings, the recommended profile, the deployment shape, the risks
with owners, the work the client must do before implementation (a runnable test command is the
usual one), the costed estimate, and a proposed pilot with its success numbers.

**Exit:** the sponsor accepts the report and funds the design and implementation, or the report
says what has to be true first and the engagement pauses with a date.

**Light profile:** §1.1 is a conversation, §1.2 is the two commands, §1.3 is "my laptop, my
login", §1.4 is the rehearsal's price. The report is a page.

**Enterprise profile:** §1.3 becomes a security questionnaire the client's security team signs
([template](templates/03-security-review-checklist.md)); §1.1 records every named person against
an identity the panel will recognise; §1.4 includes the model route's cost and the cloud's.

---

## 2 · Design

**Purpose:** write down every decision the deployment embodies before anything is installed, so
the implementation is an execution and the operator inherits a document rather than a memory.

**Entry:** the accepted assessment report.

**Artefact:** the **Deployment design record** ([template](templates/04-deployment-design-record.md)).
One document, these sections, each a decision with its reason:

### 2.1 Shape and topology

Which door: the one-machine door (`local` on tracker, forge and board), the compose stack on one
host, the compose stack on a server reachable by a team, or a cloud realisation through an
add-on. Where the worker, the panel, the engine and the boxes run; ports; the `OPENFACTORY_WORK_DIR`
host directory; disk budget (roughly 8 GB for the images); the named volumes that hold the
registry, the journals and the proofs.

### 2.2 Provider axes

One row per axis, chosen from the [status table](../STATUS.md): tracker, board, forge, CI
observer, harness (per role, with `model:` per role), reviewer engine, channel (the panel always;
a chat channel only as an add-on), sandbox (`worktree`, `container`, or a remote box add-on),
telemetry sink (SQLite by default), identity (`local` invitations or OIDC). An unknown kind
refuses by name at startup, so the design names only kinds the deployment will actually carry.

### 2.3 Credentials and their boundaries

The design states, for each credential, who holds it, where it lives, what it may do, and which
process can read it — following the platform's own rule that the box holds only the harness's
credential and the host holds everything that can touch the board, the remote or a merge
([operations](../operations.md)):

| credential | on Light | on Standard / Enterprise |
|---|---|---|
| the coding agent's | the person's own login | a subscription token or API key in the deployment's secret store; a token pool where limits are hit ([rotation](../rotation-and-retention.md)) |
| the forge's | none — the repository is local | a PAT to try things; a GitHub App for real use, with exactly the [permission table](../setup/github.md), never `workflows` |
| the tracker's | none | the App, or the classic PAT a personal account's board requires; the Azure DevOps PAT |
| the panel's | open on a laptop | `OPENFACTORY_PANEL_TOKEN` or per-person tokens; OIDC on Enterprise |
| product tokens | not used | per-person entries in `OPENFACTORY_PRODUCT_TOKENS`, ids listed in `product.admins` |
| release approvers | not used | `openfactory approver add`, scrypt-hashed, or `OPENFACTORY_APPROVERS` from the secret store |
| `box.env` | whatever the setup needs | the enumerated allow list of variables the container box may receive, and nothing else |

### 2.4 The box

The image (stock or the client's own `box.image`), the toolchain it must carry (what the proof
pins), `box.network` (bridge, a restricted network, a proxy), the optional `box.cache_volume` and
the package-manager variables that make it useful, the TLS CA a re-signing network requires the
image to trust. A client image is the client's: the design records who builds it and when it is
rebuilt.

### 2.5 The quality floor and the manifest, per repository

The manifest each repository will carry: `setup:`, `validate:` (`test` is mandatory and has no
default; `security` is inherited from the floor unless declared; `lint` and `type` where they
exist), `advisory: true` on gates that are noisy but wanted, `components:` with `risk:` levels,
`docs:` roles, `knowledge_map` (on by default), `e2e_label` and `e2e_workflow` where an e2e
workflow spans repositories, the ticket language.

### 2.6 Merge policy, branch protection and CI

`merge_policy: human` for the pilot, always; the conditions under which the design allows
graduation to `auto` (§7); `review_mode` (advisory by default; blocking where the client wants
the reviewer to be able to stop a merge); the branch-protection standard ([operations](../operations.md)
§Branch-protection standard) — PR required with zero required human approvals, linear history,
auto-merge enabled, head branches deleted on merge, the App granted Checks: Read, and the required
status checks chosen from checks that run on every PR and are deterministic.

### 2.7 After the merge

Nothing (the ticket finishes at the merge and says so), `post_merge_deploy:` (watch the deploy
workflow and report), or `environments:` + `promote:` (walk the stages, park at the production
gate, a named approver releases with a password). The design names the stage a person validates
(`validate_with: product`) and the `url:` a person is sent to. A promotion chain runs only on a
remote box today — a local box deployment designs a) not b).

### 2.8 The product role

Whether it is switched on; the context repository (existing, created by the factory, or created by
the client's own process and declared); the three declarations that must agree
([product-role](../reference/product-role.md)); who the admins are; how a legacy corpus is adopted
(`product baseline`, everything arriving as `observed`).

### 2.9 Operations

The operator's name and backup; the cadences (§4); where logs are read (the panel's Logs page,
`docker compose logs`, the engine's UI); retention (`OPENFACTORY_ENGINE_RETENTION_DAYS`, the
journal volume, conversation retention of 180 days); backup of the state that has no other copy
(§6.4); the upgrade policy (§6.1); the support tier and its escalation path (§5).

### 2.10 Cost governance

The budget per month, the token pool, `OPENFACTORY_MAX_CONCURRENT_JOBS` (default 1, and the
reason to leave it there), `effort_budget_turns` and `repair_max_attempts` per project, who is
told when a budget is exhausted, and how the cost dashboard is read weekly.

**Exit:** the record is reviewed by the client's operator, the client's security reviewer on
Enterprise, and the implementer; every open question in it has an owner and a date. On
Enterprise the security review is signed before §3 begins.

**Light profile:** the record is the annotated `.env.compose` (or the one-machine `init` file)
plus the manifest, with a short page for §2.3, §2.6 and §2.9. It still exists: an operator who
inherits a Light deployment needs to know what the merge policy is and where the token lives.

---

## 3 · Implement

**Purpose:** bring the deployment up as designed, onboard each project with the platform's own
tools, prove it, rehearse it, run a pilot, and hand over to operation with numbers.

**Entry:** the signed design record; the credentials it names, obtained; the client work items
from the assessment done (the test command runs on a clean clone).

### 3.1 Install the stack

| profile | the step |
|---|---|
| Light, one machine | `pip install -e '.[runtime]'`, `openfactory init`, `openfactory up` ([one-machine](../setup/one-machine.md)) |
| Light / Standard, compose | `curl -fsSL https://openfactory.digital/install.sh \| sh`, or the four pinned commands from the [README](../../README.md) with the checksums verified; `openfactory init` writes `.env.compose` |
| Enterprise | the same compose stack on the designed host, or the add-on's reference deployment; the version pinned in `.env.compose`; images pulled from the registry the design names; the panel behind the identity the design names |

Evidence: `openfactory preflight` naming nothing missing; the panel answering; `docker compose ps`
healthy. The version installed is written into the design record.

### 3.2 Register and onboard each project

On the worker (the compose stack has its own registry; a laptop registration is invisible to it):

```bash
openfactory project init <name> <clone-url>        # register + board with the platform's columns
openfactory doctor <name>                          # NOT ready, and it names exactly what §3.3 settles
openfactory onboard <name> --yes [--source owner/repo ...]
```

`onboard` reads the manifest out of the code, proves it in the real box, generates the module
map, creates-or-uses the context repository, proposes the backfill, and opens one pull request
per repository with the proof's verdict in the body. **The client reviews and merges**; the
implementer never merges a proposal into a client repository. `validate.test` is the field to
read hardest. The `docs_repo:` line in each source repository is the one line the platform will
not write — the implementer's checklist carries it.

With the developers in the room, the manual session (`env read`, `env apply --yes`) replaces or
precedes `onboard` for the manifest; `env context --ask --write` for the backfill.

Evidence: the merged pull requests; `doctor` reporting the manifest as merged rather than
proposed.

### 3.3 Prove the box

```bash
openfactory box prove <name> [--repo owner/repo]   # one proof per repository
openfactory box status <name>
```

A failing proof on a command that must change is a normal step: edit the manifest, commit, re-prove.
Nothing is picked up until every repository in the product is proven. On a local box the proof
gates pickup; on a remote box add-on the proof is run by hand and the design record says who runs
it after each change ([STATUS](../STATUS.md)).

Evidence: `box status` green with the toolchain it is pinned to, per repository.

### 3.4 One verdict, then the rehearsal

```bash
openfactory env check <name>                       # exit 0 only when pickup is genuinely unblocked
openfactory env rehearse <name>                    # prints what it would cost, runs nothing
openfactory env rehearse <name> --yes [--no-gates] # the whole loop on a synthetic ticket, in a throwaway clone
```

The rehearsal touches no tracker, no branch, no pull request. Its printed cost is the first real
number in the cost governance section. A failure says where a real ticket would have died.

Evidence: the rehearsal's output attached to the implementation log.

### 3.5 The first real ticket

A small, real card with an objective and acceptance criteria, moved to the pickup column, under
`merge_policy: human`, watched on the panel from spec to independent review. The client merges.
The implementer walks the reviewers through the pull request body: validations, the review, the
touched components, the cost.

Evidence: the merged pull request; the card in Done; the job's page on the Logs surface.

### 3.6 The pilot

Between ten and thirty real tickets over two to six weeks, chosen by the client's product owner,
under human merge, with the numbers agreed in the assessment measured on the cost dashboard:

| number | where it is read |
|---|---|
| tickets picked up, merged, parked, skipped | the panel's floor and the Logs page |
| median time to pull request | the cost dashboard |
| median agent cost per merged ticket | the cost dashboard |
| park rate and its classes (transient, credential, environment, requirement, code, unknown) | the tech-lead's escalations on the cards |
| review rejection rate and repair passes | the pull-request bodies |
| the operator's hours per week | the operator's log |

The pilot ends with a **Pilot report** ([template](templates/05-pilot-report.md)): the numbers
against the targets, what parked and why, the manifest changes made, and a go / no-go / go-with-
changes recommendation.

### 3.7 Hand-over and go-live

The **Operations runbook** ([template](templates/06-operations-runbook.md)) is completed from the
design record with everything the pilot taught; the operator runs a week under the implementer's
watch; support (§5) is switched on; the go-live gate is signed.

**Exit — the go-live gate:** `doctor` green on every project; every proof current; the pilot
report accepted; the runbook handed over; the support contract active; the backup of §6.4 taken
once and restored once.

**Light profile:** §3.6 is five tickets in a week; §3.7 is the operator reading the runbook page.

**Enterprise profile:** §3.1 is done in a non-production deployment first and repeated; §3.6 is
per project with a security sign-off on the first pull request's diff of what reached the box;
§3.7 includes the DR test.

---

## 4 · Operate

**Purpose:** run the deployment day to day so that every wait is visible, every parked card is
answered, and cost stays inside the budget. The platform is designed so that operation is
reading the panel and answering questions on cards; this section is the cadence that makes it so.

**The operator's cadences** (from the runbook):

| when | what | with |
|---|---|---|
| continuously | the panel's attention bar: cards in Needs Action, waiting merges, the production gate | the panel; a chat channel where one is installed |
| daily | the Logs page for the last day's runs; parked cards answered on the card and moved back to TO-DO; token pool state (`index/N` on the panel) | the panel |
| weekly | the cost dashboard against the budget; recurring failures the tech-lead has reported; `doctor` on each project; `box status`; the API budget line | the panel, `openfactory doctor`, `openfactory box status` |
| monthly | the platform's releases read; the upgrade decided (§6.1); credentials nearing expiry rotated; retention and disk checked | the release notes, `docker system df` |
| quarterly | the merge-policy review (§7); the manifest review with the developers; the runbook re-read | the design record |

**What the platform does on its own and what a person does** — the boundary the operator is
certified on ([agents.md](../agents.md)):

- transient and credential failures are the factory's: it waits, rotates, resumes;
- environment, code, requirement and unknown failures park with a named person and a
  decision-shaped message; the operator routes them, never "goes to read the code";
- production is never released from chat; the approver releases on the panel with a password;
- a card labelled `factory-test` is refused on a client's board; the factory's own tests run on
  the partner's test-bench project.

**The requester's discipline:** an objective and acceptance criteria on every card; a refinement
question answered on the card, then the card moved back to TO-DO; a card corrected only before the
factory takes it up.

**The reviewer's discipline:** the pull-request body is read before the diff (validations, the
independent review, the touched components, the cost); a wrong merge is reverted through a card.

**Evidence of an operated deployment:** the operator's weekly log; the cost dashboard's history;
zero cards in Needs Action older than the support tier's response time.

---

## 5 · Support

**Purpose:** answer, within a committed time, the questions the platform escalates and the
failures it cannot classify — and route to the maintainers what is a defect in the platform.

The full standard, with tier definitions, severities and the escalation contract, is
[06-support-and-maintenance-standard.md](06-support-and-maintenance-standard.md). What the method
requires of an implementation:

- **A named first line.** The operator (Light), or the partner's support desk (Standard,
  Enterprise) with a tier from the standard.
- **Severities from the platform's own failure classes.** A silent stall, a credential reaching
  where it must not, or a production gate that cannot be opened is severity 1 on every tier; a
  card parked `unknown` twice on the same cause is severity 2; a single project's proof expired
  is severity 3; a question is severity 4.
- **The tech-lead's memory is the first read.** Its escalation says what it tried and how often
  it has seen this; the support engineer starts there, never from a blank log.
- **An escalation path to the maintainers.** A platform defect is filed with the journal excerpt
  and the version; a security finding goes through the [security policy](../../SECURITY.md).
- **A record.** Every ticket carries its class, its remedy and whether the remedy worked, so
  recurring failures become maintenance items (§6).

---

## 6 · Maintain

**Purpose:** keep the deployment current, proven and recoverable over years, without an outage
the operator did not choose.

### 6.1 Upgrade

- **Currency:** a supported deployment runs the current release or the one before it. The
  project's [release policy](06-support-and-maintenance-standard.md#releases-and-currency) says which lines
  receive fixes.
- **The step:** re-run the installer (compose), or `git pull && docker compose --env-file
  .env.compose up -d --build` (a contributor's checkout); the version pinned in `.env.compose`
  moved deliberately; `doctor` opens with the build it is running.
- **After every upgrade:** `doctor` on every project, `box status` on every repository (a
  rebuild that leaves the toolchain unchanged does not expire the proof; a changed toolchain
  does), one rehearsal, and the release notes' behaviour changes applied (an
  `OPENFACTORY_NOTIFIER_FALLBACK` declaration, for instance, was one such change).
- **Never** an upgrade during a job that holds the floor; never two versions in one step
  without reading both release notes.

### 6.2 Proofs, credentials and rotation

The proof expires when the world it was taken against moves — the commands, the toolchain, a
client image's digest. The maintenance calendar re-proves after any of those. Credentials are
rotated on the schedule the design record set; the token pool's rotation is the platform's, the
pool's contents are the operator's. GitHub App keys can be regenerated at any time and the stack
recreated.

### 6.3 Retention and disk

The engine's history (30 days by default, only ever raised), the journals (until the volume is
deleted), conversations (180 days), the resume directory (7 days), the images the deployment
built. `docker system df` monthly; the disk budget in the design record kept true.

### 6.4 Backup and recovery

What has no other copy, and is backed up:

| state | where |
|---|---|
| the registry | `OPENFACTORY_REGISTRY` (`~/.openfactory/registry.yaml` or the worker's volume) |
| the deployment's environment | `.env.compose` or the secret store |
| the local board and pull requests (one-machine door) | the SQLite file beside the registry |
| the metrics and conversation store | the SQLite sink under `OPENFACTORY_STATE_DIR` |
| the approvers | `~/.openfactory/approvers.json` or `OPENFACTORY_APPROVERS` |
| the journals and proofs | the named volumes (`OPENFACTORY_LOG_DIR`) |
| the engine's database | the Postgres volume under the compose stack's `temporal` service |

What is *not* backed up because it lives elsewhere: the client's repositories, the boards, the
context repository, the module map (on the repository's knowledge branch). A restore is tested at
go-live and after every major upgrade; the test is a restore onto a clean machine with `doctor`
green afterwards.

### 6.5 Security maintenance

The [security policy](../../SECURITY.md) read on every release; the `box.env` allow list reviewed
when a manifest changes; the panel never open on a reachable host; the Docker socket trade
re-accepted when the host changes; a security advisory from the project applied within the tier's
window.

**Evidence of a maintained deployment:** the maintenance calendar ([template](templates/07-maintenance-calendar.md))
with each row dated; `doctor` and `box status` outputs after each upgrade; the last restore test's
date.

---

## 7 · Expand and renew

**Purpose:** grow the deployment's scope on evidence, and renew the engagement on numbers.

- **Graduating to `merge_policy: auto`:** after a pilot under human merge with a review
  rejection rate the client accepts, and with every area they want eyes on marked `risk: high`;
  the conditions `auto` actually checks are in [ONBOARDING §11b](../ONBOARDING.md). Never in the
  first month.
- **Switching on the product role:** a product owner named, a context repository, per-person
  tokens, a baseline adopted as `observed` and accepted by a person
  ([product-role](../reference/product-role.md)).
- **Adding projects:** each one is data — `project init`, `onboard`, `box prove` — and each
  gets its own row in the design record. One deployment serves one GitHub organisation; a
  second organisation is a second deployment.
- **Multi-repository products, e2e workflows, promotion chains:** designed in §2, introduced
  one at a time, each with its own proof.
- **Raising `OPENFACTORY_MAX_CONCURRENT_JOBS`:** only after the client accepts that it removes
  the dependency safety of one-job-at-a-time; there is no per-project cap.
- **The annual review:** the pilot's numbers re-measured for the year; the design record
  re-signed; the support tier re-chosen; the certified people on the engagement re-listed.

---

## Roles and responsibilities

Every role below has a certification in [03-role-certifications.md](03-role-certifications.md);
on Light one person holds several of them, and the method does not mind, as long as each is
held by a named person.

| role | who, typically | certified as |
|---|---|---|
| **sponsor** | the client's budget owner | not certified; signs the gates |
| **solution architect** | the partner's lead | OpenFactory Certified Solution Architect |
| **implementer** | the partner's engineer | OpenFactory Certified Implementer |
| **operator** | the client's platform engineer, or the hosting partner's | OpenFactory Certified Operator |
| **security reviewer** | the client's security team, or the architect on smaller profiles | Solution Architect (security domain) |
| **product owner** | the client's product person | OpenFactory Certified Product Owner |
| **requester / reviewer** | the client's developers | OpenFactory Certified Associate |
| **support engineer** | the partner's desk | Operator, plus the support standard |
| **release approver** | a named client person with a password | Associate; named in `prod_approvers` |
| **add-on developer** | whoever writes an adapter the core does not ship | OpenFactory Certified Developer |
| **trainer** | whoever teaches the above | OpenFactory Certified Trainer |

### RACI by phase

R = responsible, A = accountable, C = consulted, I = informed.

| phase | sponsor | architect | implementer | operator | security | product owner | developers |
|---|---|---|---|---|---|---|---|
| 0 Qualify | A | R | – | – | – | C | C |
| 1 Assess | A | R | C | C | C | C | C |
| 2 Design | A | R | C | C | C (A on Enterprise for §2.3) | C | I |
| 3 Implement | A | C | R | C | C | C | R (merges) |
| 4 Operate | I | I | C | R/A | I | R (cards) | R (reviews) |
| 5 Support | I | C | C | R (first line) / partner desk | C | I | I |
| 6 Maintain | I | C | C | R/A | C | I | I |
| 7 Expand | A | R | C | C | C | R | C |

---

## The evidence, in one table

A certified implementation can produce every row on request. An assessor auditing a partner asks
for these and nothing else.

| phase | evidence |
|---|---|
| 0 | the qualification note |
| 1 | the assessment report; `env read` and `env context` outputs per repository |
| 2 | the design record, signed |
| 3 | `preflight` and `doctor` outputs; the merged onboarding pull requests; `box status` per repository; the rehearsal output; the first ticket's pull request; the pilot report; the runbook; the go-live gate |
| 4 | the operator's weekly log; the cost dashboard; the Needs Action age |
| 5 | the support ticket record with classes and remedies |
| 6 | the maintenance calendar; post-upgrade `doctor` / `box status`; the last restore test |
| 7 | the annual review; the re-signed design record |

## What the method deliberately leaves to the platform

The method does not describe how a ticket is sized, how a stall is classified, how a token pool
rotates or how a proof expires — those are the platform's behaviours, documented once in
[operations](../operations.md), [rotation-and-retention](../rotation-and-retention.md) and
[agents](../agents.md), and a certified person is examined on them there. A method that restated
them would drift from them, and the platform's own rule is that a claim lives in one place.

The [feature coverage appendix](01a-feature-coverage.md) maps every supported feature to the
phase that introduces it, the role that owns it, and the profile where it is expected.
