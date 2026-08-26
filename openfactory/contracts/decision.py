"""DecisionRequest — the ONE contract for every human-in-the-loop decision.

Owner principle: parking a job for a human without OPTIONS is useless. Whenever the flow needs
a person — a planner blocker, an unclear ticket, a crash, a rate-limit, a prod approval — it
must surface a concrete question with 2-4 options, each with its consequence, plus the
machine's recommendation. The human (or a bot) picks a key; the decision is recorded on the
ticket and injected back into the agent on resume, so it never re-asks and the call is
auditable forever.

API-FIRST: this model is transport-agnostic. The panel renders it as buttons, but a Slack
interactive message, a Telegram inline keyboard, and `curl` all speak the same shape — one
GET to read pending decisions, one POST to answer with a choice key. No surface is special.
"""

from __future__ import annotations

import json
import re

from pydantic import BaseModel, Field

from openfactory.contracts.commands import normalize_command


class DecisionOption(BaseModel):
    key: str  # short selector the human/bot returns: "A", "B", "C" (or "retry"/"skip")
    label: str  # one-line human-readable choice
    consequence: str = ""  # what happens if this is picked — the whole point of options
    recommended: bool = False  # the machine's suggestion (exactly one should be true)


class DecisionRequest(BaseModel):
    """A parked job's question + the ways forward. `stage` says who asked (plan/size/impediment/
    approval); `default` is the recommended option's key (used only to PRE-SELECT in a client,
    never to auto-decide — decisions are always human)."""

    stage: str
    question: str
    context: str = ""  # background the human needs to choose well (the full, untruncated text)
    options: list[DecisionOption] = Field(default_factory=list)
    default: str = ""  # key of the recommended option
    advice: CoordinatorAdvice | None = None  # the tech-lead's humanized take (attached async)

    def option(self, key: str) -> DecisionOption | None:
        k = (key or "").strip().lower()
        return next((o for o in self.options if o.key.strip().lower() == k), None)

    def recommended_key(self) -> str:
        if self.default:
            return self.default
        rec = next((o for o in self.options if o.recommended), None)
        return rec.key if rec else (self.options[0].key if self.options else "")


def parse_decision(text: str) -> DecisionRequest | None:
    """Pull a DecisionRequest out of an agent's output — the LAST fenced ```json block whose
    object has a `question` and `options` (agents think out loud; only the final block is the
    verdict). Tolerates prose around it and minor sloppiness; returns None (caller degrades to a
    generic park) rather than raising, so a malformed decision can never crash the flow."""
    if not text:
        return None
    blocks = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if not blocks:  # maybe a bare object
        m = re.search(r"\{[\s\S]*\"options\"[\s\S]*\}", text)
        blocks = [m.group(0)] if m else []
    for raw in reversed(blocks):  # last valid one wins
        try:
            d = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if not isinstance(d, dict) or "options" not in d or not d.get("question"):
            continue
        opts = [
            DecisionOption(
                key=str(o.get("key") or chr(65 + i)),
                label=str(o.get("label", ""))[:200],
                consequence=str(o.get("consequence", ""))[:400],
                recommended=bool(o.get("recommended")),
            )
            for i, o in enumerate(d.get("options") or [])
            if isinstance(o, dict)
        ][:4]
        if len(opts) < 2:  # a real decision needs a genuine choice
            continue
        req = DecisionRequest(
            stage=str(d.get("stage", ""))[:40],
            question=str(d["question"])[:600],
            context=str(d.get("context", ""))[:4000],
            options=opts,
            default=str(d.get("default", "")),
        )
        # normalise `default`/`recommended` so exactly one option is the recommendation
        if not req.option(req.default):
            req.default = req.recommended_key()
        for o in req.options:
            o.recommended = o.key.strip().lower() == req.default.strip().lower()
        return req
    return None


class CoordinatorAdvice(BaseModel):
    """The tech-lead coordinator's humanized briefing on a parked decision (v0: advisory only —
    it explains + recommends, a human still decides). Attached to the decision so every channel
    shows the senior engineer's take alongside the raw options."""

    summary: str = ""  # what happened + why it needs a human, in plain language
    recommend: str = ""  # the option key the tech-lead would pick
    rationale: str = ""  # WHY — the engineering trade-off
    watch_outs: str = ""  # optional risk to double-check


