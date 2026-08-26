"""#181 — a rejected review can be answered AND asked again.

The cuts fall in three groups: the verb reaching every surface a person can press it from, the
pass doing only what it promises (read, never write, never run an agent), and the refusal being
one test rather than a flag and a sentence that agree today.
"""

TEST = "tests/test_a_rejected_review_can_be_asked_again.py"

MUTATIONS = [
    # ── the verb has to survive every hop ───────────────────────────────────────────────────────
    ("the signal drops the answer, so every surface reports success and nothing happens",
     "openfactory/runtime/temporal/workflow.py",
     '        if answer in ("merge", "adjust", "discard", "review"):',
     '        if answer in ("merge", "adjust", "discard"):'),

    ("the client side refuses the verb its own workflow accepts",
     "openfactory/runtime/temporal/view.py",
     '    if answer not in ("merge", "adjust", "discard", "review"):',
     '    if answer not in ("merge", "adjust", "discard"):'),

    ("the gate can ask for a re-review and never publishes what came back",
     "openfactory/runtime/temporal/workflow.py",
     "            if not self._reviewed_again(read):",
     "            if not (read.review is None):"),

    ("the catalogue row stops saying the ask is paid for",
     "openfactory/actions/catalog.py",
     '                        "spends a model pass and writes nothing, so prefer it over sending a "',
     '                        "writes nothing, so prefer it over sending a "'),

    # ── the pass reads; it does not write, and it does not run an agent ─────────────────────────
    ("the read pass runs the project's setup, so an honest reading costs what a repair costs",
     "openfactory/orchestrator/machine.py",
     "            diff = self._pr_diff(ws, base)\n"
     "            if diff is None:\n"
     "                return RunResult(\n"
     "                    ticket_id=ticket.id, state=JobState.PR_OPEN, branch=branch,\n"
     "                    code_changed=False,",
     "            self._run_setup(ticket, ws)\n"
     "            diff = self._pr_diff(ws, base)\n"
     "            if diff is None:\n"
     "                return RunResult(\n"
     "                    ticket_id=ticket.id, state=JobState.PR_OPEN, branch=branch,\n"
     "                    code_changed=False,"),

    ("the read pass runs an agent — the one thing it promises it will not do",
     "openfactory/orchestrator/machine.py",
     "            self._set_state(ticket, JobState.REVIEWING)\n"
     "            review = self.reviewer.review(\n"
     "                sandbox=self.sandbox, workspace=ws,\n"
     "                review_input=ReviewInput(ticket=ticket, diff=diff, validations=[]),\n"
     "            )\n"
     "            self._count_review(review)",
     "            self._set_state(ticket, JobState.REVIEWING)\n"
     "            self.agent.repair(sandbox=self.sandbox, workspace=ws,\n"
     "                              context=self._build_context(ticket, ws), failure_log='')\n"
     "            review = self.reviewer.review(\n"
     "                sandbox=self.sandbox, workspace=ws,\n"
     "                review_input=ReviewInput(ticket=ticket, diff=diff, validations=[]),\n"
     "            )\n"
     "            self._count_review(review)"),

    ("a deployment with no reviewer gets silence instead of a sentence",
     "openfactory/orchestrator/machine.py",
     '                note="this deployment has no reviewer — nothing re-read the pull request",',
     '                note="",'),

    ("the box's review flag is renamed on one side only",
     "openfactory/runtime/boxed_job.py",
     '        if os.environ.get("OPENFACTORY_REVIEW_PASS"):',
     '        if os.environ.get("OPENFACTORY_REVIEW"):'),

    ("the read is launched onto the repair path, so it runs an agent and pushes",
     "openfactory/runtime/temporal/activities.py",
     '        extra_env={"OPENFACTORY_PR": inp.pr_url, "OPENFACTORY_REVIEW_PASS": "1"},',
     '        extra_env={"OPENFACTORY_PR": inp.pr_url, "OPENFACTORY_CI_REPAIR": "1"},'),

    # ── the refusal is ONE test, and it is the right one ────────────────────────────────────────
    ("a job that ran with review off is still offered a re-review",
     "openfactory/runtime/temporal/workflow.py",
     '        if not params.review:\n'
     '            return "this job ran with review turned off — there is no reviewer to ask"',
     '        if False:\n'
     '            return "this job ran with review turned off — there is no reviewer to ask"'),

    ("a pull request nothing has reviewed is offered a RE-review",
     "openfactory/runtime/temporal/workflow.py",
     '        if not (self._verdict or {}).get("decision"):',
     '        if False and not (self._verdict or {}).get("decision"):'),

    ("the cap is off by one, so the bill has one more pass in it than the number says",
     "openfactory/runtime/temporal/workflow.py",
     "        if self._review_passes >= self._REVIEW_MAX:",
     "        if self._review_passes > self._REVIEW_MAX:"),

    ("the button is published from its own belief instead of the one test",
     "openfactory/runtime/temporal/workflow.py",
     "                    self._merge_wait[\"can_review\"] = bool(\n"
     "                        gate_live and not self._re_review_refusal(params))",
     "                    self._merge_wait[\"can_review\"] = bool(gate_live and params.review)"),

    ("the handler decides for itself, so a page and its engine can disagree about one job",
     "openfactory/runtime/temporal/workflow.py",
     "            refusal = self._re_review_refusal(params)",
     "            refusal = \"\" if self._review_passes < 99 else \"spent\""),

    # ── the surfaces ────────────────────────────────────────────────────────────────────────────
    ("the API publishes the option on every gate, including where it would be refused",
     "openfactory/api/app.py",
     '            if act.get("can_review"):',
     "            if True:"),

    ("the panel goes back to keeping its own list of what a gate accepts",
     "openfactory/api/panel.html",
     "    const opts=(it.options&&it.options.length)?it.options:[",
     "    const opts=["),

    ("the project card offers the re-review whatever the job says",
     "openfactory/api/panel.html",
     "        (a.can_review?` <button class=\"btn sm ghost\" data-act=\"mergeGate\"",
     "        (true?` <button class=\"btn sm ghost\" data-act=\"mergeGate\""),

    # ── the gesture, in both languages ──────────────────────────────────────────────────────────
    ("the Portuguese ask loses its repetition marker and stops matching",
     "openfactory/actions/floor_intents.py",
     r'        r"|revis[ae]r?\s+(?:isso\s+|o\s+pr\s+|a\s+mudan[çc]a\s+)?(?:de\s+novo|novamente|outra\s+vez)"',
     r'        r"|revis[ae]r?\s+(?:isso\s+|o\s+pr\s+|a\s+mudan[çc]a\s+)?(?:novamente|outra\s+vez)"'),

    ("the English permission form is dropped, so the gesture exists in one language only",
     "openfactory/actions/floor_intents.py",
     r'        r"|re-?review|review\s+(?:it\s+|this\s+)?again|re-?run\s+(?:the\s+)?review)"',
     r'        r")"'),

    ("the bare verb is admitted, so every sentence ABOUT a review buys one",
     "openfactory/actions/floor_intents.py",
     r'        r"|re-?review(?:s|ed)?"',
     r'        r"|review(?:s|ed)?"'),
]
