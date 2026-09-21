# The support and maintenance standard

**What "supported" means on an OpenFactory deployment, written once so that every partner
contract, every hosting service and every client expectation points at the same definitions.**
A partner certifies its support desk against this page; a hosting service certifies against its
last section; the [method](01-delivery-method.md) §5 and §6 refer here rather than restating it.

Two facts about the platform shape everything below. First, **the platform already does the
first line of support itself**: the tech lead classifies every failure, resolves the transient
and credential classes on its own, and escalates the rest with what it tried and how often it has
seen the same thing ([agents.md](../agents.md)). A support desk starts from that escalation, not
from a blank log. Second, **the platform is pre-1.0 and its own policy is that only `main`
receives fixes** ([SECURITY.md](../../SECURITY.md)). The release policy below is therefore a
proposal to the maintainers, and until they adopt it the currency rule reads "the latest
release".

## Severities

Severities are defined by **what is stopped**, in the platform's own terms, so that a partner and
a client never argue about whether an incident is a 1 or a 2.

| severity | definition | examples |
|---|---|---|
| **Sev1 — the factory is down or unsafe** | no card can be picked up on any project, or a security property is violated | the worker will not start; the floor is held with no reason printed (a silent stall, the platform's own defect class); a credential reaches where `SECURITY.md` says it cannot; the production gate opens without a password; a merge landed that `auto`'s conditions should have held |
| **Sev2 — a project is stopped** | one project cannot pick up cards, or cards on it park repeatedly on the same cause | a proof that cannot be re-established; `doctor` red on a line whose remedy does not work; a card parked `unknown` twice on the same cause; the token pool exhausted and not resuming after the backoff; the panel unreachable |
| **Sev3 — degraded** | work flows with a defect a person is working around | the deploy watch reports timeout on every merge; the cost dashboard empty; the module map stale and the freshness gate amber; a notifier silent; one card parked on an environment cause with a named fix |
| **Sev4 — a question or a request** | no work is stopped | how to declare a component; a request to raise a budget; a feature the status page says is not built |

A severity is set by the reporter and may be lowered by the desk only with the reporter's
agreement and a reason on the ticket.

## Tiers

| | **Community** | **Standard** | **Premium** | **Enterprise** |
|---|---|---|---|---|
| who provides it | the project: issues, discussions, the documentation | a Certified Partner | a Certified or Premier Partner with the Support specialisation | a Premier Partner |
| hours | none promised | business hours, 8x5, the client's time zone | 24x7 for Sev1 and Sev2; business hours for the rest | 24x7 for Sev1 to Sev3 |
| Sev1 first response | — | 4 business hours | 1 hour | 30 minutes |
| Sev2 first response | — | 1 business day | 4 hours | 2 hours |
| Sev3 first response | — | 2 business days | 1 business day | 4 business hours |
| Sev4 first response | — | 5 business days | 2 business days | 1 business day |
| channel | GitHub | e-mail and a ticket system | plus phone or chat for Sev1/Sev2 | plus a named engineer and a chat channel |
| upgrades | the operator's | assisted: the partner reviews the release notes and confirms the post-upgrade checks | performed by the partner in an agreed window | performed, staged in non-production first, with a rollback plan |
| reviews | — | — | quarterly service review with the numbers of the [method](01-delivery-method.md) §3.6 | monthly |
| maintainer escalation | the public issue tracker | through the partner, 5 business days target first response | 2 business days through a Premier partner | 2 business days |
| profile fit | Light | Standard | Standard, Enterprise | Enterprise |

A first response is a person reading the ticket and saying what happens next; it is not a fix.
Resolution targets are agreed per contract, because a code fix in the platform is the
maintainers' to make and a partner can promise a workaround, not a release.

**Pricing guidance for partners** (the project sets no prices; this is the ratio the
[market](research/oss-monetization-and-market.md) §3.3 uses): Premium at 1.6 to 2 times Standard,
Enterprise at 3 times or more; where the partner also hosts, support as 5 to 10% of the hosting
and consumption spend with a floor.

## The support process

1. **Intake.** Every ticket carries the deployment's version (`doctor`'s first line), the
   project, the card, the severity, and the tech lead's escalation text verbatim when there is
   one. The desk asks for the journal excerpt (`/logs/<project>/<ticket>`) before anything else.
2. **Classification.** The desk records the platform's own class — transient, credential,
   environment, requirement, code, unknown — plus one of the desk's own: *platform defect*,
   *configuration*, *client code*, *client process*, *question*. The class decides the owner.
3. **The first read.** `doctor`, `box status`, `env check`, the journal, the tech lead's memory
   of what it already tried. The desk never asks the client to "go read the code".
4. **Resolution or escalation.** Configuration and process are the desk's; client code goes
   back with the diagnosis; a platform defect is filed upstream with the journal excerpt, the
   version and a minimal reproduction, and the desk offers a workaround.
5. **Closure by observation.** A ticket closes when the remedy is seen to work — a card that
   flows, a proof that holds, `doctor` green — never when the remedy was applied.
6. **The record.** Class, remedy, whether it worked, and the upstream issue number. Recurring
   entries become maintenance items; aggregates go to the partner's annual report.