def parse_advice(text: str) -> CoordinatorAdvice | None:
    """Pull the coordinator's advice out of its output — the LAST fenced ```json block with a
    `summary` or `recommend`. Degrades to None (caller just skips the advice), never raises."""
    if not text:
        return None
    blocks = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if not blocks:
        m = re.search(r"\{[\s\S]*\"(?:summary|recommend)\"[\s\S]*\}", text)
        blocks = [m.group(0)] if m else []
    for raw in reversed(blocks):
        try:
            d = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if not isinstance(d, dict) or not (d.get("summary") or d.get("recommend")):
            continue
        return CoordinatorAdvice(
            summary=str(d.get("summary", ""))[:600],
            recommend=str(d.get("recommend", ""))[:40],
            rationale=str(d.get("rationale", ""))[:600],
            watch_outs=str(d.get("watch_outs", ""))[:400],
        )
    return None


def canned(stage: str, question: str, options: list[tuple[str, str, str]], default: str,
           context: str = "") -> DecisionRequest:
    """Build a DecisionRequest from fixed options — for process decisions that have no LLM
    verdict (a crash, a turn cap): [(key, label, consequence), …]. So even the generic
    impediments obey 'no park without options'."""
    return DecisionRequest(
        stage=stage, question=question, context=context, default=default,
        options=[DecisionOption(key=k, label=lb, consequence=c, recommended=(k == default))
                 for k, lb, c in options],
    )


class HandOff(BaseModel):
    """The tech-lead's diagnosis of an IMPEDIMENT — what a senior engineer would post when a job
    parks needing a human. Richer than CoordinatorAdvice (which recommends one option KEY for a
    decision): an impediment's real fix is often free-form ("descope into a separate ticket"), and
    the tech-lead may CORRECT a prior human comment it verified as wrong. Rendered to GitHub
    markdown on the ticket and to Slack mrkdwn in the channel — same brain, two surfaces."""

    headline: str = ""  # one line: the ticket + what it needs (Slack title / comment header)
    what_happened: str = ""  # plain language: what actually failed
    why: str = ""  # root cause + the engineering reasoning
    correction: str = ""  # optional: a prior comment/assumption this refutes, with evidence
    recommendation: str = ""  # what to do (free-form — not limited to resume/skip)
    alternatives: str = ""  # optional: other ways forward
    # A concrete, ONE-COMMAND next step the operator can hand back so the tech-lead RESOLVES the
    # park instead of leaving a wall of text to rot: "skip #NN" or "resume #NN" when that action
    # unblocks it (the panel chat and every channel add-on execute those, gated + watched).
    # "" when the fix is genuinely manual — then `recommendation` carries it.
    suggested_command: str = ""


def parse_handoff(text: str, *, issue: str = "") -> HandOff | None:
    """Pull the tech-lead's HandOff out of its output — the LAST fenced ```json block carrying a
    `headline` or `what_happened`. Degrades to None (caller falls back to the raw note), never
    raises.

    `suggested_command` is VALIDATED here, against the one grammar the chat listeners actually
    executes (`openfactory.contracts.commands`), and dropped when it doesn't parse or — when
    `issue` is
    passed — when it targets a different ticket. The command is free-form LLM output that we
    then render as a promise ("reply this and I resolve it"), so an unexecutable one would send
    the operator to a dead end and an issue-number hallucination would have us instruct an admin
    to act on an unrelated job. Unvalidated, it is the same silent rot it was meant to end."""
    if not text:
        return None
    blocks = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if not blocks:
        m = re.search(r"\{[\s\S]*\"(?:headline|what_happened)\"[\s\S]*\}", text)
        blocks = [m.group(0)] if m else []
    for raw in reversed(blocks):
        try:
            d = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if not isinstance(d, dict) or not (d.get("headline") or d.get("what_happened")):
            continue
        return HandOff(
            headline=str(d.get("headline", ""))[:200],
            what_happened=str(d.get("what_happened", ""))[:800],
            why=str(d.get("why", ""))[:1200],
            correction=str(d.get("correction", ""))[:800],
            recommendation=str(d.get("recommendation", ""))[:800],
            alternatives=str(d.get("alternatives", ""))[:600],
            suggested_command=normalize_command(
                str(d.get("suggested_command", ""))[:60], issue=issue
            ),
        )
    return None


