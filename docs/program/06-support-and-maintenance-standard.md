# Support and maintenance standard

This standard defines severities, support tiers, the support process, the release and currency
policy, maintenance requirements, and the requirements for certified hosting. Partner support
desks are audited against it. Hosting services are certified against its last section. The
[delivery method](01-delivery-method.md) phases 5 and 6 refer to it.

Two platform facts shape the standard. First, the platform performs first-line triage itself:
the tech lead classifies each failure, resolves transient and credential failures, and escalates
the rest with a record of what it tried ([agents.md](../agents.md)). Support starts from that
escalation. Second, the platform is pre-1.0 and currently receives fixes on `main` only
([SECURITY.md](../../SECURITY.md)). The release policy in this document is a proposal for the
maintainers; until adopted, the currency requirement is "the latest release".

## Severities

Severity is defined by what is stopped, using the platform's own terms.

| severity | definition | examples |
|---|---|---|
| Sev1: factory down or unsafe | No card can be picked up on any project, or a security property is violated | Worker will not start. Floor held with no reason printed (a silent stall). A credential reaches a location `SECURITY.md` says it cannot. Production gate opens without a password. A merge landed that `auto`'s conditions should have blocked. |
| Sev2: project stopped | One project cannot pick up cards, or cards park repeatedly on the same cause | Proof cannot be re-established. `doctor` red on a line whose remedy fails. A card parked `unknown` twice on the same cause. Token pool exhausted and not resuming after backoff. Panel unreachable. |
| Sev3: degraded | Work flows with a defect a person is working around | Deploy watch times out on every merge. Cost dashboard empty. Module map stale with the freshness gate amber. Notifier silent. One card parked on an environment cause with a known fix. |
| Sev4: question or request | No work is stopped | How to declare a component. A request to raise a budget. A feature the status page lists as not built. |

The reporter sets the severity. The desk may lower it only with the reporter's agreement and a
reason recorded on the ticket.

## Support tiers

| | Community | Standard | Premium | Enterprise |
|---|---|---|---|---|
| Provider | The project: issues, discussions, documentation | Certified Partner | Certified or Premier Partner with the Support specialisation | Premier Partner |
| Hours | None committed | Business hours, 8x5, customer time zone | 24x7 for Sev1 and Sev2; business hours otherwise | 24x7 for Sev1 to Sev3 |
| Sev1 first response | – | 4 business hours | 1 hour | 30 minutes |
| Sev2 first response | – | 1 business day | 4 hours | 2 hours |
| Sev3 first response | – | 2 business days | 1 business day | 4 business hours |
| Sev4 first response | – | 5 business days | 2 business days | 1 business day |
| Channels | GitHub | Email and ticket system | Plus phone or chat for Sev1 and Sev2 | Plus a named engineer and a chat channel |
| Upgrades | Operator's responsibility | Assisted: partner reviews release notes and confirms post-upgrade checks | Performed by the partner in an agreed window | Performed by the partner; staged on non-production first; rollback plan |
| Service reviews | – | – | Quarterly, with the metrics in [method 3.6](01-delivery-method.md#36-pilot) | Monthly |
| Maintainer escalation | Public issue tracker | Via the partner; 5 business days target first response | 2 business days via a Premier partner | 2 business days |
| Profile | Light | Standard | Standard, Enterprise | Enterprise |

A first response is a person reading the ticket and stating the next step. It is not a
resolution. Resolution targets are agreed per contract: a platform code fix is the maintainers'
to make; a partner can commit to a workaround, not a release.

**Pricing guidance.** The project sets no prices. Comparable vendors price Premium at 1.6 to 2
times Standard and Enterprise at 3 times or more ([research](research/oss-monetization-and-market.md),
section 3.3). Where the partner also hosts, support is commonly 5 to 10% of hosting and
consumption spend with a minimum.

## Support process

1. **Intake.** Each ticket records the platform version (`doctor`'s first line), project, card,
   severity, and the tech lead's escalation text when present. The desk requests the journal
   excerpt (`/logs/<project>/<ticket>`) first.
2. **Classification.** Record the platform's class (transient, credential, environment,
   requirement, code, unknown) and the desk's class (platform defect, configuration, customer
   code, customer process, question). The class determines the owner.
3. **Initial diagnosis.** Run `doctor`, `box status`, `env check`; read the journal and the tech
   lead's record of attempted remedies.
4. **Resolution or escalation.** Configuration and process issues are the desk's. Customer code
   issues return to the customer with the diagnosis. Platform defects are filed upstream with
   the journal excerpt, version and a minimal reproduction; the desk provides a workaround.
5. **Closure.** A ticket closes when the remedy is observed to work (card flows, proof holds,
   `doctor` green), not when the remedy is applied.
