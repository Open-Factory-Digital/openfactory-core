# Deployment profiles

A profile is a named set of controls that a certified implementation must have in place. There
are three: Light, Standard and Enterprise. All three run the same Apache-2.0 build with every
feature available. The profile determines which controls are required, how deep each phase of
the [delivery method](01-delivery-method.md) goes, and which support tier applies. A partner's
attestation for a deployment names its profile, and audits check the controls for that profile.

## Profile summary

| | Light | Standard | Enterprise |
|---|---|---|---|
| Typical customer | One team, one to three repositories, one person operating | A company with a hosted forge and a board, several people on one panel | Several projects, a security review, a product owner, a promotion chain, audit requirements |
| Door | One machine ([one-machine.md](../setup/one-machine.md)) or the compose stack on one host | Compose stack on a server the team can reach | Compose stack hardened on customer infrastructure, or a cloud realisation through an add-on |
| Forge / tracker / board | `local` rows, or GitHub with a PAT | GitHub App, Jira or Azure DevOps | The same, under the organisation's identity and policy |
| Sandbox | `worktree` (one machine) or `container` | `container` | `container` with a customer image and network, or a remote box add-on |
| Panel access | One person; open on a laptop | Token per person | OIDC; per-person product tokens; named approvers |
| Merge policy | `human`, then `auto` after the pilot | `human`; `auto` per project with `risk: high` areas | `human` on high-risk components; `auto` elsewhere after the graduation review |
| After the merge | Nothing, or `post_merge_deploy:` | `post_merge_deploy:` | `environments:` and `promote:` with a human production gate |
| Product role | Off | Optional | On, with a context repository and admins |
| Support tier | Community | Standard | Premium or Enterprise |
| Upgrade currency | Current release | Current or previous | Current or previous, staged on a non-production deployment first |
| Pilot | 5 tickets in a week | 10–20 tickets in a month | Per project, 20–30 tickets, security sign-off on the first |

## Control catalogue

Legend: **●** required, **○** recommended (the decision must be recorded), **–** not applicable.

### A. Installation and shape

| # | control | Light | Standard | Enterprise | verified by |
|---|---|---|---|---|---|
| A1 | Version pinned in `.env.compose`; images pulled from the release; checksums verified | ○ | ● | ● | `.env.compose`, `SHA256SUMS` |
| A2 | `openfactory preflight` reports nothing missing at install | ● | ● | ● | Output |
| A3 | `OPENFACTORY_WORK_DIR` is a host directory owned by the operator | ● | ● | ● | `ls -ld` |
| A4 | Docker socket mount accepted in writing, or a remote box used | – | ● | ● | Design record |
| A5 | Panel not open on a reachable host (`OPENFACTORY_PANEL_TOKEN` or OIDC) | ○ | ● | ● | `.env.compose`, `doctor` |
| A6 | Non-production deployment exists for staging upgrades | – | ○ | ● | Design record |
| A7 | One deployment per forge organisation | ● | ● | ● | `project list` |

### B. Credentials

| # | control | Light | Standard | Enterprise | verified by |
|---|---|---|---|---|---|
| B1 | Box receives only the harness credential plus the `box.env` allow list | ● | ● | ● | Manifest, registry, [SECURITY.md](../../SECURITY.md) |
| B2 | Forge credential is a GitHub App with the documented [permission table](../setup/github.md), or the documented PAT; never `workflows` | – | ● | ● | App settings |
| B3 | `.env.compose` is mode 0600, git-ignored; stack started with `--env-file`, never `.env` | ● | ● | ● | `ls -l`, runbook |
| B4 | Secrets in a secret store, not in a checkout | ○ | ● | ● | Design record |
| B5 | Credential rotation schedule exists; last rotation dated | – | ○ | ● | Maintenance calendar |
| B6 | Token pool configured where limits are hit; panel shows `index/N` | – | ○ | ● | Panel |
| B7 | Release approvers are named people with scrypt-hashed passwords | – | ● (if a gate exists) | ● | `approver list` |
| B8 | People identified per person (`OPENFACTORY_PANEL_TOKENS`, `OPENFACTORY_PRODUCT_TOKENS`, or OIDC); shared tokens are read-only | – | ● | ● | `.env.compose` |

### C. Box and egress

