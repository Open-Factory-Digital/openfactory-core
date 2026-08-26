"""The ticket — the atomic unit of work (ADR-0001 D-5: one ticket = one PR).

A ticket is born on the board (GitHub Issue / Jira). The BoardAdapter parses the
board's native representation into this shape. The ticket-level spec is always
required; the SPEC_VALIDATION gate checks its quality deterministically (D-8).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AcceptanceCriterion(BaseModel):
    text: str
    # Optional pointer to the test/evidence expected to satisfy it. The reviewer
    # maps criteria to evidence; the platform runs the tests independently.
    verified_by: str | None = None


class Ticket(BaseModel):
    id: str  # board-native ref, e.g. "#142" or "PROJ-31"
    title: str
    objective: str
    context: str | None = None

    in_scope: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)
    acceptance_criteria: list[AcceptanceCriterion] = Field(default_factory=list)

    # Declared dependencies are deterministic truth (D-7). Inferred ones are only
    # advisory and must be confirmed by a human before landing here.
    depends_on: list[str] = Field(default_factory=list)

    # Human-curated pointers to reference docs relevant to this ticket. ADRs are
    # loaded regardless; this is for the large architecture docs (D-9).
    relevant_docs: list[str] = Field(default_factory=list)

    repo: str
    base_branch: str | None = None  # falls back to the manifest's base_branch

    #: Whether the tracker still considers this ticket OPEN — `"open"` / `"closed"`, or None when
    #: the provider was not asked.
    #:
    #: THE FIELD DID NOT EXIST AND THREE LAYERS HID IT. `scan_todo` guards against re-running a
    #: delivered ticket with `getattr(ticket, "state", "open")`; `GitHubTracker.get_ticket` never
    #: requested `state` from `gh`; and pydantic drops unknown keys silently, so even the one
    #: place that passed `state=` was discarded. The getattr default therefore always answered
    #: "open", the stale-card branch could never execute, and the tests were green because every
    #: double invented the attribute the real contract lacked (`type("_Tk", (), {"state": ...})`).
    #:
    #: The cost was live: a closed card left in the pickup column re-ran, burned a full agent
    #: pass, and parked the single job slot — which is the exact waste the guard was written to
    #: stop. A promise the answer SHAPE cannot express is one no call site can keep.
    state: str | None = None

    # Board/issue labels — used to route special tickets (e.g. an `e2e` label means "just run
    # the e2e suite", no plan/execute — ADR-0008). Lowercased for stable matching.
    labels: list[str] = Field(default_factory=list)

    # Who opened the ticket. There is no assignee in a lights-out flow (the bot is a GitHub App,
    # not a user), so on a park (Needs Action) the escalation is routed back to the CREATOR —
    # @-mentioned on the ticket and spoken by the coordinator (portal toast now, Slack later).
    author: str | None = None

    raw: str = ""  # the original board body, kept for the executor's full context