def handoff_to_markdown(ho: HandOff, *, raw_note: str = "") -> str:
    """Render a HandOff as MARKDOWN — the durable record on a ticket.

    Named for the format, not the vendor. Every tracker this platform speaks to renders markdown
    in a comment; the one that does not is the one that gets its own renderer."""
    base = "### Tech-lead triage"
    parts = [f"{base} — {ho.headline}" if ho.headline else base]
    if ho.what_happened:
        parts.append(f"**What happened.** {ho.what_happened}")
    if ho.why:
        parts.append(f"**Why.** {ho.why}")
    if ho.correction:
        parts.append(f"**Correction.** {ho.correction}")
    if ho.recommendation:
        parts.append(f"**Recommendation.** {ho.recommendation}")
    if ho.alternatives:
        parts.append(f"**Alternatives.** {ho.alternatives}")
    if ho.suggested_command:
        # NO CHANNEL IS NAMED (#159). This said "in Slack" — on a deployment that has no Slack,
        # about a command the panel chat could not execute either. The reader is reading this
        # SOMEWHERE; wherever that is, is where they reply. The panel is the reference surface
        # (ADR-0038) and its chat executes the same grammar the channel add-ons do.
        parts.append(f"**To resolve.** Reply `{ho.suggested_command}` — the tech-lead executes "
                     "it (gated + watched). The button on the panel does the same.")
    if raw_note:
        block = "\n\n```\n" + raw_note[:1500] + "\n```\n"
        parts.append("<details><summary>Raw error</summary>" + block + "</details>")
    return "\n\n".join(parts)


def handoff_to_plain(ho: HandOff, *, ref: str = "") -> str:
    """Render a HandOff as concise PLAIN text — one screen, no headers, single-asterisk bold.

    The lowest common denominator a chat surface renders. A provider whose flavour differs
    (Slack's mrkdwn, Telegram's HTML) converts from here inside its own adapter, which is where
    a vendor's formatting quirks belong."""
    head = ho.headline or "needs your input"
    parts = [f"*{head}*"]
    if ho.what_happened:
        parts.append(f"*What:* {ho.what_happened}")
    if ho.why:
        parts.append(f"*Why:* {ho.why[:500]}")
    if ho.correction:
        parts.append(f"*Correction:* {ho.correction[:400]}")
    if ho.recommendation:
        parts.append(f"*Recommend:* {ho.recommendation}")
    if ho.suggested_command:
        # ENGLISH SCAFFOLD, AGENT-LANGUAGE CONTENT. The field values were composed by an agent
        # under `language_directive`, so they arrive in the project's language; the scaffold
        # labels are the system's, like every other canned label (#124). This line was hardcoded
        # Portuguese — "Pra eu resolver, me diga:" — shipped to every deployment in any language,
        # found by the #159 guard while it was looking for the Slack weld one field up.
        parts.append(f"→ *To resolve, reply:* `{ho.suggested_command}` — I execute it "
                     "(gated + watched); the panel's button does the same.")
    if ref:
        parts.append(f"→ {ref}")
    return "\n".join(parts)


# RESOLVED AT IMPORT, NOT AT FIRST USE. `DecisionRequest.advice` is annotated `CoordinatorAdvice`,
# which is defined BELOW it, so with `from __future__ import annotations` pydantic leaves the model
# incomplete and rebuilds it lazily the first time somebody touches it. That works whenever the
# module has finished importing — which is almost always, and "almost" is the problem.
#
# Inside Temporal's workflow sandbox it does not. The sandbox re-imports modules under its own
# restrictions, and `_park` calls `result.decision.model_dump()` there, so the lazy rebuild fired
# at the one moment it could fail:
#
#   PydanticUserError: `DecisionRequest` is not fully defined; you should define
#   `CoordinatorAdvice`, then call `DecisionRequest.model_rebuild()`
#
# The workflow then errored, retried, and parked the job ON_HOLD — so the ESCALATION WITH OPTIONS,
# which exists precisely so a stall is never silent, failed into a silent-looking stall. It was
# invisible for as long as it was: any test or process that had already touched a DecisionRequest
# left the model rebuilt, so the failure only appeared when this path ran first. It read as
# flakiness in two workflow tests for weeks.
#
# One line, and the model is complete for every importer in every environment.
DecisionRequest.model_rebuild()
