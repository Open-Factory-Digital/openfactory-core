# Role certifications

OpenFactory offers seven individual certifications, one for each role in the
[delivery method](01-delivery-method.md). Certifications are held by individuals, not companies.
Each has an expiry date and can be verified online by certificate number. Partner tiers
([04-partner-program.md](04-partner-program.md)) are measured in these certifications.

The format follows current practice in comparable programs (see
[research](research/partner-and-certification-programs.md), section 3): performance-based exams
for hands-on roles, multiple-choice exams for foundational and product roles, a pass mark of 70%,
two- or three-year validity, and one free retake.

## Certifications

| code | name | audience | format | duration | pass mark | validity | prerequisite |
|---|---|---|---|---|---|---|---|
| OFCA | OpenFactory Certified Associate | Requesters, reviewers, sponsors, sales, anyone on an engagement | 50 multiple-choice and scenario items | 75 min | 70% | 3 years | None |
| OFCO | OpenFactory Certified Operator | People who run a deployment | Performance-based, lab | 2 h | 70% | 2 years | None (OFCA recommended) |
| OFCI | OpenFactory Certified Implementer | People who assess a codebase and take a project to go-live | Performance-based, lab | 3 h | 70% | 2 years | Valid OFCO |
| OFCSA | OpenFactory Certified Solution Architect | People who design deployments and sign security reviews | Design record submission graded against a rubric, plus a 90-minute scenario exam | 90 min + submission | 70% on each part | 2 years | Valid OFCI |
| OFCPO | OpenFactory Certified Product Owner | People who own what gets built | 40 items plus a 45-minute performance section on the product surface | 2 h | 70% | 3 years | None |
| OFCD | OpenFactory Certified Developer | People who write add-ons or contribute to the core | Performance-based, lab | 3 h | 70% | 2 years | OFCA |
| OFCT | OpenFactory Certified Trainer | People who teach the program's courses | Teach-back under observation plus a delivery review | Half day | Pass/fail | 1 year | Valid OFCI or OFCSA |

A valid higher certification on the same track renews the lower ones: OFCI renews OFCO; OFCSA
renews OFCI and OFCO.

## Fees

Proposed for the program's first year. Set by the program committee, revised annually and
published on the program page. A reduced fee applies to candidates in economies the World Bank
classifies as lower-middle or upper-middle income.

| | OFCA | OFCO | OFCI | OFCSA | OFCPO | OFCD | OFCT |
|---|---|---|---|---|---|---|---|
| Standard fee (USD) | 150 | 350 | 450 | 500 | 250 | 450 | 800 |
| Reduced fee (USD) | 75 | 175 | 225 | 250 | 125 | 225 | 400 |
| Included | 1 free retake | 1 free retake | 1 free retake | 1 resubmission | 1 free retake | 1 free retake | 1 re-observation |

## Exam environment

Performance-based exams run in a disposable lab that the candidate accesses through a browser.
The lab contains:

- the platform installed, with the compose stack available for the Operator and Implementer
  exams;
- a seeded repository with known defects;
- the `local` tracker, forge and board rows (the one-machine door);
- a stub harness that produces deterministic diffs from a script instead of calling a model.

No model credential is required and no tokens are spent. The documentation is available during
the exam. The lab has no other internet access.

Tasks state an outcome to achieve. Grading scripts read the resulting state (`doctor --json`,
`box status`, the manifest, the registry, the journal). Partial credit is awarded per task.
Items are drawn from a bank; candidates sitting on the same day receive different draws of the
same domains.

## Exam policies

- **Proctoring.** Online, through a proctoring provider with identity verification and screen
  recording, or in an Authorised Training Partner's classroom with an OFCT present.
- **Results.** Pass or fail with per-domain scores within five business days.
- **Badges.** A digital badge (Open Badges, verifiable by URL) on a pass. The public verification
  page lists name, certification, certificate number, issue and expiry dates. Candidates may
  withhold their name from the public page.
