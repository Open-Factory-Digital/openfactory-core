# ADR 0016 — Acting from Slack: read for all, write behind an allowlist

- **Status:** **Accepted; v3 shipped** (resume/skip from Slack, gated).
- **Date:** 2026-07-22
- **Relates to / amends:** ADR-0015 (the tech-lead: diagnosis + Slack, one brain / two triggers). This is the v3 "act" trigger + its authorization model.

## Context

ADR-0015 v2 made the tech-lead conversational in Slack: anyone in a project's channel can `@mention`
it and get a read-only answer (status, what's happening, why a job parked). v3 lets it also **act** —
`resume` / `skip` a parked job — from the same Slack thread, so an operator never has to leave the
channel to unblock the floor. But actions are powerful and the channel may hold non-operators, so
"anyone who can ask can also act" is wrong. We need an authorization boundary that is simple, safe by
default, and consistent with the platform's existing "prod is always human-authenticated" rule.

## Decision

**Read for everyone in the channel; write behind a per-project allowlist; prod stays out of Slack
entirely.**

- **Read (v2)** — any Slack user who can post in the project's channel can ask and get an answer. No
  gate; it's read-only.
- **Write (v3)** — the tech-lead executes an action ONLY when the requesting Slack user id is in that
  project's `Project.slack_admins` allowlist (in the registry, per project — like `slack_channel`).
  **Empty allowlist = nobody can act = read-only for all** (the safe default; a project opts into
  Slack actions explicitly). An unauthorized action request gets a clear "you can ask, not act" reply
  and is logged — never silently ignored, never executed.
- **Scope of writable actions:** only `resume` and `skip` on a **parked impediment** (the job must be
  awaiting an operator — verified via the workflow's `awaiting_action` query before signalling). The
  action is delivered as the existing `act_on_impediment` Temporal signal — the SAME path the panel
  button uses, so Slack is just another transport for a decision the framework already models.
- **Hard boundary — prod is never actionable from Slack.** Prod release / tag / deploy-to-prod stay
  human-authenticated through the approver flow (identity + password, ADR-0001 D-12). Slack actions
  cannot promote to prod, full stop — even for an admin. Slack acts on the *floor* (unblock a parked
  job), not on *releases*.

Per-project, because isolation is per-project (ADR-0015): one project's admins are not another's,
and each lives in its own workspace, so Slack user ids only ever authorize actions in their own
project.

## Consequences

- The common case — an operator unblocking a parked job from their phone — is one Slack message, gated
  to the people who should have it. No panel round-trip.
- Safe by default: a freshly-configured project's channel is read-only until someone adds admin user
  ids to its registry entry, so enabling Slack chat never accidentally hands out action rights.
- The blast radius of a Slack action is exactly a panel Resume/Skip — bounded by single-line-strict
  (ADR-0010) and the same guardrails; it cannot touch prod.
- Allowlist by raw Slack user id is coarse (no roles/2FA). Acceptable for v3 (small trusted teams);
  a richer identity model (roles, or tying Slack ids to the approver registry) is a later ADR if a
  deployment needs it. The prod boundary already covers the highest-risk action.
- **Deferred:** confirmation-on-destructive (a "are you sure?" for skip, which discards work) and an
  audit trail of who-acted-from-Slack beyond the logs — noted, not built.
