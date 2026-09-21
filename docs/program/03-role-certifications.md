# Role certifications: the people

**Seven credentials, one per role the [delivery method](01-delivery-method.md) names, each earned
by doing the role's work on a real deployment under examination.** A certification is held by a
person, never by a company; it expires; it is verifiable by anyone with the credential's number.
Partner tiers ([04](04-partner-program.md)) are counted in these credentials, which is why their
definitions come first.

The design follows what the market has settled on ([research](research/partner-and-certification-programs.md)
§3): performance-based examinations for the roles that touch a deployment, two to three hours,
a pass mark near 70%, two-year validity, one free retake; multiple-choice for the foundational
credential; a prerequisite chain so that nobody certifies as an architect who has never operated
a factory.

## The ladder

```
                          ┌──────────────────────────────┐
                          │  OFCT  Certified Trainer      │  teaches all of the below
                          └──────────────▲───────────────┘
                                         │ holds OFCI or OFCSA
  ┌──────────────────┐   ┌──────────────┴───────────────┐   ┌──────────────────────┐
  │ OFCPO  Product   │   │ OFCSA  Solution Architect    │   │ OFCD  Developer      │
  │        Owner     │   └──────────────▲───────────────┘   │       (add-ons)      │
  └────────▲─────────┘                  │ holds OFCI         └──────────▲───────────┘
           │              ┌─────────────┴────────────────┐              │
           │              │ OFCI  Implementer            │              │
           │              └──────────────▲───────────────┘              │
           │                             │ holds OFCO                    │
           │              ┌──────────────┴───────────────┐              │
           │              │ OFCO  Operator               │              │
           │              └──────────────▲───────────────┘              │
           │                             │ recommended                   │
  ┌────────┴─────────────────────────────┴────────────────────────────┴───────────┐
  │ OFCA  Associate — the foundation; no prerequisite; for everyone on an engagement │
  └───────────────────────────────────────────────────────────────────────────────┘
```

| code | name | who | format | length | pass | validity | prerequisite |
|---|---|---|---|---|---|---|---|
| **OFCA** | OpenFactory Certified Associate | requesters, reviewers, sponsors, sales, anyone on an engagement | 50 items, multiple choice and scenario | 75 min | 70% | 3 years | none |
| **OFCO** | OpenFactory Certified Operator | whoever runs a deployment day to day | performance-based, in a lab | 2 h | 70% | 2 years | none (OFCA recommended) |
| **OFCI** | OpenFactory Certified Implementer | whoever assesses a codebase and brings a project to go-live | performance-based, in a lab | 3 h | 70% | 2 years | valid OFCO |
| **OFCSA** | OpenFactory Certified Solution Architect | whoever designs a deployment and signs its security review | a design-record submission graded to a rubric, plus a 90-minute scenario examination | 90 min + submission | 70% on each | 2 years | valid OFCI |
| **OFCPO** | OpenFactory Certified Product Owner | the person who owns what gets built | 40 items plus a 45-minute performance section on the product surface | 2 h | 70% | 3 years | none |
| **OFCD** | OpenFactory Certified Developer | whoever writes an add-on or contributes to the core | performance-based, in a lab | 3 h | 70% | 2 years | OFCA |
| **OFCT** | OpenFactory Certified Trainer | whoever teaches the above under the project's courseware | a teach-back under observation, plus a delivery review | half a day | pass / fail | 1 year | valid OFCI or OFCSA |

**Fees, proposed for the program's first year** (set by the program committee, revised
annually, published on the program page; a purchasing-power tier at half price for economies the
World Bank classifies as lower-middle or upper-middle income, Brazil included):

| | OFCA | OFCO | OFCI | OFCSA | OFCPO | OFCD | OFCT |
|---|---|---|---|---|---|---|---|
| standard | USD 150 | USD 350 | USD 450 | USD 500 | USD 250 | USD 450 | USD 800 |
| purchasing-power tier | USD 75 | USD 175 | USD 225 | USD 250 | USD 125 | USD 225 | USD 400 |
| includes | one free retake within 12 months | one free retake | one free retake | one resubmission | one free retake | one free retake | one re-observation |

The fees sit inside the band the market pays (USD 70–500 per exam; the performance-based
credentials at the upper end, as CKA, RHCSA and Elastic are). They fund the exam platform, the
proctoring, the item bank's upkeep and the program's staff, and the surplus is the project's
([07](07-sustainability.md)).

## How an examination works