- **Renewal.** Re-sit the current exam before expiry, or hold a valid higher certification on the
  same track.
- **Versioning.** Each exam is versioned to the platform minor release it was written against.
  The item bank is revised on every minor release; changes are published.
- **Retakes.** One free retake within twelve months of a failed sitting. Further attempts at the
  full fee. Seven days between attempts. No limit on attempts.
- **Accommodations.** Extra time on documented need.
- **Appeals.** Reviewed by a second grader within fifteen business days.
- **Misconduct.** Sharing exam items results in a two-year ban; the items are retired.

## Exam domains

Domain weights are drawn from [01a-feature-coverage.md](01a-feature-coverage.md). The
documents in the syllabus column are the study material; the program publishes no separate
version of them.

### OFCA: Associate

| domain | weight | syllabus |
|---|---|---|
| What the platform is and is not: orchestrates existing agents; policies authorise, humans evaluate; not a SaaS; production behind a human gate | 15% | README, [architecture.md](../architecture.md) sections 1 and 7 |
| The engineering loop: seven stations, spec gate, sizing and splitting, the box, gates, independent review, pull request body, merge policy | 20% | [pipeline-stations.md](../pipeline-stations.md), ONBOARDING sections 8 and 11b |
| Writing a card: objective and acceptance criteria; Gherkin in English or Portuguese; answering refinement questions; when a card may be corrected | 15% | [operations.md](../operations.md), Ticket format |
| Reading the panel: floor, attention, Needs Action, Logs page, cost dashboard | 10% | ONBOARDING section 12 |
| Failure classes: the six classes, who resolves each, what the factory never retries | 15% | [agents.md](../agents.md), [architecture.md](../architecture.md) section 7 |
| Boundaries: credential boundary, `workflows` refusal, no deploys from chat, one organisation per deployment, egress destinations | 15% | [SECURITY.md](../../SECURITY.md), STATUS "Deliberately not built" |
| Profiles and the method: three profiles, seven phases and their gates, who signs what | 10% | [01](01-delivery-method.md), [02](02-profiles.md) |

### OFCO: Operator