A desk audit reads twenty tickets from the trailing year against these six steps and the tier's
response times.

## Releases and currency

**Proposed release policy, for the maintainers' adoption** (the program cannot promise what the
project has not decided):

| line | cadence | receives |
|---|---|---|
| a **minor** (`0.x`, then `1.x`) | about every eight weeks, with a behaviour-change list and a release candidate two weeks before | features, fixes |
| a **patch** | as needed | fixes only |
| a **security patch** | on disclosure, on the current and previous minor | the fix |
| a **long-term line** (from 1.0) | one a year, supported eighteen months | security and critical fixes |

**Currency.** A supported deployment runs the current minor or the one before it (or the
long-term line inside its window). A deployment further behind is supported on a best-effort
basis until it upgrades, and the desk's first action is to schedule the upgrade.

**Compatibility.** The manifest schema, the registry schema, the CLI's public commands and the
`preflight --json` schema are versioned contracts; a minor may add, a major may remove, and the
release notes list every behaviour change (the fallback-notifier declaration of 2026-08-26 is
the shape of such a change).

## Maintenance

The maintenance calendar ([template](templates/07-maintenance-calendar.md)) has these rows, and a
maintained deployment has each one dated:

| activity | cadence | what is done | evidence |
|---|---|---|---|
| upgrade | per minor, within the currency rule | release notes read; staged on non-production (Enterprise); the installer re-run or `up -d --build`; `doctor` per project; `box status` per repository; one rehearsal | the outputs, dated |
| security patch | within the tier's window: Standard 10 business days, Premium 5, Enterprise 2 | the patch applied and proven as an upgrade | the same |
| proof re-validation | after any change to `setup:`, `validate:`, the toolchain or a client image | `box prove`; a held card released | `box status` |
| credential rotation | per the design record: App keys and PATs at least annually; the token pool as the vendor's limits require; panel and product tokens on personnel change | the stack recreated with `--env-file`; `doctor` | the calendar |
| backup | daily for the state store and the engine database; before every upgrade | the backup set copied off the host | the backup log |
| restore test | at go-live, after every major upgrade, and at least annually | a restore onto a clean machine with `doctor` green | the test's date and output |
| retention and disk | monthly | `docker system df`; journals archived per the design record; images pruned; conversations past 180 days gone | the calendar |
| runbook review | quarterly | the runbook re-read against the deployment as it is | a dated revision |
| design record review | annually | re-signed, with the profile re-claimed | the signature |

## The hosting standard

A managed service that wants the **OpenFactory Certified Hosting** mark
([05](05-conformance-and-marks.md)) meets every row; the annual hosting audit reads them.

| requirement | what it means | how it is read |
|---|---|---|
| **one deployment per client organisation** | a deployment serves one forge organisation and one client; no two clients share a worker, a registry, a state store or a box daemon | the provider's inventory; `project list` per deployment |
| **the credential boundary is kept between provider and client** | the client's harness credential and forge credential are the client's; the provider holds them in a secret store the client can rotate; provider staff reach them only through the deployment's own mechanisms, and every such access is logged | the secret store's access log; the runbook |
| **the client's data stays where the client was told** | the region of the worker, the boxes, the state store, the backups and the journals is declared in the contract and does not change without notice | the contract; the inventory |
| **the client can leave** | the [backup set](01-delivery-method.md#64-backup-and-recovery) is exportable in the platform's own formats within thirty days of a request, and the deployment is deleted on confirmation, with `forget-conversations` honoured earlier on request | a documented export performed in the trailing year |
| **the panel is behind identity** | never open; per-person tokens or OIDC; approvers named; the provider's own staff have their own identities | `.env.compose` reviewed; `people list` |
| **egress is declared** | the three destinations and any package registries, per client; `box.network` set deliberately | the design record |
| **version currency** | the currency rule above, with security patches inside the Premium window | `doctor`'s first line per deployment |
| **a tested restore** | at least annually per deployment class, and after major upgrades | the calendar |
| **support at Premium or above** | with severities and responses as this page defines | the desk audit |
| **observability the client can see** | the panel, the Logs page and the cost dashboard are the client's; the provider adds monitoring of the host but does not replace them | a client's view |
| **the socket trade or a remote box, stated** | the host's Docker socket is mounted, so the worker is root-equivalent on the host that runs it; the provider either dedicates the host to the client or runs a remote box | the inventory |
| **the price is legible** | the platform fee, the hosting fee, the support fee and the model spend are separate lines; the client sees cost per merged ticket from the dashboard | the invoice |

## The maintainers' side

For this standard to hold, the project owes the partners three things, and the program commits
the steward to them until a foundation takes them over:

- a **security advisory process** with the 72-hour acknowledgement in `SECURITY.md`, and a
  private pre-notification to Certified and Premier partners with hosting deployments;
- **release notes** that list every behaviour change, and a release candidate to partners two
  weeks before a minor;
- a **maintainer escalation channel** for partners with the first-response targets in the
  partner program, where "response" means a maintainer reading the journal and saying whether
  it is a defect.
