"""Shared enums: the job lifecycle (ADR-0001 state machine) and risk levels."""

from __future__ import annotations

from enum import StrEnum


class JobState(StrEnum):
    """The v1 state machine from ADR-0001.

    TODO is intent (lives on the board). Only after SPEC_VALIDATION does a ticket
    become READY and be authorized to consume resources.
    """

    TODO = "todo"
    BLOCKED = "blocked"  # an unmet dependency prevents even starting
    ON_HOLD = "on_hold"  # started, hit an impediment → returned to the owner (an alarm)
    PAUSED = "paused"  # agent can't proceed for an infra reason (usage limit / auth) — halt + warn
    SPEC_VALIDATION = "spec_validation"
    NEEDS_REFINEMENT = "needs_refinement"  # gate failed → back to human, with reason
    READY = "ready"
    PREPARING = "preparing"
    PLANNING = "planning"  # the planner drafts a testable plan (plan→execute)
    IMPLEMENTING = "implementing"
    VALIDATING = "validating"
    REPAIRING = "repairing"  # bounded loop (max attempts / cost / runtime)
    REVIEWING = "reviewing"
    PR_OPEN = "pr_open"  # handed to human

    # --- Lifecycle beyond the PR (ADR-0001 D-12). The platform orchestrates &
    # observes these; the project's pipeline executes the actual deploys. ---
    CI_WAITING = "ci_waiting"  # waiting for the project's real CI to go green on the PR
    MERGED = "merged"  # gate passed (auto for low-risk+green; else human)
    STAGING_DEPLOYING = "staging_deploying"
    STAGING_VERIFYING = "staging_verifying"  # observe smoke/health
    AWAITING_PROD_APPROVAL = "awaiting_prod_approval"  # prod is human-gated by default
    PROD_RELEASING = "prod_releasing"
    PROD_VERIFYING = "prod_verifying"
    ROLLING_BACK = "rolling_back"  # safe pre-defined action; re-deploy last-good tag
    DONE = "done"

    #: A HUMAN TOLD THE FACTORY TO STOP — the ticket is unresolved and no longer queued.
    #:
    #: `skip` frees the floor, and until this existed the run kept the state it had BEFORE the
    #: person acted: the panel went on saying `on_hold`, the card stayed in *Needs Action*, and
    #: nothing on the ticket recorded that anybody had decided anything (pilot, 2026-08-16 —
    #: *"se foi skipped… o status não on_hold e sim skipped, ou seja, o que realmente aconteceu"*).
    #: The same shape as the merge that could not reach Done: a human acts and the record does not
    #: move.
    #:
    #: NOT `DONE`, deliberately: nothing was delivered, and a board where Done means "shipped" is
    #: the one report an operator must be able to trust. It is not `ON_HOLD` either — nobody is
    #: waiting. It is open work that is not being worked on, which is what a backlog is.
    SKIPPED = "skipped"

    FAILED = "failed"


class RiskLevel(StrEnum):
    """Per-component risk (ADR-0001 D-6). Drives how strong the human gate is."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"  # e.g. IaC, secrets, migrations — stronger human gate