6. **Record.** Class, remedy, outcome, upstream issue number. Recurring entries become
   maintenance items. Aggregates go into the partner's annual report.

A desk audit samples twenty tickets from the trailing year against these steps and the tier's
response times.

## Releases and currency

Proposed release policy, subject to adoption by the maintainers:

| release type | cadence | contents |
|---|---|---|
| Minor (`0.x`, later `1.x`) | About every eight weeks; behaviour-change list; release candidate two weeks before | Features and fixes |
| Patch | As needed | Fixes only |
| Security patch | On disclosure, for the current and previous minor | The fix |
| Long-term line (from 1.0) | One per year, supported eighteen months | Security and critical fixes |

**Currency.** A supported deployment runs the current minor or the previous one, or a long-term
line within its window. Older deployments receive best-effort support until upgraded; the
desk's first action is to schedule the upgrade.

**Compatibility.** The manifest schema, registry schema, public CLI commands and
`preflight --json` schema are versioned contracts. A minor release may add; a major release may
remove. Release notes list every behaviour change.

## Maintenance requirements

The [maintenance calendar](templates/07-maintenance-calendar.md) records each activity with a
date.

| activity | cadence | procedure | evidence |
|---|---|---|---|
| Upgrade | Per minor, within the currency rule | Read release notes; stage on non-production (Enterprise); re-run the installer or `up -d --build`; `doctor` per project; `box status` per repository; one rehearsal | Dated outputs |
| Security patch | Within the tier window: Standard 10 business days, Premium 5, Enterprise 2 | Apply and verify as an upgrade | Dated outputs |
| Proof re-validation | After any change to `setup:`, `validate:`, toolchain or customer image | `box prove`; release held cards | `box status` |
| Credential rotation | Per the design record: App keys and PATs at least annually; token pool per vendor limits; panel and product tokens on personnel change | Recreate the stack with `--env-file`; `doctor` | Calendar |
| Backup | Daily for the state store and engine database; before every upgrade | Copy the backup set off the host | Backup log |
| Restore test | At go-live, after every major upgrade, at least annually | Restore onto a clean machine; `doctor` green | Test date and output |
| Retention and disk | Monthly | `docker system df`; archive journals per the design record; prune images; expire conversations past 180 days | Calendar |
| Runbook review | Quarterly | Re-read against the current deployment | Dated revision |
| Design record review | Annually | Re-sign; re-claim the profile | Signature |

## The hosting standard

A managed service applying for OpenFactory Certified Hosting
([05](05-conformance-and-marks.md)) must meet every requirement below. The annual hosting audit
verifies them.

| requirement | definition | verification |
|---|---|---|
| One deployment per customer organisation | A deployment serves one forge organisation and one customer. Customers do not share a worker, registry, state store or box daemon. | Provider inventory; `project list` per deployment |
| Credential boundary between provider and customer | The customer's harness and forge credentials belong to the customer, are held in a secret store the customer can rotate, are reached by provider staff only through the deployment's own mechanisms, and every access is logged. | Secret store access log; runbook |
| Declared data location | The region of the worker, boxes, state store, backups and journals is stated in the contract and does not change without notice. | Contract; inventory |
| Exit | The backup set is exportable in the platform's formats within 30 days of a request; the deployment is deleted on confirmation; `forget-conversations` honoured on request. | An export performed in the trailing year |
| Panel behind identity | Never open. Per-person tokens or OIDC. Named approvers. Provider staff use their own identities. | `.env.compose`; `people list` |
| Declared egress | The three destinations and any package registries, per customer. `box.network` set deliberately. | Design record |
| Version currency | The currency rule above; security patches within the Premium window. | `doctor` first line per deployment |
| Tested restore | At least annually per deployment class and after major upgrades. | Calendar |
| Support tier | Premium or above, with the severities and response times in this standard. | Desk audit |
| Customer-visible observability | The panel, Logs page and cost dashboard are the customer's. Provider monitoring is additional. | Customer view |
| Host access model stated | The worker mounts the Docker socket and is root-equivalent on its host. The provider either dedicates the host to the customer or uses a remote box. | Inventory |
| Itemised pricing | Platform fee, hosting fee, support fee and model spend are separate lines. The customer can read cost per merged ticket from the dashboard. | Invoice |

## Obligations of the project

For this standard to hold, the project commits to:

- a security advisory process with the 72-hour acknowledgement in `SECURITY.md`, and private
  pre-notification to Certified and Premier partners with hosting deployments;
- release notes listing every behaviour change, and release candidates to partners two weeks
  before a minor release;
- a maintainer escalation channel with the first-response targets in the partner program, where
  a response means a maintainer has read the journal and stated whether the issue is a defect.
