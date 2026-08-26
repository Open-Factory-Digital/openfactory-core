# ADR 0015 — The tech-lead: impediment diagnosis + Slack, one brain, two triggers

- **Status:** **Accepted; v1 shipped** (proactive diagnosis → ticket + Slack). v2/v3 (conversational) planned.
- **Date:** 2026-07-22
- **Relates to / amends:** ADR-0001 (Notifier port; the Coordinator), ADR-0004/0009/0010 (react-don't-block; single-line park). Gives the coordinator the ADR its docstring placeholdered as "ADR-00XX".

## Context

When a job parks on an impediment, the framework did the *escalation* half right — it parked with
options, reconciled the board to Needs Action, and posted a comment — but the comment was the **raw
error** (`note = f"box failed: {redact(str(exc))}"`). A human (our partner) had to read the stderr,
open the repo, diagnose the root cause, and re-scope by hand. In the live case (#412, Plan 96c) the
bot posted `[failed] ... refusing to allow a GitHub App to create or update workflow ci.yml without
workflows permission`; a human then wrote the actual diagnosis and re-queued it. The "tech lead" was
a **principle staffed by a person**, not code.

The Notifier port (Telegram) and a read-only advisory Coordinator (`advise()` over a decision) already
existed — but neither ran on the box-failure path, and the notifier had no Slack impl. We are also
about to add Slack; piping the raw note into a new channel would just deliver noise faster.

## Decision

Build the tech lead as **one brain + one toolset (read project state + act), invoked by two triggers**:
proactively on an impediment (v1, this ADR), and reactively from Slack (v2/v3, planned). v1:

1. **HandOff** (`contracts/decision.py`) — a structured impediment diagnosis: `headline`,
   `what_happened`, `why`, `correction` (a prior comment it verified as WRONG), `recommendation`
   (free-form, not limited to resume/skip), `alternatives`. Rendered to **GitHub markdown** on the
   ticket (durable record) and **Slack mrkdwn** in the channel (the voice) — same brain, two surfaces.
2. **`diagnose()`** (`adapters/agent/claude_code.py`, role `techlead.md`) — a read-only agent that,
   unlike the advisory coordinator's empty workspace, runs over a **real checkout** so it verifies
   claims against the code and can refute a wrong prior comment. Planner-tier, never edits.
3. **`diagnose_impediment`** activity (`runtime/temporal/activities.py`) — on a park it gathers the
   error + ticket + recent comments, shallow-clones the repo, runs `diagnose()`, and posts the HandOff
   to the ticket AND Slack. Best-effort and bounded; on any trouble the raw note still stands.
4. **`SlackNotifier`** (`adapters/notify/slack.py`) — drop-in on the existing Notifier port. **Slack
   is PER-PROJECT** (`notifier_for_project`): one deployment hosts N projects (shared
   worker/panel/Temporal), but each project has its OWN Slack workspace + channel + bot — full
   isolation on the client-facing surface (one project's workspace shares nothing with another's).
   The channel (non-secret) lives in the registry alongside repo + board (`Project.slack_channel`);
   the bot token is workspace-scoped and secret — the registry names the env var that carries it
   (`Project.slack_bot_token_env`, default `SLACK_BOT_TOKEN`), injected per-token from SSM.

Wired at the existing park site under a new `workflow.patched("park-techlead-diagnosis")` guard, so an
in-flight job replaying pre-fix history stays deterministic (replay-safety, as ADR-0009). The raw
`[failed]` comment stays as the machine audit trail; the HandOff is the human diagnosis alongside it.

**Guardrail interaction (why the diagnosis matters, not just the fix):** some diffs are human-only by
design — the bot has no `workflows` permission, so a push touching `.github/workflows/**` is *rejected
by GitHub on purpose*. We do **not** grant that permission (it would let the agent rewrite its own CI
gates). The tech lead's job is to *name* that boundary in plain language and route the human, not to
work around it.

## Consequences

- The human gets a diagnosis, not a stderr — on the ticket and in Slack. The role the partner filled by
  hand is now code (v1: it speaks; v2/v3: it also answers questions and acts).
- Slack is optional and additive: a project with no channel ⇒ Null notifier ⇒ silent. Per-project
  isolation is the model — one deployment fans out to N workspaces, each project its own bot/channel
  (terraform `slack_bot_tokens` maps env-var-name → SSM path, one token per workspace; channel in the
  registry). Isolation boundary is the PROJECT, not the deployment.
- One new patched command; the diagnosis is bounded and never blocks the park (react-don't-block).
- **Deferred to v2/v3:** two-way Slack (Socket Mode listener → ask status / what's happening), and
  write-actions from Slack (resume/skip/move) behind an **authorization model** — read for the group,
  writes gated by identity; prod release stays human-authenticated. That authorization model gets its
  own ADR when v3 lands.
