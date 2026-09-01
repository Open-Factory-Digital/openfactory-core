# Glossary — the canonical vocabulary

One place that fixes what each word means, so we never talk past each other. The three
words that matter most — **ticket**, **worker**, **job** — are defined first; the rest
support them. See [`architecture.md`](architecture.md) for how they fit
together and [`autonomous-flow.md`](autonomous-flow.md) for the timings.

## The three core terms

| Term | What it is | Lifetime | Role |
|---|---|---|---|
| **Ticket** (a.k.a. **issue**) | One unit of work on your board — the thing you write a spec for | Permanent (it's a card) | The *request* |
| **Worker** | The **always-on** service. The maestro: it stays up, watches the board, and **orchestrates**. A container in your compose stack by default | continuous | *Decides* what to do |
| **Box** (a.k.a. **job**) | An **ephemeral** container that spins up to do **one ticket** (clone → agent → test → push → PR), then dies. A throwaway Docker container by default | minutes, then gone | *Executes* the work |

The analogy: the **worker is the manager** (always in the office, watching the queue and
handing out work); a **job is a temp hire** brought in for one task, does it, leaves.

> ⚠️ **Avoid the bare word "task."** Container runtimes use it for any running container —
> both the worker and a box run *as* one — and in project-management speak it often means
> the *ticket*. To stay unambiguous we say **ticket** (the card), **worker** (the always-on
> maestro) and **box** (the ephemeral executor), and reserve "task" for when we literally mean
> a container runtime's own word.

## How they connect (the mechanics)

| Term | What it is |
|---|---|
| **Board** | Your project board, whichever vendor provides it. Its **TO-DO** column is the pickup queue — a ticket there is a request to run. |
| **Poller** | Not a separate machine — a *function the worker runs* every 3 min to scan the board's TO-DO column. "The worker doing the poll." Implemented as **PollWorkflow**. |
| **PollWorkflow** | The durable workflow (executed by the worker) that the engine's schedule fires every 3 min: scan projects → scan TO-DO → start a JobWorkflow per new ticket. |
| **JobWorkflow** | The **durable "story" of one ticket**, held by the durable engine and executed by the worker. It commands "launch a box", waits for the merge, drives promotion/approval/release. It survives crashes and can wait days. **This is different from a `box`:** the JobWorkflow *orchestrates* (it decides and waits); the **box** *does the coding work*. One commands, the other executes. |
| **Activity** | A single side-effecting step a workflow calls (e.g. `run_job`, `check_pr_merged`, `promote_staging`). Auto-retried by the engine → must be **idempotent**. |
| **Agent** | The coding agent — Claude Code, Codex, Kimi or OpenCode, per your configuration — that actually writes the code inside a box. |
| **Sandbox** | Where the agent works, isolated from everything else. Locally a `git worktree` or a throwaway container; in a cloud realisation the whole ephemeral task *is* the isolation boundary (D-17). |
| **Spec gate** | The refinement check at the start of a JobWorkflow: does the ticket have an objective + acceptance criteria? A weak spec stops at **NEEDS_REFINEMENT** — no job launched, no cost. |
| **Pre-flight (sizer)** | The sizing gate that runs on the **worker** *before* any job is launched (ADR-0013). A read-only agent pass judges the ticket by **INVEST** (one cohesive, independent, testable outcome — *not* by counting files). Verdict: **fit** (run), **split** (decompose), **unclear** (park with questions). |
| **Split** | When pre-flight judges a ticket too large, the framework **autonomously** creates `Plan Na`/`Plan Nb` children (ordered, full criteria), sends them to **TO-DO in order**, and closes the parent. Single-line strict runs them one at a time, each on the prior's merge. |
| **Needs Action** | The board column for tickets **parked waiting on a human decision** (`needs_refinement` / `on_hold` / `failed`) — kept separate from Backlog so they don't hide among un-started work. The "why" is in the ticket comment. `openfactory project init` creates it on a new GitHub board; on an existing board it is added by hand (exact name), and on Azure Boards it is a state you add once to an inherited process (docs/setup/azure-devops.md §3). |
| **Effort budget** | The ticket-wide cap on agent **turns** (`effort_budget_turns`), summed across execute + repairs + recoveries + resumes. The real size/effort governor; the per-invocation turn cap is only an anti-runaway backstop. |
| **Recovery ladder** | When the agent stops mid-work (stuck / turn cap), a bounded autonomous sequence — continue the same session, then a fresh recovery pass that may *simplify* scope — tries to finish it before any human is involved. Humans decide; agents debug. |
| **Review gate** | The independent automated review of the diff. A rejection **blocks auto-merge**; the PR waits for a human. |

## Deployment & config terms

| Term | What it is |
|---|---|
| **Durable engine** | What holds every workflow's state, timers and retries — the "database" of job state, which is why the platform needs no database of its own. It is [Temporal](https://temporal.io), open source, and it runs as a container in your own compose stack. A managed service is one way to run it, never a requirement. |
| **Schedule** | The engine's cron-like trigger (every 3 min, overlapping runs skipped) that starts the PollWorkflow. |
| **Sandbox kind** | Which container runtime a box gets: `container` (Docker on your own machine — the default), `worktree` (local/test, no isolation), or a cloud task. It is one row in the registry; the workflow does not change with it. |

| **Manifest** (`.openfactory/project.yaml`) | The per-project config: environments, gates, validation commands, reviewers, `merge_policy`. A new project is **data, not code**. |
| **Forge / Tracker / Board** adapters | The seams onto whatever hosts your code (PRs/merges), your issues, and your board. Swapping one changes an adapter, not the workflow. |
| **Promotion / environments** | Optional post-merge deploys (staging → prod), driven by the manifest's `environments`. Zero to N; prod is human-gated by default. |
| **Approval gate** | The one mandatory human touch (only when prod is configured): a durable signal, deadline 3 days, you're notified by push. |
| **Notifier** | An optional push channel that tells you when a human is needed, so you never poll the system. The panel already says it; a notifier just carries it somewhere you already look. |
| **OKF bundle** / **module map** | The *generated* knowledge artifact (`knowledge/modules.yaml` + `manifest.yaml`): "where things live" per module, plus a sha256 per source file. Derived from the code, never hand-written; the code stays ground truth and the map only accelerates finding it (ADR-0017). |
| **`.okf/repos/<owner>--<name>/`** | Where that bundle is persisted — a path inside the project's **context repository** (`<project>-context`, D-2/D-3), one folder per source repo, one commit per merge that changes sources. Never the client's own repo at all — the context repository is one the platform itself created. Requires `product.docs_repo` to be set. |
| **Knowledge Pipeline** | The post-merge step (`refresh_knowledge`) that regenerates the bundle and publishes it. Writes nothing when no source changed, so it converges instead of re-triggering itself. |
| **Stale / orphan (knowledge)** | The two guards that decide whether the map may be used at all. *Stale* = a tracked source's checksum no longer matches the job's checkout. *Orphan* = a `source:` link no longer resolves. Either one → the map is **not injected** and the agent searches the code as before. |

## What is *not* the platform

Wherever you run it, the same machine or account also holds the **applications** the platform
operates on — a client's own app, on its own infrastructure. Those are the *products*: the targets
the platform writes pull requests for and deploys into. The **platform itself** is only the
always-on **worker**, the ephemeral **boxes**, and the **durable engine** beside them. Two layers,
one place: the products (heavy, with their own infrastructure) and the thin factory on top that
operates them.

## Where a cloud fits

A cloud is an **add-on**, and none of the vocabulary above changes when you add one (ADR-0040).
The worker becomes a small always-on task, a box becomes an ephemeral one, the journal becomes a
managed table, the secrets file becomes a parameter store — and the words stay *worker*, *box*,
*journal*, *secret*. One worked example on one cloud ships with the `openfactory-aws` add-on
package so the mapping is readable; that package's own documents, and
[`configuration.md`](configuration.md), are where that vendor's own names live.
