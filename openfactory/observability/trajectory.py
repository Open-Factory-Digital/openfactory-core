"""What a pass DID — the measurement the platform computes and throws away.

`adapters/agent/stream.py` already turns a harness's stream into neutral `Pulse`es, one per tool
call, each carrying the tool's name, its target, a clock where the harness stamps one, and the cost
of the step it ended. It even carries a `key` designed to answer *"what makes two calls THE SAME
call"*, with the care not to count an unkeyed call as a repeat.

`techlead/watch.read_harness` consumes those pulses and asks a **pathology** question: is this run
stuck — silent, looping, reaching for tools it was never granted. That answer is used live, to park
a job with a reason, and then it is gone.

`observability/metrics.AgentRunMetric` keeps `cost_usd`, `num_turns`, `input_tokens`,
`output_tokens`. The per-call detail dies between the two.

**So the platform already parses the trajectory and keeps none of it**, and the two questions an
operator asks about a factory — is it fast, is it cheap — have no instrument at all, while their
raw material is computed on every single pass. This module is the missing half: not *did it get
stuck*, but *what did it do to get there*.

WHY THE TOOL NAMES CANNOT BE READ LITERALLY, and it is the whole reason this is not four lines.
`Pulse.name` is the VENDOR's string, unnormalised by design — `_claude` passes through whatever the
block says (`Edit`, `Read`, `Bash`), `_codex` emits `"Bash"` plus `kind.capitalize()` for a file
change, `_opencode` whatever OpenCode calls it (lower-case), `_kimi` whatever key it finds with
`"Bash"` as a fallback. A measure keyed on the literal `"Edit"` would work on one harness and return
a confident **zero** on the others — a wrong answer in the quiet direction, for exactly the
harnesses the product's agnosticism claim rests on.

So calls are classified by INTENT, and every name the table does not know is counted AND NAMED
(`unclassified_names`). A reader can then tell "this agent did no editing" from "this harness calls
it something we have not met" — the same three-state discipline as the bundle's declared blindness
and the OKF's `unclassified` remainder. An unknown name is never silently an `other` that reads as
inactivity.

NOTHING HERE IS A VERDICT. A repeat is not automatically waste: re-reading a file after editing it
is correct behaviour. These are counts an operator ranks runs by and a suite regresses against —
the thresholds belong to whoever is tuning, not to this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: What a tool call was FOR. Deliberately few — this is a shape for ranking runs, not a taxonomy.
EDIT = "edit"      # changed a file
READ = "read"      # looked at one
RUN = "run"        # executed something
FIND = "find"      # searched the tree
OTHER = "other"    # a real call this table does not classify — visible, never invisible
INTENTS = (EDIT, READ, RUN, FIND, OTHER)

#: Vendor tool names → intent. Deliberately a table rather than substring matching: `write` and
#: `rewrite` are both edits and `read` is inside `notebook_read`, so a substring rule that got one
#: right would get the next wrong silently. A name absent from here is `OTHER` **and named**, which
#: is the honest failure.
_RAW_INTENTS: dict[str, str] = {
    # edit
    "edit": EDIT, "write": EDIT, "multi_edit": EDIT, "notebook_edit": EDIT, "str_replace": EDIT,
    "apply_patch": EDIT, "update": EDIT, "add": EDIT, "delete": EDIT, "patch": EDIT,
    "create": EDIT, "move": EDIT,
    # read
    "read": READ, "view": READ, "cat": READ, "notebook_read": READ, "open": READ,
    # run
    "bash": RUN, "shell": RUN, "run": RUN, "exec": RUN, "terminal": RUN, "command": RUN,
    # find
    "grep": FIND, "glob": FIND, "search": FIND, "find": FIND, "ls": FIND, "list": FIND,
    "ripgrep": FIND, "codebase_search": FIND,
}


def _normalised(name: str) -> str:
    """One spelling for a tool name: lower-case, no separators.

    THE TABLE IS BUILT THROUGH THIS TOO, and that is the point rather than tidiness. The first
    version normalised only the LOOKUP, so `str_replace` and `codebase_search` sat in the table
    spelled with underscores that the lookup had already stripped — three edit/search tools that
    could never match, falling through to `OTHER` and reported as unclassified for ever. Two
    spellings of the same thing is how the two stop agreeing; there is now one."""
    return (name or "").strip().lower().replace("-", "").replace("_", "").replace(" ", "")


_INTENT_OF: dict[str, str] = {_normalised(k): v for k, v in _RAW_INTENTS.items()}

#: Pulse kinds this module reads. Duck-typed rather than imported: `techlead/watch.read_harness`
#: takes the same list untyped, for the same reason — an observability module that imported the
#: agent adapter would couple the metric to the harness layer at import time.
_TURN = "turn"
_TOOL = "tool"
_REFUSED = "refused"


def intent_of(name: str) -> str:
    """The intent of a vendor tool name. `OTHER` for anything the table has not met."""
    return _INTENT_OF.get(_normalised(name), OTHER)


@dataclass(frozen=True)
class Trajectory:
    """What one pass did, in numbers an operator can rank runs by.

    THE THREE STATES ARE KEPT APART, as everywhere else here. `readable=False` means this harness
    has no stream reader at all, and every count below is meaningless rather than zero — the caller
    must branch on it. `readable=True` with `tool_calls=0` is a measurement: the pass did nothing.
    """

    #: False when `pulses_of` answered None — no reader for this harness. Every field below is then
    #: at its default and MUST NOT be read as a measurement of zero.
    readable: bool = True
    #: assistant steps the stream reported
    turns: int = 0
    #: calls that actually ran — the only evidence of work
    tool_calls: int = 0
    #: calls for a tool this invocation never granted. The CLI denied them, so they are pass spent
    #: asking for something that was never going to arrive.
    refused: int = 0
    #: calls whose `key` had already been seen in this pass. NOT automatically waste — re-reading a
    #: file after editing it is correct — but a run whose repeats dominate its calls is a run to
    #: look at, and that is what this number is for.
    repeated: int = 0
    #: calls the stream did not describe well enough to judge repetition (an empty `key`). Counted
    #: so `repeated` is never read as "and the rest were distinct".
    unkeyed: int = 0
    #: calls per intent, every key in `INTENTS` present so a zero is visible rather than absent
    by_intent: dict[str, int] = field(default_factory=dict)
    #: distinct vendor names that fell through to `OTHER`, sorted. Non-empty means the intent table
    #: does not know this harness's vocabulary — which is a fact about THIS MODULE, not about the
    #: agent, and a reader has to be able to tell.
    unclassified_names: tuple[str, ...] = ()
    #: how many turns passed before the first edit. None = no edit happened in this pass.
    turns_to_first_edit: int | None = None
    #: wall-clock seconds from the first pulse to the first edit. None when the harness stamps no
    #: clock in its stream (only some do) — never 0.0, which would read as instantaneous.
    seconds_to_first_edit: float | None = None
    #: dollars the stream attributed, when it attributed any. None ≠ free.
    spent_usd: float | None = None

    @property
    def repeat_ratio(self) -> float | None:
        """Repeats as a share of the calls where repetition could be judged. None when none could.

        The denominator excludes `unkeyed` deliberately: dividing by every call would report a run
        the stream described poorly as a run that repeated nothing."""
        judged = self.tool_calls - self.unkeyed
        return (self.repeated / judged) if judged > 0 else None

    @property
    def note(self) -> str:
        """One line, never empty — the same rule `HarnessReading.note` keeps. A measurement that
        says nothing when it measured nothing is indistinguishable from one that never ran."""
        if not self.readable:
            return "the trajectory could not be read: this harness has no stream reader"
        if not self.tool_calls:
            return f"{self.turns} turn(s), no tool call — the pass did no work this reader can see"
        parts = [f"{self.turns} turn(s)", f"{self.tool_calls} call(s)"]
        if self.turns_to_first_edit is not None:
            parts.append(f"first edit at turn {self.turns_to_first_edit}")
        else:
            parts.append("no edit")
        if self.repeated:
            parts.append(f"{self.repeated} repeated")
        if self.refused:
            parts.append(f"{self.refused} refused")
        if self.unclassified_names:
            parts.append(f"unclassified tool name(s): {', '.join(self.unclassified_names)}")
        return " · ".join(parts)


def trajectory_of(pulses: list | None) -> Trajectory:
    """Summarise a pass from its pulses. Pure, total, and never raises.

    `None` means there was no reader — the answer is `readable=False`, not a row of zeros. `[]`
    means the stream was read and held nothing, which IS a measurement and reports as one. That
    distinction is `pulses_of`'s own, and collapsing it here would undo it one layer up.
    """
    if pulses is None:
        return Trajectory(readable=False, by_intent=dict.fromkeys(INTENTS, 0))

    counts = dict.fromkeys(INTENTS, 0)
    seen: set[str] = set()
    unknown: set[str] = set()
    turns = tool_calls = refused = repeated = unkeyed = 0
    turns_to_first_edit: int | None = None
    first_at: float | None = None
    first_edit_at: float | None = None
    spent: float | None = None

    for pulse in pulses:
        at = getattr(pulse, "at", None)
        if at is not None and first_at is None:
            first_at = at
        cost = getattr(pulse, "cost_usd", None)
        if cost is not None:
            spent = (spent or 0.0) + cost

        kind = getattr(pulse, "kind", "")
        if kind == _TURN:
            turns += 1
            continue
        if kind == _REFUSED:
            # COUNTED AS A CALL AND NOT CLASSIFIED. It never ran, so crediting it to an intent
            # would report editing that did not happen — but it is pass spent, so a summary that
            # dropped it would report a cheaper run than the one that occurred.
            refused += 1
            continue
        if kind != _TOOL:
            continue

        tool_calls += 1
        name = getattr(pulse, "name", "") or ""
        intent = intent_of(name)
        counts[intent] += 1
        if intent == OTHER:
            unknown.add(name.strip() or "(unnamed)")

        key = getattr(pulse, "key", "") or ""
        if not key:
            unkeyed += 1
        elif key in seen:
            repeated += 1
        else:
            seen.add(key)

        if intent == EDIT and turns_to_first_edit is None:
            # THE TURN COUNT AT THIS MOMENT, not the index of the call. "How many model steps
            # before it started changing anything" is the question; a call index would answer a
            # different one and would move when a harness batches its tool calls differently.
            turns_to_first_edit = turns
            if at is not None:
                first_edit_at = at

    return Trajectory(
        readable=True,
        turns=turns,
        tool_calls=tool_calls,
        refused=refused,
        repeated=repeated,
        unkeyed=unkeyed,
        by_intent=counts,
        unclassified_names=tuple(sorted(unknown)),
        turns_to_first_edit=turns_to_first_edit,
        seconds_to_first_edit=(first_edit_at - first_at
                               if first_edit_at is not None and first_at is not None else None),
        spent_usd=spent,
    )
