"""Needs Action: where the product role meets the tech-lead — without either one talking to
the other.

The column already exists and already holds exactly what needs a decision. The tech-lead has already
written its diagnosis onto the ticket. So the product role reads that, decides whether the cause is
something IT owns, and either fixes it or hands it back — through the board, the way two people
would. No new field, no classifier service, no channel between agents (ADR-0019 §6).

WHAT IT OWNS: a requirement defect. An acceptance criterion nobody can evaluate, a scope that
contradicts itself, a decision the ticket assumes but nobody ever made. Those are the reason a job
parks that a person with the product in their head can fix in five minutes — and today a human does
exactly that, by hand.

WHAT IT DOES NOT OWN: anything technical or environmental. A failing migration, a rate limit, a
flaky test. It says so and leaves, rather than offering an opinion that costs someone the time to
read and discard.

MISCLASSIFICATION IS CHEAP BUT THE WAY BACK MUST EXIST. Reading a technical impediment as a
requirement defect costs one comment and a redirect. Reading it silently — acting on it and moving
the card — costs a person discovering later that a parked job was quietly reinterpreted. So every
decision, including "this is not mine", is written on the ticket with its reason.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


#: The causes a diagnosis can have. `requirement` is the only one this role acts on.
def _sig(agent_name: str = "") -> str:
    from openfactory.product.voice import signature

    return signature(agent_name)


REQUIREMENT, TECHNICAL, ENVIRONMENT, UNCLEAR = (
    "requirement", "technical", "environment", "unclear")
_CAUSES = (REQUIREMENT, TECHNICAL, ENVIRONMENT, UNCLEAR)

_CAUSE_SCHEMA = """\
Return ONLY a JSON object (no prose, no code fences):
{"cause": "requirement"|"technical"|"environment"|"unclear",
 "confidence": "high"|"low",
 "reason": str,
 "fix": str}
`requirement` means the ticket itself is the problem: a criterion nobody can evaluate, a scope that
contradicts itself, a decision it assumes that nobody ever made. `technical` and `environment` mean
the ticket is fine and something else failed. `unclear` is a real answer — use it rather than
guessing, because acting on the wrong reading costs somebody their afternoon.
`fix` is what you would change about the TICKET, and only meaningful when the cause is
`requirement`."""


class Verdict(BaseModel):
    """What the product role concluded about one parked ticket."""

    ticket: str
    cause: str = UNCLEAR
    confidence: str = "low"
    reason: str = ""
    fix: str = ""

    def normalised(self) -> Verdict:
        """An unrecognised cause becomes `unclear`, never `requirement`. Degrading toward the
        answer that ACTS would let a parsing accident rewrite somebody's ticket."""
        if self.cause not in _CAUSES:
            return self.model_copy(update={"cause": UNCLEAR, "confidence": "low"})
        return self

    @property
    def mine(self) -> bool:
        """Whether this role should act. Requires HIGH confidence as well as the right cause: a
        low-confidence guess about whose problem this is has already told us it is unclear."""
        v = self.normalised()
        return v.cause == REQUIREMENT and v.confidence == "high"



    @field_validator("ticket", mode="before")
    @classmethod
    def _ref_is_a_string(cls, v):
        """A ticket ref is the provider's own string (C-05); an int still constructs, because
        every producer reads a tracker that may hand back either and hundreds of call sites pass
        a bare number."""
        from openfactory.contracts.refs import canonical_ref

        return None if v is None else canonical_ref(v)

class Decision(BaseModel):
    """A verdict plus what was actually done about it — reported per ticket, so a partial pass is
    legible instead of collapsing into "processed 12 items"."""

    verdict: Verdict
    acted: bool = False
    comment: str = ""
    detail: str = ""


class Review(BaseModel):
    decisions: list[Decision] = Field(default_factory=list)

    def mine(self) -> list[Decision]:
        return [d for d in self.decisions if d.verdict.mine]

    def handed_back(self) -> list[Decision]:
        return [d for d in self.decisions if not d.verdict.mine]