**The lab is the one-machine door.** Every performance-based examination runs in a disposable
environment the candidate reaches in a browser: the platform installed, a seeded repository with
known defects, the `local` rows on tracker, forge and board, and a **stub harness** — an agent that
produces deterministic diffs from a script rather than calling a model, so the examination costs
no tokens, needs no vendor credential, and grades the same for everyone. The compose stack is
present for the operator and implementer examinations, with Docker inside the lab. Nothing the
candidate does reaches the internet except the documentation, which is open during the
examination as it is on the job.

**Tasks, not questions.** A performance item states an outcome ("the card on `web` is held and
the one on `api` flows; make both flow") and is graded by a script that reads the resulting state
— `doctor --json`, `box status`, the manifest, the registry, the journal — never by reading the
candidate's shell history. Partial credit is per task. Tasks are drawn from a bank; two candidates
sitting the same day see different draws of the same domains.

**Proctoring.** Online, through a proctoring provider with identity verification and screen
recording, or in a partner's classroom with an OFCT present. The program publishes the rules of
the room once and applies them to every sitting.

**Results.** Pass or fail with the per-domain score within five business days; a digital badge
(Open Badges, verifiable by URL) on a pass; a public verification page listing name, credential,
number, issue and expiry dates, and nothing else. A candidate may withhold their name from the
public page and still be verifiable by number.

**Renewal.** By re-sitting the current examination before expiry, or by holding a valid higher
credential on the same chain (a valid OFCI renews OFCO; a valid OFCSA renews OFCI and OFCO).
Credentials are versioned to the platform's minor release they were written against; the bank is
revised on every minor release and the program publishes what changed.

**Retakes.** One free retake within twelve months of a failed sitting; further attempts at full
fee; seven days between attempts; no limit on attempts.

**Accommodations, appeals, misconduct.** Extra time on documented need; an appeal reviewed by a
second grader within fifteen business days; a candidate found sharing items is barred for two
years and the items retired.

## The blueprints

Each blueprint lists the domains and their weight, drawn from the [feature coverage](01a-feature-coverage.md)
table. A domain's tasks are performed against the platform's own commands; the documents named
are the syllabus, and the program writes no second version of them.

### OFCA · Associate

For everyone who touches an engagement: the person writing a card, the reviewer reading a pull
request, the sponsor reading the pilot report, the sales engineer describing the platform. No
prerequisite.

| domain | weight | what is examined | syllabus |
|---|---|---|---|
| what the platform is and is not | 15% | orchestrates existing agents; policies authorise, humans evaluate; not a SaaS; production always behind a human | README, `docs/architecture.md` §1, §7 |
| the loop | 20% | the seven stations; the spec gate; sizing and splitting; the box; gates; the independent review; the pull-request body; merge policy | `docs/pipeline-stations.md`, ONBOARDING §8, §11b |
| writing a card | 15% | objective and acceptance criteria; Gherkin in English or Portuguese; answering a refinement question on the card; when a card can be corrected | `docs/operations.md` §Ticket format |
| reading the panel | 10% | the floor, attention, Needs Action, the Logs page, the cost dashboard | ONBOARDING §12 |
| what parks and why | 15% | the six failure classes; who resolves each; what the factory never retries; what "asks a human" looks like | `docs/agents.md`, `docs/architecture.md` §7 |
| boundaries | 15% | the credential boundary in one sentence; the `workflows` refusal; no deploys from chat; one organisation per deployment; the three egress destinations | `SECURITY.md`, STATUS "Deliberately not built" |
| the profiles and the method | 10% | the three profiles; the seven phases and their gates; which role signs what | [01](01-delivery-method.md), [02](02-profiles.md) |

### OFCO · Operator

For the person who runs a deployment: installs it, keeps `doctor` green, answers what parks,
reads the cost, upgrades, rotates, backs up, restores. Examined in the lab against a compose
stack and a one-machine install.

| domain | weight | tasks of the kind examined | syllabus |
|---|---|---|---|
| install and upgrade | 15% | run the installer against a pinned version; fill the environment by hand; recreate the stack after a credential change; upgrade and prove nothing expired | ONBOARDING §0–§1, `install.sh --help`, [06](06-support-and-maintenance-standard.md) |
| diagnostics | 20% | read `preflight`, `doctor`, `env check`, `box status`, `floor`; make a red line green from its remedy; tell the laptop's answer from the worker's | ONBOARDING §2, §6, "If something does not work" |
| the box | 15% | prove a repository; expire a proof by changing a command and re-prove; pin a toolchain; a client image's digest | ONBOARDING §5 |
| running work | 15% | the poller; pause and resume it; a card in Needs Action answered and moved; Resume vs Skip; a paused job's token state; a split ticket; an effort budget exhausted | `docs/operations.md`, `docs/rotation-and-retention.md` §1 |
| people and access | 10% | a panel token; per-person tokens; an approver added and listed; an invitation issued; who may resume and who may release | `docs/reference/product-role.md` §2–§3, `docs/reference/cli.md` |
| retention, backup, restore | 15% | the backup set taken; a restore onto a clean machine with `doctor` green; engine retention raised; conversations deleted on request; disk reclaimed | `docs/rotation-and-retention.md`, [01 §6.4](01-delivery-method.md#64-backup-and-recovery) |
| cost and the floor | 10% | read the cost dashboard; the API budget line; `OPENFACTORY_MAX_CONCURRENT_JOBS` and what raising it removes; a budget exhausted and reported | ONBOARDING §11b, §12, STATUS |

### OFCI · Implementer

For the person who takes a codebase from assessment to go-live. Examined in the lab against a
seeded repository whose real test command is one of four, whose CI has a disabled workflow, and
whose board has a mis-named column. Prerequisite: a valid OFCO.

| domain | weight | tasks of the kind examined | syllabus |
|---|---|---|---|
| assessment | 15% | `env read` and `env context` on the seeded repository; name the fields only the developers can answer; find the areas that change and that no test names; write the scorecard | [01 §1](01-delivery-method.md#1--assess), ONBOARDING §3–§4 |
| registration and onboarding | 20% | `project init`; `onboard` with two sources; read the proposals; correct the manifest through `env apply --pr --set`; the `docs_repo:` line; the context repository declared | ONBOARDING §2–§4, §10 |
| the manifest and the floor | 20% | `validate.test` that tests something; an advisory gate; components with a `risk: high`; protected paths; docs roles; an e2e workflow declared; `conformance <project>` green | `docs/reference/configuration.md`, `docs/project.yaml.example` |
| merge policy and the forge | 15% | branch protection to the standard; required checks chosen correctly; `merge_policy` and `review_mode`; what `auto` actually checks; a suppression's effect | ONBOARDING §11b, `docs/operations.md` §Branch-protection standard |
| proof, rehearsal, first ticket | 15% | `box prove` per repository; `env check` exit 0; `env rehearse` read for cost and for where a ticket would die; the first card end to end under human merge | ONBOARDING §5–§8 |
| after the merge | 10% | a deploy watch declared with a `url:`; a promotion chain declared and `doctor`'s `post_merge` line read on a local box; the product role's three declarations | ONBOARDING §9, §13 |
| hand-over | 5% | the runbook completed from the design record; the go-live gate's evidence table produced | [01 §3.7](01-delivery-method.md#37-hand-over-and-go-live), [templates](templates/) |

### OFCSA · Solution Architect

For the person who designs a deployment and signs its security review. Two parts: a **design
record** written for a case the program supplies (a fictional organisation with a stated
constraint set: an egress policy, a personal-account board, a .NET stack, a two-repository
product, an approved model route) and graded to a published rubric; and a **scenario
examination** of ninety minutes. Prerequisite: a valid OFCI.

| domain | weight | what is examined | syllabus |
|---|---|---|---|
| shape and topology | 15% | one machine vs compose vs a cloud realisation; where worker, panel, engine and box live; ports and volumes; disk; one organisation per deployment | `docs/architecture.md` §5, ADR-0040, ADR-0043, ADR-0049 |
| provider axes | 15% | choosing kinds; add-on rows and what refuses by name; per-role harness and model; the reviewer on a different engine; the channel as an add-on | STATUS table, ADR-0022, ADR-0038 |
| credentials and identity | 20% | the boundary table; the container allow list vs the worktree deny list and the thirteen names; the App permission table; per-person tokens vs OIDC; approvers; a token pool | `SECURITY.md`, `docs/setup/github.md`, `docs/reference/product-role.md` |
| the box and egress | 15% | a client image and what the proof pins; `box.network`; a re-signing CA; the three destinations; what an air-gapped network cannot do; the socket trade or a remote box | ADR-0037, `docs/architecture.md` §5 |
| quality, risk and merge | 15% | the floor and why there is no switch; profiles that only strengthen; risk levels; the nine conditions of `auto`; suppressions and pragmas; the census | `policy/floor.py`, ADR-0007, ADR-0011, ADR-0014 |
| after the merge and the product role | 10% | deploy watch vs promotion chain; the gate; `validate_with`; the context repository's shape; observed vs accepted | ADR-0005, ADR-0019, ADR-0025, ADR-0047 |
| operations and cost governance | 10% | cadences; retention; the backup set; the support tier chosen; budgets per project; the pilot's numbers | [01 §4–§6](01-delivery-method.md), [06](06-support-and-maintenance-standard.md) |

### OFCPO · Product Owner

For the person who owns what gets built. Forty items on the requirement lifecycle and the locks,
and a performance section on the product surface of a seeded deployment. No prerequisite.

| domain | weight | what is examined | syllabus |
|---|---|---|---|
| the role | 20% | what it does alone, what it does only with a confirmation, what it never does | `docs/agents.md` §The product role |
| requirements | 25% | proposed, accepted, broken down, queued, delivered, released; a requirement agreed twice and never through a pull request; the template | ADR-0019, ADR-0032, ADR-0047, `org_defaults/requirements/0000-template.md` |
| the brownfield baseline | 15% | observed vs accepted; the three kinds of evidence; why code is never a promise; coverage declared | `docs/agents.md` §Reverse engineering, `product/brownfield.py` |
| the confirmations | 15% | a click that names what was shown; an unauthorised yes; nothing starts spending on its own; who is an admin | ADR-0028, ADR-0029, `docs/reference/product-role.md` §2 |
| delivery and release | 15% | asked whether it worked; silence never counts; the production gate; the `url:` a person is sent to | ADR-0025, ONBOARDING §13c |
| the board and the queue | 10% | Backlog vs TO-DO; what enters the queue and who moves it; weekly triage; correcting a card | `docs/agents.md`, ONBOARDING §8 |

### OFCD · Developer

For the person who writes an add-on the core does not ship or contributes to the core. Examined
in the lab against a checkout of the platform. Prerequisite: OFCA.

| domain | weight | tasks of the kind examined | syllabus |
|---|---|---|---|
| the extension model | 20% | the entry-point group; the axes; a builder's signature per axis; a built-in row wins a collision; `install_hint`; a broken add-on never takes down `--help` | `docs/writing-an-addon.md`, `docs/core/07-extensibility.md` |
| writing a row | 30% | implement a tracker or notifier row for a supplied fake vendor; declare it; watch the core find it; `conformance-adapter` green; a refusal by name when it is absent | `docs/writing-an-addon.md` §2–§7 |
| the house rules | 25% | a guard named as a sentence; proven by mutation with `tools/mutate.py`; the suite in both orders; a refusal with a remedy; a guard that reads the thing, not text about it | `CONTRIBUTING.md` |
| the seams | 15% | the four ways to break a seam; born with two; what does not belong in a port; when the answer is not an add-on | `CONTRIBUTING.md` §Four ways, ADR-0022 |
| the decisions | 10% | find the ADR nearest a change and argue with it; the ledger of what is core and what is vendor-owned | `docs/adr/README.md`, `docs/core/07-extensibility.md` §10 |

### OFCT · Trainer

For the person who teaches the program's courses. Holds a valid OFCI or OFCSA; has delivered at
least two multi-day technical courses in the last two years (references); passes a teach-back of
one module of the Operator course under observation by two OFCTs or program staff, graded on
accuracy against the documents, on running the lab, and on handling a wrong answer from the room;
and has one full course delivery reviewed in the first year. Renewed annually on delivery
records and student evaluations. The courseware is the project's and is licensed to training
partners ([04](04-partner-program.md) §Training).

## The courses (the syllabus a trainer teaches)

The program publishes course outlines; a training partner delivers them under licence. Every
course is built on the documents above, so a course and the documentation never disagree.

| course | length | prepares for | shape |
|---|---|---|---|
| OpenFactory Foundations | 1 day | OFCA | lecture and a guided one-machine run: a card to a merge on the student's own machine |
| Operating OpenFactory | 2 days | OFCO | lab-led: install, diagnose, prove, run, park and answer, upgrade, back up, restore |
| Implementing OpenFactory | 3 days | OFCI | lab-led on a legacy codebase: assess, onboard, manifest, floor, merge policy, rehearsal, first ticket, pilot report |
| Designing OpenFactory Deployments | 2 days | OFCSA | case-led: the design record written and defended; the security checklist |
| The Product Role | 1 day | OFCPO | the product surface: requirements, baseline, confirmations, release |
| Extending OpenFactory | 2 days | OFCD | a row written, conformed and installed; a guard proven by mutation |

## What certification does not claim

A credential says a person performed the role's tasks on a seeded deployment to the program's
standard on a given day. It does not say the person's next implementation will succeed, and the
program never lets a partner imply it does. The claim the program stands behind is narrower and
checkable: **a certified person knows where the platform's own answers are and can produce the
evidence the method asks for.**
