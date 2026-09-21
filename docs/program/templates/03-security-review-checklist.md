# Security review checklist

Phases 1 and 2 of the [delivery method](../01-delivery-method.md). Required on the Enterprise
profile before implementation; recommended on Standard. Each row cites the platform document
that answers it.

| | |
|---|---|
| deployment | |
| profile claimed | |
| reviewed by (client security) | |
| prepared by (architect, credential number) | |
| platform version | |
| date | |

## A · Where things run and what they can reach

| # | question | answer | source |
|---|---|---|---|
| A1 | Where do the worker, the panel, the engine and the boxes run? Who administers those hosts? | | design record §2.1 |
| A2 | The worker mounts the host's Docker socket (root-equivalent on that host). Is the host dedicated, or is a remote box used instead? | | README, `docker-compose.yml` |
| A3 | Egress: the harness endpoint, the forge and tracker, package registries. Is there an allowlist, a proxy, a re-signing CA? Which image trusts the CA? | | `docs/architecture.md` §5 |
| A4 | The box has full outbound network by default. What does `box.network` name? | | ADR-0037, the registry |
| A5 | Model route: direct, Bedrock, Vertex, gateway. Does traffic stay inside the approved account? | | ONBOARDING §11, the registry `model:` |

## B · Credentials

| # | question | answer | source |
|---|---|---|---|
| B1 | The container box receives only the harness credential plus `box.env`. What does `box.env` list, and why each name? | | `SECURITY.md`, the registry |
| B2 | Which judging roles run in a worktree, and which of the published thirteen names can they read on this deployment? | | `SECURITY.md` |
| B3 | The forge credential: a GitHub App with exactly the permission table, or a PAT? Which scopes? Never `workflows`? | | `docs/setup/github.md` |
| B4 | On Azure DevOps, one PAT serves tracker and forge; are those jobs on the container box? | | `SECURITY.md`, `docs/setup/azure-devops.md` |
| B5 | Where do secrets live (`.env.compose` 0600, a secret store)? Who can read them? Rotation schedule? | | design record §2.3 |
| B6 | Is a token pool used? Where is it sourced? The panel shows only `index/N` and a fingerprint — confirmed? | | `docs/rotation-and-retention.md` §1 |
| B7 | The bot's identity (name, e-mail, login) is the factory's, never a person's | | `.env.compose.example` |

## C · People and authorisation

| # | question | answer | source |
|---|---|---|---|
| C1 | The panel is not open (`OPENFACTORY_PANEL_TOKEN` set, or OIDC). On a reachable host, per-person identity? | | `docs/reference/cli.md` (`serve`) |
| C2 | Identity: `local` invitations or OIDC? Issuer, groups, unverified-email policy? | | `openfactory/identity/` |
| C3 | Who is in `admins` and `product.admins`? An empty list means nobody — intended? | | `policy/authz.py` |
| C4 | Release approvers: named, password hashed (scrypt), stored where? Production never released from chat? | | `docs/reference/product-role.md` §3, ADR-0016 |
| C5 | Every write on the panel attributable to a person? | | the journals |

## D · The pipeline's control of version control

| # | question | answer | source |
|---|---|---|---|
| D1 | The agent cannot push, open pull requests or merge; the framework does, on the host | | `docs/operations.md` |
| D2 | `.github/workflows/**` changes are reverted before commit and listed as a human to-do | | STATUS "Deliberately not built" |
| D3 | Branch protection: PR required, linear history, no force push; required checks chosen from checks that run on every PR | | `docs/operations.md` §Branch-protection standard |
| D4 | `merge_policy: human` for the pilot; the conditions of `auto`; `risk: high` on auth, billing, migrations, infrastructure | | ONBOARDING §11b |
| D5 | Gate suppression (`noqa`, `nosec`, `type: ignore`, coverage pragmas) disarms auto-merge and routes to a human | | `SECURITY.md`, ADR-0011 |
| D6 | The quality floor cannot be switched off; `advisory: true` is the only escape | | `policy/floor.py` |
| D7 | `protected_paths` includes `.openfactory/**` and what else? | | `policy/protected.py` |

## E · Data

| # | question | answer | source |
|---|---|---|---|
| E1 | What data leaves the client's machines: prompts and diffs to the harness vendor; tickets and pull requests to the forge. Nothing to the project (no telemetry) | | README |
| E2 | Retention: engine 30 days, journals until deleted, conversations 180 days, resume 7 days. Acceptable? | | `docs/rotation-and-retention.md` |
| E3 | Deletion on request: `project forget-conversations` | | `docs/reference/cli.md` |
| E4 | Backups: what is in the set, where it goes, who can read it | | [method §6.4](../01-delivery-method.md#64-backup-and-recovery) |
| E5 | A hosting provider (if any): one deployment per organisation; the hosting standard | | [06](../06-support-and-maintenance-standard.md#the-hosting-standard) |

## F · Vulnerability handling

| # | question | answer | source |
|---|---|---|---|
| F1 | The project's security policy: private reporting, 72-hour acknowledgement | | `SECURITY.md` |
| F2 | Who applies a security patch and within what window | | [06](../06-support-and-maintenance-standard.md) |
| F3 | Pre-1.0: only `main` receives fixes; currency rule accepted | | `SECURITY.md` |

## Sign-off

- [ ] every row answered with a source
- [ ] open items, each with an owner and a date:

Signed: client security ________ date ____ · architect ________ date ____