def classify_prompt(*, ticket_number: str, title: str, body: str, diagnosis: str) -> str:
    """What the role is asked about one parked ticket.

    It is given the tech-lead's diagnosis as TEXT rather than asking the tech-lead anything: the
    diagnosis is already on the ticket, and two agents conversing with no human in the loop is
    where two mistakes compound with nobody owning the result."""
    return (
        "A job parked on this ticket and it is waiting for a person. Decide whether the cause is "
        "something the PRODUCT owns — the ticket itself being wrong — or something technical or "
        "environmental, which is not yours.\n\n"
        "Do not offer a technical opinion. If the ticket is fine and something else failed, say so "
        "and stop; an opinion somebody has to read and discard costs more than silence.\n\n"
        f"## Ticket #{ticket_number} — {title}\n\n{body}\n\n"
        # "The latest note", NOT "the tech lead's diagnosis": the text arrives from
        # `board._last_diagnosis`, which falls back to the ticket's last comment by ANYONE when no
        # marked diagnosis exists — and a heading that asserts provenance the reader cannot check
        # makes the model (and then the platform, publicly) attribute a bystander's aside to the
        # tech-lead (#24 item 4). When it IS the diagnosis, the text says so itself.
        f"## The latest note on the ticket (the tech lead's diagnosis, when one was recorded)"
        f"\n\n{diagnosis or '(none was recorded)'}\n\n"
        + _CAUSE_SCHEMA
    )


def hand_back_comment(verdict: Verdict, *, agent_name: str = "",
                      language: str | None = None) -> str:
    """Said on the ticket when the cause is not the product's.

    Written down rather than passed over in silence: a parked ticket that the product role looked
    at and left must LOOK like that, or the next person wastes the same five minutes reaching the
    same conclusion.

    IN THE PROJECT'S LANGUAGE (#160). Nobody asked the role to look, so this is the unprompted
    kind by the rule `product/voice.py` states — and it lands on the ticket, which every project
    has whether or not it has a channel."""
    from openfactory.product import voice

    v = verdict.normalised()
    sig = _sig(agent_name)
    why = f" — {v.reason}" if v.reason else ""
    if v.cause == REQUIREMENT:
        # It reached here with the right cause, so what stopped it was CONFIDENCE. Saying that
        # plainly is the whole value of the message: a person now knows where to look, and knows
        # the role declined to act rather than failed to notice.
        fix = (voice._pick(voice._HANDBACK_FIX_CLAUSE, language).format(fix=v.fix)
               if v.fix else "")
        return voice._pick(voice._HANDBACK_REQUIREMENT, language).format(
            sig=sig, why=why, fix=fix)
    if v.cause == UNCLEAR:
        return voice._pick(voice._HANDBACK_UNCLEAR, language).format(sig=sig, why=why)
    what = voice._pick(voice._HANDBACK_CAUSE[v.cause], language)
    return voice._pick(voice._HANDBACK_NOT_MINE, language).format(sig=sig, what=what, why=why)


def fix_comment(verdict: Verdict, *, agent_name: str = "", language: str | None = None) -> str:
    """Said when the role DOES act. Names what it changed and why, because a sign-off that cannot
    see what moved is a rubber stamp."""
    from openfactory.product import voice

    v = verdict.normalised()
    why = f" — {v.reason}" if v.reason else ""
    fix = voice._pick(voice._FIX_CLAUSE, language).format(fix=v.fix) if v.fix else ""
    return voice._pick(voice._FIX_COMMENT, language).format(
        sig=_sig(agent_name), why=why, fix=fix)


def review(verdicts: list[Verdict], *, may_act: bool, agent_name: str = "",
           language: str | None = None) -> Review:
    """Turn verdicts into decisions. Pure, so the rule that decides whether an agent rewrites
    somebody's ticket is testable without a network.

    `may_act=False` still produces the comments: saying "this is a requirement problem and here is
    what I would change" is useful even when nobody has authorised the role to change it."""
    out: list[Decision] = []
    for raw in verdicts:
        v = raw.normalised()
        if not v.mine:
            out.append(Decision(verdict=v, acted=False,
                                comment=hand_back_comment(v, agent_name=agent_name,
                                                          language=language)))
            continue
        if not may_act:
            out.append(Decision(
                verdict=v, acted=False,
                comment=fix_comment(v, agent_name=agent_name, language=language),
                detail="nobody has authorised this role to change tickets yet"))
            continue
        out.append(Decision(verdict=v, acted=True,
                            comment=fix_comment(v, agent_name=agent_name, language=language)))
    return Review(decisions=out)
