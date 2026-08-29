"""The trajectory measurement, and the sixteen ways it stops being one.

THE GAP THIS CLOSES. `stream.pulses_of` parses one pulse per tool call — name, target, a clock
where the harness stamps one, and a `key` built to answer "what makes two calls THE SAME call".
`techlead/watch.read_harness` asks a PATHOLOGY question of them (is this stuck), uses the answer
live, and drops it. `AgentRunMetric` keeps cost, turns and tokens. The per-call detail is computed
on every pass and kept by nobody — so *is the factory fast* and *is it cheap*, two of the six
outcomes this product is sold on, have no instrument while their raw material is already being
produced.

CUTS IN BOTH DIRECTIONS, and rows 14-16 are the new half. Every plan in this directory until now
restored a defect and stopped there. A guard that only ever sees the loosening cut cannot see the
opposite failure — the version that refuses everything, that reports every legitimate re-read as
waste, or that blanks a whole measurement because one tool name was unfamiliar. Those are real
failure modes, they are the ones an over-eager fix produces, and rows 14-16 are where they live.

ROW 2 IS A REGRESSION THAT HAPPENED, not a hypothesis: the first version normalised only the
LOOKUP, so `str_replace`, `apply_patch` and `codebase_search` sat in the table spelled with
underscores the lookup had already stripped. Three edit and search tools that could never match,
falling through to `OTHER`, reported as unclassified for ever, on every harness.

ROW 16 IS ONE THE FIXTURE HAD TO BE REBUILT TO REACH. With one tool call per turn, "turns before
the first edit" and "index of the first edit call" are the same number and the cut is invisible.
The fixture now batches two calls into one turn, which is also what a real harness does.
"""

TEST = "tests/test_the_trajectory_is_a_measurement.py"

