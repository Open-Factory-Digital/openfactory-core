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

    #: Who ASKED for this card — not who created it. On a hand-written card the two are the same
    #: person; on a card the factory opened, `author` is the platform's own App and the requester
    #: is the person it was opened for. Read from a `requester:` front-matter key every body the
    #: factory writes now carries, else from the `Pedido por` / `Reportado por` / `Awaiting the
    #: acceptance of` lines older cards carry in prose; None when nothing says. Issue #33,
    #: decision 2 (2026-09-06): the person the plan calls is the card's requester, whoever wrote
    #: the card — so a card has to say, machine-readably, who that is.
    requester: str | None = None
    #: The same person, in the TRACKER's own namespace — a GitHub login, an Azure DevOps
    #: `uniqueName`, a Jira display name — when the deployment could resolve one at the time the
    #: card was opened (`Project.people`, forge login → channel id, read backwards). `requester`
    #: is a chat identity (a Slack user id, a panel principal, `cli`) and no tracker can mention or
    #: match it; ADR-0048 §5: where nobody the tracker knows resolves, the factory does not ask.
    requester_forge: str | None = None

    raw: str = ""  # the original board body, kept for the executor's full context


#: The value the factory writes when nobody was recorded — never a person.
NOBODY = ("não registrado", "nao registrado", "not recorded", "unknown", "")


def requester_of(ticket) -> str | None:
    """The person a question about this card goes to: the requester when the card names one,
    else the creator — a hand-written card's creator IS its requester; a factory-opened card's
    creator is the bot, which is why the requester is read first."""
    named = (getattr(ticket, "requester", None) or "").strip()
    if named and named.lower() not in NOBODY:
        return named
    author = (getattr(ticket, "author", None) or "").strip()
    return author or None


def tracker_requester_of(ticket) -> str:
    """The requester as the TRACKER knows them — the only identity a comment author can be matched
    against, and the only one a mention can reach (ADR-0048 §5). "" when there is none.

    Three cases, in order. A card carrying `requester_forge:` names the person in the tracker's own
    namespace. A card carrying only a chat requester was opened BY THE FACTORY for somebody the
    tracker cannot name — its `author` is the platform's own identity, and returning that would
    address the question to the bot that asked it. A card carrying neither was written by hand,
    and its author is its requester."""
    forge = (getattr(ticket, "requester_forge", None) or "").strip()
    if forge and forge.lower() not in NOBODY:
        return forge
    chat = (getattr(ticket, "requester", None) or "").strip()
    if chat and chat.lower() not in NOBODY:
        return ""
    return (getattr(ticket, "author", None) or "").strip()
