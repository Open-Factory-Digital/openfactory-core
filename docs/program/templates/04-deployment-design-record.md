# Deployment design record

Phase 2 of the [delivery method](../01-delivery-method.md). Records every deployment decision
and its reason before installation. Re-signed annually. On the Light profile, answer the
headings in a single page kept beside the manifest.

| | |
|---|---|
| organisation, deployment name | |
| profile claimed | Light / Standard / Enterprise |
| architect (credential number) | |
| implementer (credential number) | |
| operator, backup | |
| security reviewer | |
| platform version at design; at last review | |
| date; last review date | |

## 2.1 Shape and topology

| decision | choice | reason |
|---|---|---|
| door | one machine / compose on one host / compose on a server / cloud realisation (add-on: ____) | |
| host(s): worker + panel + engine; boxes | | |
| ports: panel, engine, engine UI | | |
| `OPENFACTORY_WORK_DIR` | | |
| disk budget | | |
| named volumes and where they are backed up | | |
| non-production deployment (Enterprise) | | |
| one forge organisation served | | |

## 2.2 Provider axes

| axis | kind | options (by name, never a secret) | reason |
|---|---|---|---|
| tracker | | | |
| board | | columns / states | |
| forge | | | |
| CI observer | | | |
| harness: executor / reviewer / techlead / product | | `model:` per role | |
| channel | panel (+ add-on?) | | |
| notifier fallback | | | |
| sandbox | worktree / container / remote (add-on) | | |
| telemetry sink | | | |
| event sink | | | |
| identity | local / oidc | | |
| session store, token pool | | | |

## 2.3 Credentials and boundaries

| credential | holder | lives in | may do | readable by | rotation |
|---|---|---|---|---|---|
| harness (and pool) | | | | the box only | |
| forge (App / PAT) | | | the permission table | the host only | |
| tracker | | | | the host only | |
| panel tokens / OIDC | | | | | |
| product tokens | | | | | |
| approvers | | | release production | | |
| `box.env` allow list | | | | the box | |

Bot identity (name, e-mail, login): ____

## 2.4 The box

| decision | choice | reason |
|---|---|---|
| image: stock / client image (who builds it, when rebuilt) | | |
| toolchain the proof pins | | |
| `box.network` | | |
| `box.cache_volume` and package-manager variables | | |
| CA trust (re-signing network) | | |
| `cpus`, `memory` | | |

## 2.5 Quality floor and manifest, per repository

| repository | `setup:` | `validate.test` | `security` | `lint` / `type` | advisory gates | `components:` and `risk:` | `docs:` roles | `knowledge_map` | e2e | language |
|---|---|---|---|---|---|---|---|---|---|---|
| | | | | | | | | | | |

Budgets: `effort_budget_turns` ____ · `repair_max_attempts` ____ · `recovery_max_attempts` ____ · `max_cost_usd` ____ · `max_diff_lines` ____

## 2.6 Merge policy, branch protection, CI

| decision | choice | reason |
|---|---|---|
| `merge_policy` for the pilot; conditions for graduating to `auto` | human; | |
| `review_mode` | advisory / blocking | |
| branch protection to the standard (PR required, 0 reviews, linear, no force push, auto-merge on, delete head branches) | | |
| required status checks (every-PR, deterministic) | | |
| App granted Checks: Read | | |

## 2.7 After the merge

| decision | choice | reason |
|---|---|---|
| nothing / `post_merge_deploy:` / `environments:` + `promote:` | | |
| stages, `deploy_ref`, `health_url`, `url`, `validate_with` | | |
| production gate: approvers, `prod_tag_prefix` | | |
| on a local box: deploy watch only (the chain needs a remote box) | | |

## 2.8 The product role

| decision | choice | reason |
|---|---|---|
| on / off / later | | |
| context repository: existing / created by the factory / created by the client's process | | |
| `product.admins` | | |
| baseline adoption plan (`observed` → `accepted` by a person) | | |
| `docs_repo:` committed in each source repository by | | |

## 2.9 Operations

| item | value |
|---|---|
| operator, backup | |
| cadences (daily, weekly, monthly, quarterly) | as [method phase 4](../01-delivery-method.md#phase-4-operate), or: |
| where logs are read | |
| retention: engine days, journals, conversations | |
| backup set, schedule, destination, restore-test cadence | |
| upgrade policy and window | |
| support tier and escalation path | |

## 2.10 Cost governance

| item | value |
|---|---|
| monthly budget | |
| token pool | |
| `OPENFACTORY_MAX_CONCURRENT_JOBS` | 1 (reason to change: ) |
| who is told when a budget is exhausted | |
| weekly cost review by | |

## Open questions

| question | owner | date |
|---|---|---|
| | | |

## Signatures

operator ________ · security reviewer ________ (Enterprise) · implementer ________ · date ____
Annual review: ________ date ____ · profile re-claimed: ____
