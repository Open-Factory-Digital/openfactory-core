"""Another pass on a change that waits on the person who asked for it (#448, slice 1).

THE REQUESTER'S "NOT YET" HAD NO DOOR. Measured live on card #1000007, 2026-09-30: the requester
tried the preview and said in the conversation what was still wrong; the product role named the
loose criterion it had written, found the cause and rewrote the two criteria — then said *"I can't
edit the card or its acceptance criteria myself; that has to go back through #1000007 as a
request for changes."* The requester could not do that either. The merge gate's `adjust` was a
floor row an operator alone could press (`actions/base.py`, FLOOR and admin), `correct_card`
refused every card the factory had taken up, and the third pass was refused by a constant.

WHAT THIS MODULE IS: the product side's two words with the job at its merge gate — what the gate
says (`gate_of`) and the answer `adjust` (`send_back`), and the `merge` a requester's acceptance
gives when the look is all that holds it (`answer_gate`, #448 slice 3) — through the one seam
every surface's answer crosses (`view.answer_merge_gate`), on the process's standing loop with the
client the release path keeps (`release._client`, #201: one client per process, not one per
answer). And
the pure half of drafting the pass from the conversation (`draft_prompt`, `floor`), for the
module to run.

NOTHING HERE DECIDES WHO MAY, OR WHAT THE PERSON IS TOLD. Who may send a card back is the module's
(`ProductModule.send_back`, #384's rule for the card's own controls), and every sentence is the
voice's (`voice.adjust_said`), in the project's language. A reason here is a WORD a sentence is
chosen by, never a sentence.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from openfactory.product.authoring import WriteResult

log = logging.getLogger("openfactory.product.adjust")

# ── what the gate says ───────────────────────────────────────────────────────────────────────────

#: No job waits on a person for this card: it merged, was closed, never opened a pull request, the
#: factory is landing it on its own, or no job ever ran.
NOT_WAITING = "not_waiting"
#: A pass is rewriting the pull request right now — the answer would land on a diff nobody read.
WORKING = "working"
#: The job waits on a person and cannot hear an answer from here (a run older than the gate).
DEAF = "deaf"
#: Every pass the project allows for one change was spent: a person decides now (#448).
SPENT = "spent"
#: The engine could not be asked — nothing was sent, and nothing changed.
UNREACHABLE = "unreachable"
#: Every reason `Gate.why` and `send_back` may answer. A closed set, so the voice holds a sentence
#: for each and a test walks them (`tests/test_the_requester_asks_for_another_pass.py`).
WHY = frozenset({NOT_WAITING, WORKING, DEAF, SPENT, UNREACHABLE})


@dataclass(frozen=True)
class Gate:
    """What the job on one card says about its merge gate, as the engine answered it."""

    #: the card the engine was asked about — so a correction admitted "at the gate" is admitted
    #: for THIS card's gate, never another's (`ProductModule.correct_card`)
    card: str = ""
    #: why no pass can be asked for now, one of `WHY` — "" when one can
    why: str = ""
    pr_url: str = ""
    #: the project's budget as the job was started with, and what is left of it — None for a job
    #: whose binary predates the numbers (#448); it is sent the answer, and its own branch decides
    passes: int | None = None
    left: int | None = None
    #: THE LOOK IS THE ONLY THING HOLDING THIS MERGE (#448 slice 3): the job's own word
    #: (`auto_but_for_the_look` on its merge wait), so the requester's acceptance of the head they
    #: tried may answer this gate with `merge` (`product/accept.py`). False for a job that does
    #: not say, which a person merges.
    look_only: bool = False

    @property
    def open(self) -> bool:
        """A person is being asked and another pass may be sent."""
        return not self.why


def read(gate: dict | None, *, card: str, deaf: str = "") -> Gate:
    """The merge-wait a job publishes, read as a `Gate` — PURE, so every reason is testable
    without an engine. `deaf` is `view.gate_cannot_hear`'s sentence, asked by the caller that
    holds the engine's module.

    AUTO IS NOT WAITING ON A PERSON: on that path the factory is landing the change on its own
    (`awaiting_merge`'s own docstring), and a "not yet" there has no gate to stand at."""
    if not gate or gate.get("auto"):
        return Gate(card=card, why=NOT_WAITING)
    if gate.get("working"):
        return Gate(card=card, why=WORKING, pr_url=str(gate.get("pr_url") or ""))
    passes, left = _count(gate.get("adjust_passes")), _count(gate.get("adjusts_left"))
    said = dict(card=card, pr_url=str(gate.get("pr_url") or ""), passes=passes, left=left,
                look_only=gate.get("auto_but_for_the_look") is True)
    if deaf:
        return Gate(why=DEAF, **said)
    if left == 0:
        return Gate(why=SPENT, **said)
    return Gate(**said)


def _count(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _missing(exc: BaseException) -> bool:
    """Whether the engine said "no such workflow" — no job ever ran for the card. Read from the
    text for `catalog._looks_missing`'s reason: the SDK raises one `RPCError` for both."""
    blob = f"{type(exc).__name__} {exc}".lower()
    return "not found" in blob or "notfound" in blob


def gate_of(project, card: str) -> Gate:
    """What the job on `card` says about its merge gate — NEVER RAISES: an engine that could not be
    asked is `UNREACHABLE`, and a card no job ever ran for is `NOT_WAITING`."""
    from openfactory.contracts.refs import canonical_ref

    name, card = str(getattr(project, "name", "") or ""), canonical_ref(card)

    async def _run() -> Gate:
        from openfactory.product.release import _client
        from openfactory.runtime.temporal import view as tv

        client = await _client()
        gate = await tv.merge_gate(client, name, card)
        deaf = tv.gate_cannot_hear(gate) if gate and not gate.get("working") else ""
        return read(gate, card=card, deaf=deaf)

    try:
        from openfactory.runtime.temporal.standing import from_a_thread

        return from_a_thread(_run)
    except Exception as exc:  # noqa: BLE001 — a person's turn must never see a traceback
        if _missing(exc):
            return Gate(card=card, why=NOT_WAITING)
        log.error("OPENFACTORY_ADJUST_GATE_UNREADABLE project=%s card=#%s (%s) — the merge gate "
                  "could not be read, so no pass was offered or sent", name, card, str(exc)[:200])
        return Gate(card=card, why=UNREACHABLE)


def send_back(project, card: str, *, instruction: str, by: str) -> str:
    """Deliver `adjust` with `instruction` to the job on `card` — `""` when it was delivered, else
    the reason it was not (one of `WHY`). NEVER RAISES.

    THROUGH THE SEAM EVERY SURFACE'S ANSWER CROSSES (`view.answer_merge_gate`): it queries the gate
    before signalling, so a stale answer is refused rather than swallowed, it refuses a pass the
    job would refuse (`AdjustsSpent`), and it seals the answer as the panel's (`gate_seal`) — the
    worker refuses an unsealed one."""
    return answer_gate(project, card, answer="adjust", instruction=instruction, by=by)


def answer_gate(project, card: str, *, answer: str, instruction: str = "", by: str) -> str:
    """Deliver one of the merge gate's answers to the job on `card` — `""` when it was delivered,
    else the reason it was not (one of `WHY`). NEVER RAISES. `send_back`'s seam, for every answer
    the product side gives: `adjust` (#448 slice 1) and the `merge` a requester's acceptance gives
    when the look is all that holds it (slice 3, `product/accept.py`)."""
    from openfactory.contracts.refs import canonical_ref

    name, card = str(getattr(project, "name", "") or ""), canonical_ref(card)
    said = answer

    async def _run() -> str:
        from openfactory.product.release import _client
        from openfactory.runtime.temporal import view as tv

        client = await _client()
        try:
            await tv.answer_merge_gate(client, name, card, answer=said,
                                       instruction=instruction, by=by)
        except tv.AdjustsSpent:
            return SPENT
        except tv.GateDeaf:
            return DEAF
        except RuntimeError:        # the engine answered: the job is not at its merge gate
            return NOT_WAITING
        return ""

    try:
        from openfactory.runtime.temporal.standing import from_a_thread

        return from_a_thread(_run)
    except Exception as exc:  # noqa: BLE001 — a person's yes must never see a traceback
        if _missing(exc):
            return NOT_WAITING
        log.error("OPENFACTORY_ADJUST_NOT_DELIVERED project=%s card=#%s answer=%s by=%s (%s) — a "
                  "person answered the merge gate and the job was not told", name, card, said, by,
                  str(exc)[:200])
        return UNREACHABLE


# ── the pass, drafted from the conversation (ADR-0054 D1: never from the message alone) ─────────

#: The phase the draft is metered under, and the one `adapters/agent/roles.py` localises: the
#: criteria are written onto the card the person opens, and the instruction is shown to them.
DRAFT_PHASE = "product_adjust_draft"

#: The longest instruction a pass takes. THE WORKFLOW CUTS AT THIS NUMBER (`workflow._ADJUST_CHARS`)
#: and the floor's row refuses past it (`catalog._ADJUST_MAX_CHARS`), so a longer one would reach
#: the pass shorter than the person confirmed it. Held equal to both by a test.
INSTRUCTION_LIMIT = 2000

#: One draft and one redraft, then the person is asked again (ADR-0054 D4's bound): a third try at
#: the same conversation is a loop, and what is missing is information only the person has.
ATTEMPTS = 2


@dataclass(frozen=True)
class Adjustment:
    """What the next pass must change, and the card's criteria as they must read after it."""

    instruction: str
    criteria: tuple[str, ...] = field(default_factory=tuple)


@dataclass
class Sent(WriteResult):
    """A pass that was sent: which one of how many, and whether the card's bar moved with it.

    THE FACTS, NOT THE SENTENCE, on a `WriteResult` whose `detail` on success keeps the one meaning
    the confirmation path gives it — what did NOT happen (`confirm._unfinished`): a correction whose
    note could not be left. The headline is composed from these by whoever answers the person
    (`headline`), so the conversation and the card say the same thing."""

    pass_number: int | None = None
    passes: int | None = None
    corrected: bool = False


def headline(sent: Sent, *, instruction: str, language: str | None = None) -> str:
    """What the person reads once the pass is on its way, in their language
    (`voice.adjust_sent`)."""
    from openfactory.product.voice import adjust_sent

    # READ WITH DEFAULTS: a module that is not this tree's (an add-on's, a double) answers a plain
    # `WriteResult`, and the person is then told the pass went, without its count
    return adjust_sent(ref=getattr(sent, "ref", ""), instruction=instruction,
                       number=getattr(sent, "pass_number", None),
                       passes=getattr(sent, "passes", None),
                       corrected=bool(getattr(sent, "corrected", False)), language=language)


@dataclass(frozen=True)
class Prepared:
    """What the conversation stages for the yes — or, when `ok` is False, what it says instead."""

    ok: bool = False
    said: str = ""
    instruction: str = ""
    criteria: tuple[str, ...] = ()
    #: why the card's criteria stay as written — `requirement` (the requirement changes first) or
    #: `board` (a person wrote the card on the board, and it is theirs) — "" when they are corrected
    keeps: str = ""
    gate: Gate | None = None


def one_line(text: str) -> str:
    return " ".join(str(text or "").split())


def floor(raw: dict | None) -> tuple[Adjustment | None, list[str]]:
    """The draft, checked by code before anybody is asked to confirm it — `(adjustment, [])`, or
    `(None, problems)` naming what to change in a redraft. No model can switch it off (ADR-0054
    D2's rule for the card, applied to the pass)."""
    if not isinstance(raw, dict):
        return None, ["answer with one JSON object, nothing else"]
    problems: list[str] = []
    instruction = str(raw.get("instruction") or "").strip()
    if not instruction:
        problems.append("`instruction` is empty — say what the pass must change")
    elif len(instruction) > INSTRUCTION_LIMIT:
        problems.append(f"`instruction` is {len(instruction)} characters; it must be at most "
                        f"{INSTRUCTION_LIMIT}")
    given = raw.get("criteria")
    criteria = tuple(dict.fromkeys(one_line(c) for c in given if one_line(c))) \
        if isinstance(given, list) else ()
    if not criteria:
        problems.append("`criteria` is empty — the card's whole list of acceptance criteria as it "
                        "must read now")
    if problems:
        return None, problems
    return Adjustment(instruction=instruction, criteria=criteria), []


def draft_prompt(*, number: str, card: str, conversation: str, request: str, reply: str,
                 language: str | None, problems: list[str] | None = None) -> str:
    """What the role is asked when it drafts the pass — in `language` when one is named (#429)."""
    from openfactory.product.voice import language_rules

    written_in = (f"Write both in {language}, the conversation's language — whatever language "
                  f"the card is in." if language else "Write it in the person's language.")
    rules = language_rules(language) if language else ""
    again = ""
    if problems:
        again = ("\n\n## Your previous answer could not be used\n\nChange exactly this:\n"
                 + "\n".join(f"- {p}" for p in problems))
    return (
        f"The person who asked for card #{number} tried the change that is waiting on them and "
        "said what is still wrong. From the conversation below, write what the next pass on the "
        "SAME pull request must change, and the card's acceptance criteria as they must read "
        "now — the bar that pass is reviewed against. The pass reads only the card and your "
        f"instruction; it never sees this conversation. {written_in}\n\n"
        + (f"{rules}\n\n" if rules else "")
        + "Rules:\n"
        "- `instruction`: what the pass must change, in one to three concrete sentences the "
        "person can read too — name the screen or behaviour and the change wanted, not the "
        f"symptom. At most {INSTRUCTION_LIMIT} characters, and only what the conversation "
        "established.\n"
        "- `criteria`: the card's WHOLE list of acceptance criteria as it must read after this — "
        "each current one that still holds, as written; the ones the conversation showed were "
        "loose or wrong, rewritten; what the person established, added. Each one an observable "
        "statement a reviewer can check without opening the code; never HOW to build it.\n"
        "- Nothing private or unrelated to the work goes into either.\n\n"
        f"## The card as it reads now\n\n{card.strip() or '(the card could not be read)'}\n\n"
        f"## The conversation (oldest first)\n\n{conversation.strip() or '(no earlier messages)'}"
        f"\n\n## The message that asked for another pass\n\n{request.strip()}"
        + (f"\n\n## Your reply to it\n\n{reply.strip()}" if reply.strip() else "")
        + again
        + "\n\n## Answer\n\nAnswer at once with ONLY a JSON object (no prose, no code fences, "
        "nothing to look up — everything the pass is drafted from is above):\n"
        '{"instruction": str, "criteria": [str]}'
    )


def draft(ask: Callable[[str], dict | None], *, number: str, card: str, conversation: str,
          request: str, reply: str = "", language: str | None = None) -> Adjustment | None:
    """At most `ATTEMPTS` drafts, the floor's problems handed to the second — the adjustment, or
    None when neither was usable (the person is then asked to say it again)."""
    problems: list[str] = []
    for attempt in range(1, ATTEMPTS + 1):
        try:
            raw = ask(draft_prompt(number=number, card=card, conversation=conversation,
                                   request=request, reply=reply, language=language,
                                   problems=problems))
        except Exception as exc:  # noqa: BLE001 — a draft that broke is a draft not usable
            log.warning("OPENFACTORY_ADJUST_DRAFT_FAILED card=#%s attempt=%d (%s)", number,
                        attempt, str(exc)[:200])
            raw = None
        adjustment, problems = floor(raw)
        log.info("OPENFACTORY_ADJUST_DRAFTED card=#%s attempt=%d usable=%s problems=%s", number,
                 attempt, adjustment is not None, problems)
        if adjustment is not None:
            return adjustment
    return None
