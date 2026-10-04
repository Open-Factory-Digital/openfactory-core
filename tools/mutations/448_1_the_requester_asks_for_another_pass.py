"""The requester asks for another pass, from the conversation and the card; the number of passes is
the project's (#448, slice 1)."""

TEST = "tests/test_the_requester_asks_for_another_pass.py"
WORKFLOW = "openfactory/runtime/temporal/workflow.py"
VIEW = "openfactory/runtime/temporal/view.py"
CATALOG = "openfactory/actions/catalog.py"
ACTIVITIES = "openfactory/runtime/temporal/activities.py"
PROJECT = "openfactory/contracts/project.py"
IO = "openfactory/runtime/temporal/io.py"
MODULE = "openfactory/product/module.py"
VOICE = "openfactory/product/voice.py"
ADJUST = "openfactory/product/adjust.py"
CONFIRM = "openfactory/product/confirm.py"
STAGING = "openfactory/product/staging.py"
ROLE = "openfactory/product/role.py"
ENGINE = "openfactory/product/engine.py"
PANEL = "openfactory/api/panel.html"
APP = "openfactory/api/app.py"

MUTATIONS = [
    # ── the budget is the project's ──────────────────────────────────────────────────────────
    ("the job spends the old constant, whatever the project says", WORKFLOW,
     "        if self._adjust_passes >= params.adjust_passes:\n",
     "        if self._adjust_passes >= self._ADJUST_MAX:\n"),
    ("the gate publishes the whole budget as left, however many passes ran", WORKFLOW,
     "                        0, params.adjust_passes - self._adjust_passes)\n",
     "                        0, params.adjust_passes)\n"),
    ("past the budget the standing wait no longer says who decides", WORKFLOW,
     "                    if not auto and self._adjust_passes >= params.adjust_passes:\n",
     "                    if False:\n"),
    ("a job whose input predates the field reads a budget other than today's 2", IO,
     "    adjust_passes: int = ADJUST_PASSES\n",
     "    adjust_passes: int = 3\n"),
    ("the registry's budget is taken as written, unclamped", PROJECT,
     "        kept = min(max(wanted, 0), ADJUST_PASSES_CEILING)\n",
     "        kept = wanted\n"),
    ("the poller starts a job without the project's budget", ACTIVITIES,
     "                          language=str(getattr(project, \"language\", \"\") or \"\"), box=traits,\n"
     "                          adjust_passes=project.adjust_passes),\n",
     "                          language=str(getattr(project, \"language\", \"\") or \"\"), box=traits),\n"),
    ("the panel's scan starts a job without the project's budget", CATALOG,
     "                JobParams(project=proj.name, issue=issue, sandbox=scan_sandbox, image=scan_image,\n"
     "                          adjust_passes=proj.adjust_passes),\n",
     "                JobParams(project=proj.name, issue=issue, sandbox=scan_sandbox, image=scan_image),\n"),

    # ── the seam every answer crosses ────────────────────────────────────────────────────────
    ("the seam delivers a pass the job would refuse", VIEW,
     # re-pinned 2026-10-02: `address` (#330) spends the same budget on the same line
     '    if answer in ("adjust", "address") and gate.get("adjusts_left") == 0:\n',
     "    if False:\n"),
    ("a job that finished is read as one still at its gate", VIEW,
     "    if described.status != WorkflowExecutionStatus.RUNNING:\n",
     "    if False:\n"),
    ("the floor folds a spent budget into 'not waiting on a merge'", CATALOG,
     "    except tv.AdjustsSpent as exc:\n",
     "    except tv.GateDeaf as exc:\n"),

    # ── `correct_card` moves the bar at the merge gate, and only there ───────────────────────
    ("the bar is admitted on any started card, gate or not", MODULE,
     "            if not key or (has_started(key) and not (at_the_gate and not has_finished(key))):\n",
     "            if not key or (has_started(key) and not (bar and not has_finished(key))):\n"),
    ("another card's gate admits the correction", MODULE,
     '                           and canonical_ref(getattr(gate, "card", "")) == number)\n',
     "                           )\n"),
    ("a gate that is not waiting on a person admits the correction", MODULE,
     '                           and getattr(gate, "open", False)\n',
     ""),
    ("a text change rides in at the gate with the bar", MODULE,
     "        at_the_gate = bool(bar and not text and not title and gate is not None\n",
     "        at_the_gate = bool(bar and gate is not None\n"),
    ("anybody may move the bar at the gate", MODULE,
     "                or (at_the_gate and (vouched or self.asked_for(number, actor)))):\n",
     "                or at_the_gate):\n"),
    ("the bar is appended beside the old one instead of replacing it", MODULE,
     '    return _with_section(body, "Acceptance criteria", f"## {named}\\n\\n{listed}"), before\n',
     '    return body.rstrip() + f"\\n\\n## {named}\\n\\n{listed}\\n", before\n'),
    ("a Portuguese card's criteria are renamed into English", MODULE,
     '    named = old.split("\\n", 1)[0].lstrip("#").strip() if old else "Acceptance criteria"\n',
     '    named = "Acceptance criteria"\n'),
    ("the note forgets what the bar said before", VOICE,
     '        note += (before["bar"].format(items="\\n".join(f"- {c}" for c in old_bar)) if old_bar\n'
     '                 else before["no_bar"])\n',
     "        pass\n"),

    # ── who may send a card back, and the gate's word ────────────────────────────────────────
    ("an operator on the product view is refused the pass the floor lets them send", CATALOG,
     "    # the floor — a product-scoped credential never is\n"
     "    vouched = bool(by.admin) and by.may_enter(FLOOR)\n",
     "    # the floor — a product-scoped credential never is\n"
     "    vouched = False\n"),
    ("the card's own requester is not admitted", MODULE,
     "                or self.asked_for(number, actor))\n",
     "                or False)\n"),
    ("the conversation drafts a pass for somebody who may not send it", MODULE,
     "        if not self.may_send_back(number, actor):\n"
     '            return adjust.Prepared(said=adjust_said("not_yours", ref=number, language=lang))\n',
     "        if False:\n"
     '            return adjust.Prepared(said=adjust_said("not_yours", ref=number, language=lang))\n'),
    ("the card's control sends a pass the gate says cannot be sent", MODULE,
     "        if not gate.open:\n"
     '            return WriteResult(ok=False, ref=f"#{number}", detail=adjust_said(\n',
     "        if False:\n"
     '            return WriteResult(ok=False, ref=f"#{number}", detail=adjust_said(\n'),
    ("an instruction longer than the pass takes is sent, to be cut", MODULE,
     "        if len(said) > adjust.INSTRUCTION_LIMIT:\n",
     "        if False:\n"),
    ("the pass is sent before the bar moves", MODULE,
     '        corrected, residue = False, ""\n',
     '        adjust.send_back(self.project, number, instruction=said, by=actor)\n'
     '        corrected, residue = False, ""\n'),
    ("the card view offers the pass to anybody who opens it", MODULE,
     "        if not self.may_send_back(number, actor, vouched=vouched):\n"
     '            return {"offered": False}\n',
     "        if False:\n"
     '            return {"offered": False}\n'),
    ("a spent budget reads as a gate a pass can be sent to", ADJUST,
     "    if left == 0:\n",
     "    if left == -1:\n"),
    ("a pass rewriting the change reads as a gate waiting on a person", ADJUST,
     '    if gate.get("working"):\n',
     "    if False:\n"),
    ("a change the factory lands on its own reads as one waiting on a person", ADJUST,
     '    if not gate or gate.get("auto"):\n',
     "    if not gate:\n"),

    # ── the conversation ─────────────────────────────────────────────────────────────────────
    ("the role's marker is never read", ROLE,
     '        gesture = "adjust" if adjusted else "queue" if QUEUE_MARKER in text else ""\n',
     '        gesture = "queue" if QUEUE_MARKER in text else ""\n'),
    ("the engine ignores the gesture", ENGINE,
     '    if getattr(answer, "gesture", "") == "adjust" and getattr(answer, "gesture_card", ""):\n',
     "    if False:\n"),
    ("the requester's own yes is refused like any non-approver's", CONFIRM,
     '_THE_REQUESTERS_OWN = frozenset({"adjust"})\n',
     "_THE_REQUESTERS_OWN = frozenset()\n"),
    ("a requester's yes confirms any kind of proposal", CONFIRM,
     '    if str(entry.get("kind") or "") in _THE_REQUESTERS_OWN and user:\n',
     "    if user:\n"),
    ("a button posted for one pass sends another with other words", STAGING,
     '    if entry.get("instruction"):\n',
     "    if False:\n"),
    ("the floor's problems are never handed to a redraft", ADJUST,
     "ATTEMPTS = 2\n",
     "ATTEMPTS = 1\n"),
    ("a draft with no bar is shown for a yes", ADJUST,
     "    if not criteria:\n",
     "    if False:\n"),

    # ── the card on the product view, and the floor ──────────────────────────────────────────
    ("the card view asks the engine about cards nobody has started", CATALOG,
     '    if (shown and shown.get("readable") and shown.get("open") and shown.get("started")\n',
     '    if (shown and shown.get("readable") and shown.get("open")\n'),
    ("the page draws the control whatever the server says", PANEL,
     '  if(!a.offered)return a.note?',
     '  if(false)return a.note?'),
    ("the product card draws no control at all", PANEL,
     '    </div>${note}${confirm}${where === "product" ? pvAdjustBlock(c) : ""}`;\n',
     "    </div>${note}${confirm}`;\n"),
    ("the inbox offers adjust past the budget", APP,
     '            if act.get("adjusts_left") == 0:\n',
     "            if False:\n"),
    ("the floor's button is drawn whatever passes are left", PANEL,
     '          (a.adjusts_left===0?"":` <button class="btn sm ghost" data-act="mergeGate"',
     '          (` <button class="btn sm ghost" data-act="mergeGate"'),
]
