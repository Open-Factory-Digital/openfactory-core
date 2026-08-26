# ADR 0040 — The core runs on the client's own machines; a cloud is an add-on

- **Status:** **Accepted**
- **Date:** 2026-08-06
- **Relates to:** ADR-0038 (the platform is complete on its own; channels are add-ons — the same
  shape, one layer down), ADR-0022 / ADR-0034 (provider seams and the extension model),
  ADR-0001 D-12 (the platform triggers; the client's pipeline executes),
  [`docs/core/07-extensibility.md`](../core/07-extensibility.md).

## Context

ADR-0038 settled that **channels** are add-ons: the panel is complete on its own and Slack is a
transport somebody may or may not buy. The same question exists one layer down and had never been
written: **what does the platform need from the machine it runs on?**

It came up because a board card was titled *"the panel's approval vault needs the secret in SSM"*
and the product owner read it and asked the right question:

> *"but isn't that an AWS coupling? we are making everything agnostic — this whole undertaking
> exists precisely so there is no provider dependency; it is the open-source core."*

The answer was no, and the only way to give it was to go and measure — which is the wrong shape for
the claim the whole project rests on. The product owner then stated the principle directly, and it
is worth recording verbatim because it draws the line in exactly the right place:

> *"the focus here is to leave the core 100% usable by any company. What matters — and there is no
> way around it — is reading Jira, GH, DevOps boards, GHA, DevOps pipelines. But the worker, the
> job, everything that CIRCULATES, has to be local — not least because the client may simply want
> to stand up machines (EC2, say) instead of using Fargate."*

## Decision

**Two categories, and the line between them is whether the dependency is on the CLIENT'S WORLD or
on OUR deployment's.**

### D1 — Vendor coupling is legitimate exactly where the client already lives

Reading Jira, GitHub, Azure Boards; observing GitHub Actions or Azure Pipelines; pushing to Azure
Repos — these are not compromises. They are the product. A client on Jira needs a Jira adapter and
no amount of architecture removes that. Nine axes dispatch through registries so a provider is
*configuration*, and the second vendor on four of them proved the seam holds.

### D2 — Everything that CIRCULATES runs on the client's own machines

The worker, the job, the sandbox, the durable engine, the panel: none of these may require a
specific cloud. A client who prefers to run EC2 instances, on-prem servers or a Kubernetes cluster
must get the whole platform, not a degraded one. Concretely, and true as of this ADR:

| | |
|---|---|
| `docker-compose.yml` | a complete stack — Postgres, Temporal, worker, panel. No cloud |
| `default_sandbox()` | answers `container`; `fargate` only when `SDLC_FARGATE_CLUSTER` is set |
| boxes | `worktree` (no daemon) · `container` (local Docker) · `fargate` (opt-in) |
| `boto3` | not a core dependency — it lives in the `runtime`/`sandbox`/`slack` extras |
| every cloud import | function-level, so importing the core never needs one |

### D3 — A cloud is an add-on, in ADR-0038's exact sense

We will help a client run this on AWS or Azure, and that help is a **paid or published add-on**,
not a prerequisite. The test is ADR-0038's: *the platform without it is complete, not hobbled.*
Remove the Fargate launcher and jobs still run in containers. Remove CloudWatch and events still go
to a file. Remove SSM and the approval vault still reads its env var.

### D4 — The claim is a TEST, not a sentence in this file

`tests/test_the_core_does_not_need_a_cloud.py` blocks every cloud SDK in a subprocess and imports
the core for real, asserts no cloud SDK is a core dependency, asserts every such import is
function-level, and asserts each observability axis keeps a cloud-free row. Each is
mutation-verified.

It deliberately does **not** assert "there is no AWS code". A provider being AVAILABLE is the
product working; a provider being UNAVOIDABLE is the product broken. Only the second is guarded.

## What this does NOT mean

- **Not that AWS is discouraged.** It is the reference deployment and stays supported.
- **Not that vendor code is quarantined.** `fargate/launcher.py` is honest, tested AWS code.
- **Not that the client supplies infrastructure design.** They supply machines; we supply the
  stack that runs on them.

## Consequences

**An import path is an architectural claim, and one of ours was false.** `runtime/fargate/
entrypoint.py` held thirteen symbols and **not one touched AWS** — it is the program that runs
inside the box, identical whether that box is a Fargate task, a container on the client's EC2, or a
pod. Yet `worker.py` imported `materialize_app_key` from it and `activities.py` imported
`BoxConfig` — the box's own configuration contract — from a folder named after a cloud vendor, on
paths that never go near one. Anybody reading those lines concludes the worker needs Fargate.

The code already obeyed D2. Only the address disagreed, and an address is what a reader believes.
It is now `sdlc/runtime/boxed_job.py`; `fargate/launcher.py`, whose five of six symbols are ECS and
CloudWatch, stays where it is. That split is the ADR in one directory listing.

**And the boundary has a name for each side.** The product owner settled it the same day: the
harness, its model and its credential are CONFIGURATION and therefore core — that is the platform
working, not an extra. What a client may or may not want is Slack (a channel, ADR-0038), a cloud
(a deployment, this ADR) and — commercially — the product role. But the product role is
**available on the platform**, not in a channel: a client who prefers to write their own tickets
and drop them in TO-DO simply does not use it, and one who wants it finds it in the panel.

"Add-on" is the right COMMERCIAL word and the wrong ARCHITECTURAL one, because it flattens three
things that already have their own seam — a channel, a deployment, a role. Keeping the commercial
word is fine; inventing a fourth mechanism to serve it is not. `pip` extras plus lazy imports
already carry the whole load: nothing outside `sdlc/product/` imports it at module scope (0 of 65),
and the core imports cleanly with `slack_sdk`, `temporalio`, `boto3` and `fastapi` each blocked.

**Measuring that claim immediately falsified half of it (#98).** The product role is reachable from
Slack and from two scheduled activities — and from NOWHERE ELSE. `runtime/slack/product_channel.py`
holds 2,165 lines and 54 functions; `actions/catalog.py` has zero product actions and `api/app.py`
zero product routes. So on a deployment without Slack the role sweeps and reconciles, and nobody
can talk to it. The decision above is correct and the code does not yet keep it.

**The next one to check is the panel.** It reads CloudWatch for logs and SSM for the approval
vault. Both degrade correctly today — the vault falls back to a file, events fall back to the file
sink — but "degrades correctly" and "is an add-on" are different claims, and only the first is
currently tested.