MUTATIONS = [
    # ── the vendor's names, read literally ──────────────────────────────────────────────────────
    ("intent is read from the literal vendor name, so `Edit` classifies on Claude Code and every "
     "codex, opencode and kimi spelling falls to OTHER — a confident zero for editing on three of "
     "the four harnesses the agnosticism claim rests on",
     "openfactory/observability/trajectory.py",
     "    return _INTENT_OF.get(_normalised(name), OTHER)",
     "    return _INTENT_OF.get(name, OTHER)"),

    ("the table is not normalised through the same function — the regression exactly as it "
     "happened: `str_replace`, `apply_patch` and `codebase_search` can never match, because the "
     "lookup strips the underscores the keys still carry",
     "openfactory/observability/trajectory.py",
     "_INTENT_OF: dict[str, str] = {_normalised(k): v for k, v in _RAW_INTENTS.items()}",
     "_INTENT_OF: dict[str, str] = dict(_RAW_INTENTS)"),

    ("a name the table does not know is counted and NOT named, so \"this agent did no editing\" "
     "and \"this harness calls it something we have not met\" become the same reading",
     "openfactory/observability/trajectory.py",
     "        if intent == OTHER:\n            unknown.add(name.strip() or \"(unnamed)\")",
     "        if False:\n            unknown.add(name.strip() or \"(unnamed)\")"),

    ("an intent with no calls is dropped from the map, so a zero renders as nothing and reads as "
     "\"not measured\" rather than \"measured, and it is zero\"",
     "openfactory/observability/trajectory.py",
     "    counts = dict.fromkeys(INTENTS, 0)",
     "    counts = {}"),

    # ── the three states collapse ───────────────────────────────────────────────────────────────
    ("a harness with NO READER reports a row of zeros instead of saying it could not be read — "
     "undoing, one layer up, the exact distinction `pulses_of` exists to keep",
     "openfactory/observability/trajectory.py",
     "    if pulses is None:\n        return Trajectory(readable=False, by_intent=dict.fromkeys("
     "INTENTS, 0))",
     "    if pulses is None:\n        pulses = []"),

    ("the note goes empty on the unreadable case, and a measurement that says nothing when it "
     "measured nothing is indistinguishable from one that never ran",
     "openfactory/observability/trajectory.py",
     '            return "the trajectory could not be read: this harness has no stream reader"',
     '            return ""'),

    # ── repetition, and what could not be judged ────────────────────────────────────────────────
    ("a call the stream did not describe well enough is counted as DISTINCT, so a run whose "
     "harness reports bare `bash` lines reads as a run that repeated nothing",
     "openfactory/observability/trajectory.py",
     "        if not key:\n            unkeyed += 1\n        elif key in seen:",
     "        if False:\n            unkeyed += 1\n        elif key in seen:"),

    ("the ratio divides by every call rather than by the calls repetition could be judged on, so "
     "a poorly-described stream dilutes the number and the dilution is invisible in the result",
     "openfactory/observability/trajectory.py",
     "        judged = self.tool_calls - self.unkeyed",
     "        judged = self.tool_calls"),

    ("a run where nothing could be judged reports a ratio of zero — \"it repeated nothing\", which "
     "was never measured",
     "openfactory/observability/trajectory.py",
     "        return (self.repeated / judged) if judged > 0 else None",
     "        return (self.repeated / judged) if judged > 0 else 0.0"),

    # ── the two numbers an operator actually wants ──────────────────────────────────────────────
    ("a pass that edited nothing reports zero turns to the first edit, which means it edited "
     "immediately — the exact opposite of the truth",
     "openfactory/observability/trajectory.py",
     "        turns_to_first_edit=turns_to_first_edit,",
     "        turns_to_first_edit=turns_to_first_edit or 0,"),

    ("seconds to the first edit reports 0.0 where the harness stamps no clock, so a stream that "
     "cannot answer the question renders as one that answered `instantaneous`",
     "openfactory/observability/trajectory.py",
     "        seconds_to_first_edit=(first_edit_at - first_at\n"
     "                               if first_edit_at is not None and first_at is not None "
     "else None),",
     "        seconds_to_first_edit=((first_edit_at or 0.0) - (first_at or 0.0)),"),

    ("a REFUSED call is credited to its intent, so a pass reports editing that the CLI denied and "
     "that never happened",
     "openfactory/observability/trajectory.py",
     "            refused += 1\n            continue",
     "            refused += 1\n            counts[intent_of(getattr(pulse, \"name\", \"\") or \"\")]"
     " = counts.get(intent_of(getattr(pulse, \"name\", \"\") or \"\"), 0) + 1\n            continue"),

    ("the spend reported by a provider that reports none renders as free, rather than as unknown",
     "openfactory/observability/trajectory.py",
     "    spent: float | None = None",
     "    spent: float | None = 0.0"),

    # ── THE OTHER DIRECTION: the over-tightened version, which no plan here has cut before ──────
    ("OVER-TIGHTENED — one unfamiliar tool name blanks the whole measurement. This is the fix an "
     "over-eager reading of row 3 produces: refusing to report anything rather than reporting an "
     "`other` bucket, so a single unknown name costs an operator every other number in the run",
     "openfactory/observability/trajectory.py",
     "        counts[intent] += 1",
     "        counts[intent] += 1\n"
     "        if intent == OTHER:\n            return Trajectory(readable=False, "
     "by_intent=dict.fromkeys(INTENTS, 0))"),

    ("OVER-TIGHTENED — every call after the first counts as a repeat, whatever it was. Re-reading "
     "a file after editing it is CORRECT behaviour, and a measure that scores it as waste sends an "
     "operator tuning against the thing the agent should be doing",
     "openfactory/observability/trajectory.py",
     "        elif key in seen:\n            repeated += 1",
     "        elif seen:\n            repeated += 1"),

    ("OVER-TIGHTENED — the first edit is reported by CALL INDEX rather than by turns, which "
     "overstates the exploration tax on any harness that batches its tool calls into one turn, "
     "and moves the number when a vendor changes its batching and the agent changed nothing",
     "openfactory/observability/trajectory.py",
     "            turns_to_first_edit = turns",
     "            turns_to_first_edit = tool_calls"),
]
