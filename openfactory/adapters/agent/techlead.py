"""The tech-lead and the sizer, for ANY harness.

These four roles — pre-flight sizing, a parked decision's briefing, an impediment diagnosis, and a
Slack answer — were hand-written inside the Claude adapter. They differ from one another only in
their prompt, and from harness to harness in nothing at all: each is "run this read-only prompt
against a checkout and give me the text".

So they live here once, over `agent.ask()` (see roles.py). A new harness gets the sizer and the
whole of ADR-0015 by implementing that one primitive — which is what makes a Claude-free
deployment possible instead of a deployment that quietly loses its tech-lead.

The prompt bodies still come from `org_defaults/roles/*.md`, unchanged: the platform's opinion
about HOW a tech lead should behave is not an adapter's business.
"""

from __future__ import annotations

from openfactory.adapters.agent.base import AgentContext
from openfactory.adapters.agent.roles import role_prompt
from openfactory.adapters.sandbox.base import SandboxAdapter, Workspace
from openfactory.contracts import AgentRunResult

_SIZER_FALLBACK = (
    "Judge whether this ticket is one small, testable change; output a fenced json verdict "
    "(fit|split|unclear)."
)
_COORDINATOR_FALLBACK = (
    "You are a tech lead. Briefly advise (json: summary/recommend/rationale) on this parked "
    "decision:"
)
_TECHLEAD_FALLBACK = (
    "You are the project's tech lead. A job PARKED on an impediment and needs a human. "
    "Investigate against the repo, verify every claim (including any prior human comment — say so "
    "if it's wrong), and output your diagnosis as a fenced json block with keys: headline, "
    "what_happened, why, correction (optional), recommendation, alternatives (optional)."
)
_CHAT_PROMPT = (
    "You are the project's tech lead, answering a teammate's question in a chat. Be concise, "
    "concrete, plain-language — no preamble, no fenced JSON, no markdown headers (this renders as "
    "a chat message). The repository is checked out at the workspace root: use your read tools to "
    "VERIFY before you answer. If you don't know or can't tell from what's available, say so "
    "plainly rather than guessing."
)


class HarnessTechLead:
    """The judging roles, delegated to whichever harness a project configured.

    Wraps a coding adapter rather than subclassing it: the tech-lead axis is deliberately
    SEPARATE from the executor axis (a project can write with one harness and judge with another),
    so this composes an adapter it does not own."""

    def __init__(self, agent) -> None:
        self.agent = agent
        self.name = getattr(agent, "name", type(agent).__name__)

    def _ask(self, sandbox, workspace, prompt: str, phase: str) -> AgentRunResult:
        return self.agent.ask(sandbox=sandbox, workspace=workspace, prompt=prompt, phase=phase)

    def size(
        self, *, sandbox: SandboxAdapter, workspace: Workspace, context: AgentContext
    ) -> AgentRunResult:
        """The SIZER (ADR-0013 D2): INVEST judgment on the ticket text plus a blast-radius
        estimate over the checkout. Its verdict gates the whole pipeline, which is why the
        tech-lead axis exists separately from the executor's."""
        role = role_prompt("sizer") or _SIZER_FALLBACK
        return self._ask(sandbox, workspace, f"{role}\n\n{_ticket_text(context)}", "size")

    def advise(
        self, *, sandbox: SandboxAdapter, workspace: Workspace, situation: str
    ) -> AgentRunResult:
        """The COORDINATOR on a parked decision: a humanized briefing + a recommended option."""
        role = role_prompt("coordinator") or _COORDINATOR_FALLBACK
        return self._ask(sandbox, workspace, f"{role}\n\n## Situation\n{situation}", "advise")

    def diagnose(
        self, *, sandbox: SandboxAdapter, workspace: Workspace, situation: str
    ) -> AgentRunResult:
        """The TECH LEAD on an impediment (ADR-0015): investigate against the REAL checkout,
        verify every claim — including a prior human comment — and hand off a diagnosis."""
        role = role_prompt("techlead") or _TECHLEAD_FALLBACK
        return self._ask(sandbox, workspace, f"{role}\n\n## Situation\n{situation}", "diagnose")

    def chat(
        self, *, sandbox: SandboxAdapter, workspace: Workspace, question: str, context: str = ""
    ) -> AgentRunResult:
        """A teammate's free-text question in Slack (ADR-0015 v2) — prose back, no forced JSON."""
        prompt = (
            f"{_CHAT_PROMPT}\n\n## Question\n{question}"
            + (f"\n\n## Current factory state\n{context}" if context else "")
        )
        return self._ask(sandbox, workspace, prompt, "chat")


def _ticket_text(context: AgentContext) -> str:
    """The ticket as the sizer needs to see it — spec only. The sizer judges the REQUEST, so it
    deliberately does not receive plans, knowledge maps or guidelines."""
    t = context.ticket
    parts = [f"# Ticket {t.id}: {t.title}", "", "## Objective", t.objective]
    if t.acceptance_criteria:
        parts += ["", "## Acceptance criteria"] + [f"- {c.text}" for c in t.acceptance_criteria]
    if t.in_scope:
        parts += ["", "## In scope"] + [f"- {x}" for x in t.in_scope]
    if t.out_of_scope:
        parts += ["", "## Out of scope"] + [f"- {x}" for x in t.out_of_scope]
    if t.context:
        parts += ["", "## Context", t.context]
    return "\n".join(parts)