| domain | weight | example tasks | syllabus |
|---|---|---|---|
| Install and upgrade | 15% | Run the installer against a pinned version; fill the environment by hand; recreate the stack after a credential change; upgrade and confirm proofs still hold | ONBOARDING sections 0–1, `install.sh --help`, [06](06-support-and-maintenance-standard.md) |
| Diagnostics | 20% | Read `preflight`, `doctor`, `env check`, `box status`, `floor`; fix a red line from its remedy; distinguish the laptop's answer from the worker's | ONBOARDING sections 2 and 6, "If something does not work" |
| The box | 15% | Prove a repository; expire a proof by changing a command and re-prove; interpret the pinned toolchain; handle a customer image digest change | ONBOARDING section 5 |
| Running work | 15% | Pause and resume the poller; answer a card in Needs Action and return it; Resume versus Skip; read a paused job's token state; a split ticket; an exhausted effort budget | [operations.md](../operations.md), [rotation-and-retention.md](../rotation-and-retention.md) section 1 |
| People and access | 10% | Set a panel token; per-person tokens; add and list an approver; issue an invitation; who may resume and who may release | [product-role.md](../reference/product-role.md) sections 2–3, [cli.md](../reference/cli.md) |
| Retention, backup, restore | 15% | Take the backup set; restore onto a clean machine with `doctor` green; raise engine retention; delete conversations on request; reclaim disk | [rotation-and-retention.md](../rotation-and-retention.md), [01 section 6.4](01-delivery-method.md#64-backup-and-recovery) |
| Cost and the floor | 10% | Read the cost dashboard; the API budget line; `OPENFACTORY_MAX_CONCURRENT_JOBS` and its trade-off; a reported budget exhaustion | ONBOARDING sections 11b and 12, STATUS |

### OFCI: Implementer

The lab repository has a test command that is one of four candidates, a disabled CI workflow,
and a mis-named board column. Prerequisite: valid OFCO.

| domain | weight | example tasks | syllabus |
|---|---|---|---|
| Assessment | 15% | Run `env read` and `env context`; identify the fields only developers can answer; find changed areas with no named tests; complete the scorecard | [01 phase 1](01-delivery-method.md#phase-1-assess), ONBOARDING sections 3–4 |
| Registration and onboarding | 20% | `project init`; `onboard` with two sources; review the proposals; correct the manifest with `env apply --pr --set`; the `docs_repo:` line; declare the context repository | ONBOARDING sections 2–4 and 10 |
| Manifest and quality floor | 20% | A `validate.test` that tests something; an advisory gate; components with `risk: high`; protected paths; docs roles; an e2e workflow; `conformance <project>` green | [configuration.md](../reference/configuration.md), [project.yaml.example](../project.yaml.example) |
| Merge policy and forge | 15% | Apply the branch-protection standard; choose required checks; set `merge_policy` and `review_mode`; explain what `auto` checks; the effect of a suppression | ONBOARDING section 11b, [operations.md](../operations.md) Branch-protection standard |
| Proof, rehearsal, first ticket | 15% | `box prove` per repository; `env check` exit 0; read `env rehearse` for cost and failure point; run the first card end to end under human merge | ONBOARDING sections 5–8 |
| After the merge | 10% | Declare a deploy watch with a `url:`; declare a promotion chain and read `doctor`'s `post_merge` line on a local box; the product role's three declarations | ONBOARDING sections 9 and 13 |
| Hand-over | 5% | Complete the runbook from the design record; produce the go-live evidence | [01 section 3.7](01-delivery-method.md#37-hand-over-and-go-live), [templates](templates/) |

### OFCSA: Solution Architect

Two parts. The candidate writes a design record for a case supplied by the program (a fictional
organisation with a defined constraint set, such as an egress policy, a personal-account board,
a .NET stack, a two-repository product and an approved model route), graded against a published
rubric. The candidate then sits a 90-minute scenario exam. Prerequisite: valid OFCI.

| domain | weight | syllabus |
|---|---|---|
| Shape and topology: one machine, compose, cloud realisation; component placement; ports and volumes; disk; one organisation per deployment | 15% | [architecture.md](../architecture.md) section 5, ADR-0040, ADR-0043, ADR-0049 |
| Provider axes: choosing kinds; add-on rows; per-role harness and model; reviewer on a separate engine; channel as an add-on | 15% | STATUS table, ADR-0022, ADR-0038 |
| Credentials and identity: the boundary table; container allow list versus worktree deny list; the App permission table; per-person tokens versus OIDC; approvers; token pool | 20% | [SECURITY.md](../../SECURITY.md), [github.md](../setup/github.md), [product-role.md](../reference/product-role.md) |
| Box and egress: customer image and what the proof pins; `box.network`; re-signing CA; egress destinations; air-gapped limitation; socket mount or remote box | 15% | ADR-0037, [architecture.md](../architecture.md) section 5 |
| Quality, risk and merge: the floor and why it has no switch; profiles that only strengthen; risk levels; the conditions of `auto`; suppressions; test census | 15% | `policy/floor.py`, ADR-0007, ADR-0011, ADR-0014 |
| After the merge and product role: deploy watch versus promotion chain; the gate; `validate_with`; context repository; observed versus accepted | 10% | ADR-0005, ADR-0019, ADR-0025, ADR-0047 |
| Operations and cost governance: cadences; retention; backup set; support tier; per-project budgets; pilot metrics | 10% | [01 phases 4–6](01-delivery-method.md), [06](06-support-and-maintenance-standard.md) |

### OFCPO: Product Owner

| domain | weight | syllabus |
|---|---|---|
| The product role: what it does alone, what it does only with confirmation, what it never does | 20% | [agents.md](../agents.md), The product role |
| Requirements: proposed, accepted, broken down, queued, delivered, released; agreed twice and never through a pull request; the template | 25% | ADR-0019, ADR-0032, ADR-0047, `org_defaults/requirements/0000-template.md` |
| Brownfield baseline: observed versus accepted; the three kinds of evidence; coverage declared | 15% | [agents.md](../agents.md), Reverse engineering; `product/brownfield.py` |
| Confirmations: a click that names what was shown; unauthorised yes; nothing starts spending on its own; admins | 15% | ADR-0028, ADR-0029, [product-role.md](../reference/product-role.md) section 2 |
| Delivery and release: acceptance is explicit; silence is not acceptance; the production gate; the `url:` a person is sent to | 15% | ADR-0025, ONBOARDING section 13c |
| Board and queue: Backlog versus TO-DO; who moves work into the queue; weekly triage; correcting a card | 10% | [agents.md](../agents.md), ONBOARDING section 8 |

### OFCD: Developer

The lab contains a checkout of the platform. Prerequisite: OFCA.

| domain | weight | example tasks | syllabus |
|---|---|---|---|
| Extension model | 20% | The entry-point group; the axes; builder signature per axis; built-in row wins a collision; `install_hint`; a broken add-on does not break `--help` | [writing-an-addon.md](../writing-an-addon.md), [core/07-extensibility.md](../core/07-extensibility.md) |
| Writing a row | 30% | Implement a tracker or notifier row for a supplied fake vendor; declare it; confirm the core finds it; `conformance-adapter` green; refusal by name when absent | [writing-an-addon.md](../writing-an-addon.md) sections 2–7 |
| House rules | 25% | A guard named as a sentence; proven by mutation with `tools/mutate.py`; the suite in both orders; a refusal with a remedy; a guard that reads the artefact rather than text about it | [CONTRIBUTING.md](../../CONTRIBUTING.md) |
| Seams | 15% | The four ways to break a seam; "born with two"; what does not belong in a port; when an add-on is the wrong answer | [CONTRIBUTING.md](../../CONTRIBUTING.md), ADR-0022 |
| Decision records | 10% | Locate the ADR nearest a change; the core/add-on ledger | [adr/README.md](../adr/README.md), [core/07-extensibility.md](../core/07-extensibility.md) section 10 |

### OFCT: Trainer

Requirements:

1. Valid OFCI or OFCSA.
2. Two multi-day technical course deliveries in the last two years, with references.
3. A teach-back of one module of the Operator course, observed by two OFCTs or program staff,
   graded on accuracy against the documentation, lab execution, and handling of incorrect answers
   from participants.
4. One full course delivery reviewed in the first year.

Renewed annually on delivery records and participant evaluations. Courseware is licensed to
Authorised Training Partners ([04-partner-program.md](04-partner-program.md), Training).

## Courses

Course outlines are published by the program. Authorised Training Partners deliver them under
licence. Courses are built on the documents above so that course content and documentation do
not diverge.

| course | length | prepares for | format |
|---|---|---|---|
| OpenFactory Foundations | 1 day | OFCA | Lecture and a guided one-machine run: a card to a merge on the participant's machine |
| Operating OpenFactory | 2 days | OFCO | Lab: install, diagnose, prove, run, park and answer, upgrade, back up, restore |
| Implementing OpenFactory | 3 days | OFCI | Lab on a legacy codebase: assess, onboard, manifest, floor, merge policy, rehearsal, first ticket, pilot report |
| Designing OpenFactory Deployments | 2 days | OFCSA | Case study: the design record and the security checklist |
| The Product Role | 1 day | OFCPO | The product surface: requirements, baseline, confirmations, release |
| Extending OpenFactory | 2 days | OFCD | A row written, conformance-checked and installed; a guard proven by mutation |

## Scope of a certification

A certification states that the holder performed the role's tasks in the exam environment to
the program's standard on the exam date. It is not a guarantee of future work. Partners may not
present it as one.
