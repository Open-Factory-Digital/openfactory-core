"""The trajectory's trip from the stream to the row to the panel, and the twelve ways it lies.

`observability/trajectory.py` shipped the measurement and nothing read it. This is the wiring —
and almost every way it can go wrong produces a NUMBER rather than an error, which is why the plan
is long for a change this size.

ROWS 3-6 ARE ONE IDEA, cut at four different layers. `AgentRunResult.raw_output` defaults to `""`,
and `pulses_of(harness, "")` answers `[]` — "read it, it held no events" — which summarises to a
perfectly readable trajectory of ZERO tool calls. Recorded, that row says the agent called no
tools; what actually happened is that nobody captured its output. The two must not land in the same
row, must not average together, and must not render alike, and the distinction is destroyable
independently at the metric, at the activity, at the rollup and at the panel's own reader.

ROW 7 IS THE POSITIVE TWIN OF ALL OF THEM. A version that recorded nothing for every pass would
satisfy rows 3-6 perfectly and the measurement would simply not exist. A pass that genuinely did
nothing is a measurement and has to survive as one.

ROWS 11-12 CUT THE OTHER WAY, the discipline this directory now keeps: a fix that refuses to record
anything it is not certain of, and a rollup that sums a number which does not sum.
"""

TEST = "tests/test_the_trajectory_reaches_the_record.py"

MUTATIONS = [
    # ── the measurement never happens ───────────────────────────────────────────────────────────
    ("the trajectory is never read, so the stream stays parsed-and-discarded exactly as before and "
     "the two instruments the operator has no other source for stay empty",
     "openfactory/orchestrator/machine.py",
     "            **JobRunner._trajectory_of(res)))",
     "            ))"),

    ("the dimensions are computed and then dropped on the way to the row, so the numbers exist for "
     "the length of one function call and nowhere else",
     "openfactory/runtime/temporal/activities.py",
     '                tool_calls=r.get("tool_calls"), repeated_calls=r.get("repeated_calls"),\n'
     '                refused_calls=r.get("refused_calls"),\n'
     '                turns_to_first_edit=r.get("turns_to_first_edit")))',
     "                ))"),

    # ── the zero nobody measured, at each layer it can be reintroduced ──────────────────────────
    ("an UNCAPTURED stream is summarised anyway, so a pass whose output nobody recorded lands as a "
     "pass that called no tools — a measurement of something that was never measured",
     "openfactory/orchestrator/machine.py",
     '        if not (res.raw_output or "").strip():\n            return {}',
     "        if False:\n            return {}"),

    ("a harness with no stream reader records zeros instead of nothing, so every codex or kimi "
     "deployment reports its agents as doing no work at all",
     "openfactory/orchestrator/machine.py",
     "            if not t.readable:\n                return {}",
     "            if False:\n                return {}"),

    ("the activity turns an absent dimension into a zero on its way to the row, so the "
     "distinction survives the metric and dies one layer later",
     "openfactory/runtime/temporal/activities.py",
     '                tool_calls=r.get("tool_calls"), repeated_calls=r.get("repeated_calls"),',
     '                tool_calls=r.get("tool_calls", 0) or 0,\n'
     '                repeated_calls=r.get("repeated_calls", 0) or 0,'),

    ("the per-ticket rollup reports zero for a ticket no pass could be read for, so an operator "
     "ranking tickets by wasted calls is handed a zero nobody measured, at the top of the list",
     "openfactory/api/metrics_view.py",
     '            "tool_calls": p["calls"] if p["read"] else None,',
     '            "tool_calls": p["calls"],'),

    # ROW REWRITTEN. The first version removed an explicit `if value is None or value == ""`
    # guard — and survived, because `float(None)` raises and lands in the very `except` below it.
    # The clause was DEAD CODE, not a defence, and the mutation is what proved it: the fix was to
    # delete the redundant line rather than to write a guard for a branch nothing reached.
    ("the panel's own reader invents a zero for an absent value — `int(x or 0)`, which is right "
     "for a cost and wrong for this, and the two are one line apart",
     "openfactory/api/metrics_view.py",
     "        return int(float(value))",
     "        return int(value or 0)"),

    # ── the positive twin ───────────────────────────────────────────────────────────────────────
    ("a pass that genuinely did nothing records nothing, so the honest zero and the unmeasured one "
     "collapse the OTHER way and the measurement never exists at all",
     "openfactory/orchestrator/machine.py",
     '            return {"tool_calls": t.tool_calls, "repeated_calls": t.repeated,',
     '            return {} if not t.tool_calls else {"tool_calls": t.tool_calls,\n'
     '                    "repeated_calls": t.repeated,'),

    # ── the numbers themselves ──────────────────────────────────────────────────────────────────
    ("the rollup counts only the passes it could read but sums across all of them, so a ticket "
     "whose second pass was unreadable reports the first pass's calls as the whole ticket's",
     "openfactory/api/metrics_view.py",
     '        if r.get("tool_calls") is not None:\n            p["read"] += 1',
     '        if True:\n            p["read"] += 1'),

    ("a stringified number from the DynamoDB backend reads as unmeasured, so the whole panel goes "
     "blank on the one deployment shape that stores numbers as strings",
     "openfactory/api/metrics_view.py",
     "        return int(float(value))",
     "        raise ValueError(value)"),

    # ── THE OTHER DIRECTION ─────────────────────────────────────────────────────────────────────
    ("OVER-TIGHTENED — a pass with no EDIT is treated as unmeasurable, so every planner, reviewer "
     "and diagnosis pass loses its numbers because it was never going to edit anything",
     "openfactory/orchestrator/machine.py",
     "            if not t.readable:\n                return {}",
     "            if not t.readable or t.turns_to_first_edit is None:\n                return {}"),

    ("OVER-TIGHTENED — the rollup sums `turns_to_first_edit` across the ticket's passes, which is "
     "a per-pass shape: two of them added together is a number with no meaning, printed in a "
     "column an operator will nonetheless rank by",
     "openfactory/api/metrics_view.py",
     '            "refused_calls": p["refused"] if p["read"] else None,',
     '            "refused_calls": p["refused"] if p["read"] else None,\n'
     '            "turns_to_first_edit": p["calls"],'),
]
