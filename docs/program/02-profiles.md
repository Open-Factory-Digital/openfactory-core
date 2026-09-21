# Deployment profiles: Light, Standard, Enterprise

**Three sizes of the same platform, so that a two-person shop and a regulated enterprise follow
the same method at a cost each can carry.** A profile is not a product edition — every profile
runs the same Apache-2.0 build with every feature available. A profile is the set of decisions the
[design record](01-delivery-method.md#2--design) makes by default, the controls a certified
implementation must have in place, and the depth the [method](01-delivery-method.md) goes to at
each phase.

| | **Light** | **Standard** | **Enterprise** |
|---|---|---|---|
| who it is for | one team, one to three repositories, one person who runs it | a company with a hosted forge and a real board, several people on one panel | a security review, several projects, a product owner, a promotion chain, audit |
| the door | one machine ([one-machine](../setup/one-machine.md)) or the compose stack on one host | the compose stack on a server the team reaches | the compose stack hardened on the client's infrastructure, or a cloud realisation through an add-on |
| forge / tracker / board | `local` rows, or GitHub with a PAT | GitHub App, Jira, or Azure DevOps | the same, under the organisation's own identity and policy |
| sandbox | `worktree` (one machine) or `container` | `container` | `container` with the client's own image and network, or a remote box add-on |
| people on the panel | one, open on a laptop | a token per person | OIDC against the identity provider; per-person product tokens; named approvers |
| merge policy | `human`, then `auto` when the numbers say so | `human`, `auto` per project with `risk: high` areas | `human` on high-risk components always; `auto` elsewhere after the graduation review |
| after the merge | nothing, or `post_merge_deploy:` | `post_merge_deploy:` | `environments:` + `promote:` with a human production gate |
| product role | off | optional | on, with a context repository and admins |
| support | the operator, community channels | a partner's business-hours desk | a partner's desk with severity 1 around the clock |
| upgrade currency | current release | current or previous | current or previous, staged in a non-production deployment first |
| typical pilot | 5 tickets in a week | 10–20 tickets in a month | per project, 20–30 tickets, security sign-off on the first |

The rest of this page is the **control catalogue**: what a certified implementation on each
profile must have, stated as something an auditor can check. `●` required, `○` recommended,
`–` not applicable.

## Controls

### A · Installation and shape

| control | Light | Standard | Enterprise | checked by |
|---|---|---|---|---|
| A1 version pinned in `.env.compose`, images pulled from the release, checksums verified | ○ | ● | ● | `.env.compose`, `SHA256SUMS` |
| A2 `openfactory preflight` names nothing missing at install | ● | ● | ● | its output |
| A3 the work directory is a host directory the operator owns (`OPENFACTORY_WORK_DIR`) | ● | ● | ● | `ls -ld` |
| A4 the Docker socket trade accepted in writing, or a remote box used | – | ● | ● | the design record |
| A5 the panel is not open on a reachable host (`OPENFACTORY_PANEL_TOKEN` set, or OIDC) | ○ | ● | ● | `.env.compose`, `doctor` |
| A6 a non-production deployment exists for staging upgrades | – | ○ | ● | the design record |
| A7 one deployment per forge organisation (a second organisation is a second deployment) | ● | ● | ● | `project list` |

### B · Credentials

| control | Light | Standard | Enterprise | checked by |
|---|---|---|---|---|
| B1 the box receives only the harness credential plus the `box.env` allow list | ● | ● | ● | the manifest, the registry, [SECURITY.md](../../SECURITY.md) |
| B2 the forge credential is a GitHub App with exactly the [permission table](../setup/github.md), or the platform-documented PAT; never `workflows` | – | ● | ● | the App's settings |
| B3 `.env.compose` is `0600`, git-ignored, and the stack is started with `--env-file`, never `.env` | ● | ● | ● | `ls -l`, the runbook |
| B4 secrets live in the deployment's secret store, not in a checkout | ○ | ● | ● | the design record |
| B5 a credential rotation schedule exists and the last rotation is dated | – | ○ | ● | the maintenance calendar |
| B6 a token pool is configured where limits are hit, and the panel shows `index/N` | – | ○ | ● | the panel |
| B7 release approvers are named people with scrypt-hashed passwords; `OPENFACTORY_APPROVERS` from the secret store where a home directory cannot be mounted | – | ● (if a gate exists) | ● | `approver list` |
| B8 people are identified per person (`OPENFACTORY_PANEL_TOKENS` / `OPENFACTORY_PRODUCT_TOKENS`, or OIDC); a shared token is read-only by construction | – | ● | ● | `.env.compose` |

### C · The box and egress

| control | Light | Standard | Enterprise | checked by |
|---|---|---|---|---|
| C1 the box is proven per repository and the proof is current | ● | ● | ● | `box status` |
| C2 the toolchain the proof pins is recorded; a client image's rebuild triggers a re-proof | ○ | ● | ● | `box status`, the calendar |
| C3 egress is understood: harness endpoint, forge and tracker, package registries; an allowlist exists where the network is restricted | ○ | ○ | ● | the security checklist |
| C4 a TLS-intercepting CA is trusted by the client's own image, not by patching the stock one | – | ○ | ● | the image's build |
| C5 `box.network` names the network the design chose; the default `bridge` is a decision, not an accident | – | ○ | ● | the registry |
| C6 the dependency cache volume, if any, is per project and its package-manager variables are declared | – | ○ | ○ | the registry, `box.env` |

### D · The quality floor and merge

| control | Light | Standard | Enterprise | checked by |
|---|---|---|---|---|
| D1 every repository declares `validate.test`; `security` is declared or inherited; no gate is absent, only `advisory` | ● | ● | ● | `openfactory conformance <project>` |
| D2 the manifest was merged by the client, never by the implementer | ● | ● | ● | the pull request |
| D3 the branch-protection standard is applied: PR required, linear history, auto-merge allowed, head branches deleted, Checks: Read granted | – | ● | ● | the forge's settings |
| D4 required status checks are only checks that run on every PR and are deterministic | – | ● | ● | the forge's settings |
| D5 `merge_policy: human` during the pilot; `auto` only after the graduation review | ● | ● | ● | the manifest's history |
| D6 high-risk components declared with `risk: high` | ○ | ● | ● | the manifest |
| D7 `review_mode` chosen deliberately (advisory or blocking) and recorded | ○ | ● | ● | the design record |
| D8 the e2e workflow, where one spans repositories, is declared and dispatched, never implemented by the factory | – | ○ | ● | the manifest |

### E · After the merge

| control | Light | Standard | Enterprise | checked by |
|---|---|---|---|---|
| E1 what happens after a merge is declared — nothing, a deploy watch, or a chain — and the ticket says so | ● | ● | ● | a finished ticket's comment |
| E2 the production gate is a named approver with a password on the panel, never chat | – | ● (if a chain) | ● | the release form |
| E3 a `url:` is declared for the stage a person validates | – | ○ | ● | the manifest |
| E4 the promotion chain runs on a remote box, or the design uses the deploy watch instead | – | ● | ● | `doctor`'s `post_merge` line |

### F · Product and requirements

| control | Light | Standard | Enterprise | checked by |
|---|---|---|---|---|
| F1 the three declarations agree (registry, context repository, source manifests) | – | ● (if on) | ● | `product init` output |
| F2 a legacy corpus arrives as `observed`; acceptance is a person's act | – | ● (if on) | ● | the context repository's history |
| F3 the `docs_repo:` pointer is committed by the client, never written by the platform | – | ● (if on) | ● | the source manifest |
| F4 the module map is published and refreshed after merges | ○ | ● | ● | the knowledge branch |

### G · Operations, support, maintenance

| control | Light | Standard | Enterprise | checked by |
|---|---|---|---|---|
| G1 a named operator and a backup | ● (one person) | ● | ● | the runbook |
| G2 the cadences of [§4](01-delivery-method.md#4--operate) are kept and logged | ○ | ● | ● | the operator's log |
| G3 the cost dashboard is read against a budget | ○ | ● | ● | the log |
| G4 the support tier is contracted and severities map to the platform's failure classes | – | ● | ● | the contract |
| G5 upgrade currency: current or previous release; post-upgrade `doctor` and `box status` recorded | ○ | ● | ● | the calendar |
| G6 the backup set of [§6.4](01-delivery-method.md#64-backup-and-recovery) is taken on a schedule and a restore was tested | ○ | ● | ● | the calendar |
| G7 engine retention is at least the default 30 days; journals are on a volume that survives `down` | ● | ● | ● | `docker-compose.yml`, `OPENFACTORY_LOG_DIR` |
| G8 conversations are deleted on request (`project forget-conversations`) and the retention of 180 days is known to the client | – | ○ | ● | the runbook |
| G9 security advisories are applied within the tier's window | ○ | ● | ● | the calendar |

### H · Governance and audit (Enterprise)

| control | Light | Standard | Enterprise | checked by |
|---|---|---|---|---|
| H1 the security review checklist signed before implementation | – | – | ● | the signed checklist |
| H2 the design record re-signed annually | – | ○ | ● | the record |
| H3 every action on the panel is attributable to a person (identity), and the bot's identity is the factory's, never a human's | – | ● | ● | the journals |
| H4 a DR test performed at go-live and after major upgrades | – | – | ● | the calendar |
| H5 the model route keeps traffic inside the approved account or gateway where the policy requires it | – | – | ● | the registry (`model:`), the design record |

## Moving between profiles

A Light deployment becomes Standard by adding the controls the Standard column requires; nothing
is reinstalled. The usual order is A5 (a panel token), B2 (a GitHub App instead of a PAT), D3
(branch protection), G4 (a support contract). Standard to Enterprise is a design pass: H1 first,
then B8 (identity), C3–C5 (egress and the client's image), E2–E4 (a chain with a gate), and A6 (a
non-production deployment).

Going the other way is also allowed — a company that never needs a promotion chain is not made to
run one — and the design record says which profile the deployment claims. A certified partner's
attestation names the profile.
