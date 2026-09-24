"""Proven by breaking it — a pass that pauses is charged like every other pass (#262).

The rate-limit arm returned before the pass was counted, so a ticket that spent real money and
then hit the usage limit came back with `agent_runs == []` and `total_cost_usd is None`. Not one
place: the planner, the executor and all three repair loops asked `pause_reason` above their
`_count`; `_paused` never carried a total even where the count came first (recovery, CI repair);
the suppression-repair pass was never counted on any way out; and `_hold` took whatever total its
caller passed — none from the planner's gates, a pre-review one from the holds after the review.

FIVE CLAIMS:

  1. **A pass is counted before it is asked whether it paused**, at every pass that can pause —
     the row reaches the result, and its turns reach the budget the resume is measured against.
  2. **The pause reaches the journal**, so `/api/jobs` and the panel say what the result says.
  3. **Both parked doors charge**: `_paused` and `_hold` carry the rows AND the total, whatever
     their caller passed.
  4. **The suppression-repair pass is counted** on every way out, not only in the journal.
  5. **Counting is not pricing.** A paused pass that reported no price is a row with no price and
     a total of `None`, never `$0.00`.

The guard is `tests/test_a_paused_pass_is_charged.py`.
"""

TEST = "tests/test_a_paused_pass_is_charged.py"

MACHINE = "openfactory/orchestrator/machine.py"

MUTATIONS = [
    # ── claim 1: counted before the pause is asked ────────────────────────────────────────────
    ("THE DEFECT ITSELF: the executor is asked whether it paused before it is counted", MACHINE,
     "            self._count(agent_result, \"executor\")\n"
     "            if agent_result.pause_reason:\n"
     "                return self._paused(\n"
     "                    ticket, agent_result.pause_reason, agent_result.retry_at, "
     "branch=branch,\n"
     "                    ws=ws, resume_handle=agent_result.resume_handle,\n"
     "                )\n",
     "            if agent_result.pause_reason:\n"
     "                return self._paused(\n"
     "                    ticket, agent_result.pause_reason, agent_result.retry_at, "
     "branch=branch,\n"
     "                    ws=ws, resume_handle=agent_result.resume_handle,\n"
     "                )\n"
     "            self._count(agent_result, \"executor\")\n"),

    ("the planner is counted after its pause again, where it used to be", MACHINE,
     "                self._count(plan_result, \"planner\")\n"
     "                if plan_result.pause_reason:\n"
     "                    self._emit(ticket, \"note\", f\"planner paused: "
     "{plan_result.summary[:200]}\",\n"
     "                               cost_usd=plan_result.cost_usd, role=\"planner\")\n"
     "                    return self._paused(\n"
     "                        ticket, plan_result.pause_reason, plan_result.retry_at, "
     "branch=branch,\n"
     "                        ws=ws, resume_handle=plan_result.resume_handle,\n"
     "                    )\n",
     "                if plan_result.pause_reason:\n"
     "                    self._emit(ticket, \"note\", f\"planner paused: "
     "{plan_result.summary[:200]}\",\n"
     "                               cost_usd=plan_result.cost_usd, role=\"planner\")\n"
     "                    return self._paused(\n"
     "                        ticket, plan_result.pause_reason, plan_result.retry_at, "
     "branch=branch,\n"
     "                        ws=ws, resume_handle=plan_result.resume_handle,\n"
     "                    )\n"
     "                self._count(plan_result, \"planner\")\n"),

    ("the gate repair pauses before it is journalled or counted — its old order", MACHINE,
     "                                   _gates_brief(validations))\n"
     "                for action in rep.actions:\n",
     "                                   _gates_brief(validations))\n"
     "                if rep.pause_reason:\n"
     "                    return self._paused(ticket, rep.pause_reason, rep.retry_at, "
     "branch=branch,\n"
     "                                        ws=ws, resume_handle=rep.resume_handle)\n"
     "                for action in rep.actions:\n"),

    ("the review repair pauses before it is journalled or counted — its old order", MACHINE,
     "                                       _review_repair_brief(result.review))\n"
     "                    for action in rep.actions:\n",
     "                                       _review_repair_brief(result.review))\n"
     "                    if rep.pause_reason:\n"
     "                        return self._paused(ticket, rep.pause_reason, rep.retry_at, "
     "branch=branch,\n"
     "                                            ws=ws, resume_handle=rep.resume_handle)\n"
     "                    for action in rep.actions:\n"),

    ("CI repair is asked whether it paused before it is counted — only the order guard sees it",
     MACHINE,
     "            self._count(rep, \"ci_repair\")\n"
     "            if rep.pause_reason:\n"
     "                return as_left(self._paused(ticket, rep.pause_reason, rep.retry_at, "
     "branch=branch,\n"
     "                                            ws=ws, resume_handle=rep.resume_handle))\n",
     "            if rep.pause_reason:\n"
     "                return as_left(self._paused(ticket, rep.pause_reason, rep.retry_at, "
     "branch=branch,\n"
     "                                            ws=ws, resume_handle=rep.resume_handle))\n"
     "            self._count(rep, \"ci_repair\")\n"),

    # ── claim 2: the pause reaches the journal ────────────────────────────────────────────────
    ("the paused planner is counted and never journalled — the dashboard does not hear of it",
     MACHINE,
     "                    self._emit(ticket, \"note\", f\"planner paused: "
     "{plan_result.summary[:200]}\",\n"
     "                               cost_usd=plan_result.cost_usd, role=\"planner\")\n",
     ""),

    # ── claim 3: both parked doors charge ─────────────────────────────────────────────────────
    ("THE PAUSE AS IT WAS: the rows, and no total beside them", MACHINE,
     "        return self._charged(RunResult(ticket_id=ticket.id, state=state, branch=branch, "
     "note=note,\n"
     "                                       retry_at=retry_at, resume_handle=handle,\n"
     "                                       spent_turns=getattr(self, \"_turns\", 0)))\n",
     "        return RunResult(ticket_id=ticket.id, state=state, branch=branch, note=note,\n"
     "                         retry_at=retry_at, resume_handle=handle,\n"
     "                         spent_turns=getattr(self, \"_turns\", 0),\n"
     "                         agent_runs=getattr(self, \"_agent_runs\", []))\n"),

    ("THE HOLD AS IT WAS: the rows by default, and the total only if the caller passed one",
     MACHINE,
     "        return self._charged(  # the spend before the park\n"
     "            RunResult(ticket_id=ticket.id, state=state, note=reason, **extra))",
     "        extra.setdefault(\"agent_runs\", getattr(self, \"_agent_runs\", []))\n"
     "        return RunResult(ticket_id=ticket.id, state=state, note=reason, **extra)"),

    # ── claim 4: the suppression-repair pass is counted ───────────────────────────────────────
    ("the suppression-repair pass is journalled and never counted, as it always was", MACHINE,
     "                self._count(rep, \"suppression_repair\")\n",
     ""),

    # ── claim 5: counting is not pricing ──────────────────────────────────────────────────────
    ("a counted pass that reported no price is recorded as free", MACHINE,
     "            cost_usd=res.cost_usd, num_turns=res.num_turns,\n",
     "            cost_usd=res.cost_usd or 0.0, num_turns=res.num_turns,\n"),
]