| # | control | Light | Standard | Enterprise | verified by |
|---|---|---|---|---|---|
| C1 | Box proven per repository; proof current | ● | ● | ● | `box status` |
| C2 | Pinned toolchain recorded; customer image rebuilds trigger a re-proof | ○ | ● | ● | `box status`, calendar |
| C3 | Egress documented (harness endpoint, forge and tracker, package registries); allowlist where the network is restricted | ○ | ○ | ● | Security checklist |
| C4 | TLS-intercepting CA trusted in the customer's image, not by patching the stock image | – | ○ | ● | Image build |
| C5 | `box.network` set deliberately | – | ○ | ● | Registry |
| C6 | Dependency cache volume, if used, is per project with package-manager variables declared | – | ○ | ○ | Registry, `box.env` |

### D. Quality floor and merge

| # | control | Light | Standard | Enterprise | verified by |
|---|---|---|---|---|---|
| D1 | Every repository declares `validate.test`; `security` declared or inherited; no gate absent, only `advisory` | ● | ● | ● | `openfactory conformance <project>` |
| D2 | Manifest merged by the customer, not the partner | ● | ● | ● | Pull request |
| D3 | Branch-protection standard applied | – | ● | ● | Forge settings |
| D4 | Required status checks run on every PR and are deterministic | – | ● | ● | Forge settings |
| D5 | `merge_policy: human` during the pilot; `auto` only after the graduation review | ● | ● | ● | Manifest history |
| D6 | High-risk components declared `risk: high` | ○ | ● | ● | Manifest |
| D7 | `review_mode` chosen and recorded | ○ | ● | ● | Design record |
| D8 | Cross-repository e2e workflow declared and dispatched, never implemented by the factory | – | ○ | ● | Manifest |

### E. After the merge

| # | control | Light | Standard | Enterprise | verified by |
|---|---|---|---|---|---|
| E1 | Post-merge behaviour declared (nothing, deploy watch, or chain); the ticket states it | ● | ● | ● | A finished ticket |
| E2 | Production gate is a named approver with a password on the panel | – | ● (if a chain) | ● | Release form |
| E3 | `url:` declared for the stage a person validates | – | ○ | ● | Manifest |
| E4 | Promotion chain on a remote box, or deploy watch on a local box | – | ● | ● | `doctor` `post_merge` line |

### F. Product and requirements

| # | control | Light | Standard | Enterprise | verified by |
|---|---|---|---|---|---|
| F1 | The three declarations agree (registry, context repository, source manifests) | – | ● (if enabled) | ● | `product init` output |
| F2 | Legacy corpus adopted as `observed`; acceptance is a person's act | – | ● (if enabled) | ● | Context repository history |
| F3 | `docs_repo:` committed by the customer | – | ● (if enabled) | ● | Source manifest |
| F4 | Module map published and refreshed after merges | ○ | ● | ● | Knowledge branch |

### G. Operations, support, maintenance

| # | control | Light | Standard | Enterprise | verified by |
|---|---|---|---|---|---|
| G1 | Named operator and backup | ● | ● | ● | Runbook |
| G2 | Cadences in [phase 4](01-delivery-method.md#phase-4-operate) kept and logged | ○ | ● | ● | Operator's log |
| G3 | Cost dashboard reviewed against a budget | ○ | ● | ● | Log |
| G4 | Support tier contracted; severities mapped to the platform's failure classes | – | ● | ● | Contract |
| G5 | Upgrade currency met; post-upgrade `doctor` and `box status` recorded | ○ | ● | ● | Calendar |
| G6 | Backup set taken on schedule; restore tested | ○ | ● | ● | Calendar |
| G7 | Engine retention at least 30 days; journals on a volume that survives `down` | ● | ● | ● | `docker-compose.yml`, `OPENFACTORY_LOG_DIR` |
| G8 | Conversation deletion on request; 180-day retention communicated to the customer | – | ○ | ● | Runbook |
| G9 | Security advisories applied within the tier's window | ○ | ● | ● | Calendar |

### H. Governance and audit

| # | control | Light | Standard | Enterprise | verified by |
|---|---|---|---|---|---|
| H1 | Security review checklist signed before implementation | – | – | ● | Signed checklist |
| H2 | Design record re-signed annually | – | ○ | ● | Record |
| H3 | Panel actions attributable to a person; the bot's identity is the factory's | – | ● | ● | Journals |
| H4 | DR test at go-live and after major upgrades | – | – | ● | Calendar |
| H5 | Model route keeps traffic inside the approved account or gateway where policy requires | – | – | ● | Registry `model:`, design record |

## Changing profile

Moving from Light to Standard adds the Standard controls; nothing is reinstalled. The usual
order is A5, B2, D3, G4. Moving from Standard to Enterprise starts with H1, then B8, C3–C5,
E2–E4 and A6. A deployment may also claim a lower profile than it could; the design record states
the profile claimed.
