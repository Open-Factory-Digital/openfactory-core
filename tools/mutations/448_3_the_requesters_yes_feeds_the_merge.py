"""The requester's "that's it" is recorded against the head they tried, the person merging sees it,
it lets the factory merge when the look is all that holds the merge, and the requester hears the
change went in (#448, slice 3)."""

TEST = "tests/test_the_requesters_yes_feeds_the_merge.py"
MERGE_POLICY = "openfactory/orchestrator/merge_policy.py"
MACHINE = "openfactory/orchestrator/machine.py"
VERDICT = "openfactory/review/verdict.py"
WORKFLOW = "openfactory/runtime/temporal/workflow.py"
ACTIVITIES = "openfactory/runtime/temporal/activities.py"
WORKER = "openfactory/runtime/temporal/worker.py"
METRICS = "openfactory/observability/metrics.py"
DEMAND = "openfactory/preview/demand.py"
ADJUST = "openfactory/product/adjust.py"
ACCEPT = "openfactory/product/accept.py"
MODULE = "openfactory/product/module.py"
ROLE = "openfactory/product/role.py"
ENGINE = "openfactory/product/engine.py"
CONFIRM = "openfactory/product/confirm.py"
STAGING = "openfactory/product/staging.py"
EVENTS = "openfactory/product/events.py"
CATALOG = "openfactory/actions/catalog.py"
APP = "openfactory/api/app.py"
PANEL = "openfactory/api/panel.html"
TECHLEAD = "openfactory/techlead/conversation.py"

MUTATIONS = [
    # ── the machine says when the look is ALL that holds a merge ─────────────────────────────
    ("the look is called the only hold with another hold beside it", MERGE_POLICY,
     "    return bool(result.preview_required and should_auto_merge(\n"
     '        manifest, result.model_copy(update={"preview_required": False}), profile=profile))\n',
     "    return bool(result.preview_required)\n"),
    ("the machine never says the look is the only hold", MACHINE,
     "            result.auto_but_for_the_look = auto_but_for_the_look(\n",
     "            result.auto_but_for_the_look = False and auto_but_for_the_look(\n"),
    ("the pull request says nobody merges it when the requester's yes does", MACHINE,
     "        if result.preview_required and result.auto_but_for_the_look:\n",
     "        if False:\n"),

    # ── the reading standing now still admits it ─────────────────────────────────────────────
    ("a pass nobody read admits the merge", VERDICT,
     '    if v.get("stale") or not_verified(v):\n',
     "    if not_verified(v):\n"),
    ("a change nothing verified admits the merge", VERDICT,
     '    if v.get("stale") or not_verified(v):\n',
     '    if v.get("stale"):\n'),
    ("a rejection after the judgement admits the merge", VERDICT,
     '    return v.get("decision") != "rejected" or judged == "rejected"\n',
     "    return True\n"),
    ("an advisory rejection the judgement admitted holds it now", VERDICT,
     '    return v.get("decision") != "rejected" or judged == "rejected"\n',
     '    return v.get("decision") != "rejected"\n'),

    # ── the real job ─────────────────────────────────────────────────────────────────────────
    ("the job never publishes that the look alone holds it", WORKFLOW,
     "                        result.auto_but_for_the_look and still_admits_the_merge(\n",
     "                        False and still_admits_the_merge(\n"),
    ("the job publishes it whatever a pass rewrote", WORKFLOW,
     "                        result.auto_but_for_the_look and still_admits_the_merge(\n",
     "                        result.auto_but_for_the_look or still_admits_the_merge(\n"),
    ("the requester is never told it went in", WORKFLOW,
     '        if not workflow.patched("the-requester-hears-it-went-in"):\n            return\n',
     "        if True:\n            return\n"),
    ("the telling runs on a history that never recorded it", WORKFLOW,
     '        if not workflow.patched("the-requester-hears-it-went-in"):\n            return\n',
     "        if False:\n            return\n"),
    # re-pinned 2026-10-04: a watched deploy that is the last stage follows too (#448 slice 5)
    ("stages are said to follow when none do", WORKFLOW,
     "                params, result, stages_follow=should_promote or deploy_is_last)\n",
     "                params, result, stages_follow=True)\n"),
    ("the activity is not registered on the worker", WORKER,
     "    # #448 — and told it went in, the moment it merged, whoever merged it\n"
     "    tell_the_requester_it_merged,\n",
     ""),
    ("the activity reaches no event", ACTIVITIES,
     "            return events.merged_for_you(ProjectRegistry().get(inp.project), "
     "card=inp.issue,\n",
     "            return (lambda *a, **k: False)(ProjectRegistry().get(inp.project), "
     "card=inp.issue,\n"),

    # ── the head they tried, and nothing else ────────────────────────────────────────────────
    ("the gate's word on the look is never read", ADJUST,
     '                look_only=gate.get("auto_but_for_the_look") is True)\n',
     "                look_only=False)\n"),
    ("nothing tried is accepted", ACCEPT,
     "    if not built:\n        return Tried(why=UNTRIED)\n",
     "    if False:\n        return Tried(why=UNTRIED)\n"),
    ("a change that moved since the preview is accepted", ACCEPT,
     "    if now and now != built:\n",
     "    if False:\n"),
    ("the yes is judged on the forge's minute-old answer", ACCEPT,
     "def tried(project, card: str, pr_url: str, *, fresh: bool = True) -> Tried:\n",
     "def tried(project, card: str, pr_url: str, *, fresh: bool = False) -> Tried:\n"),
    ("the cache is read whatever the yes asked for", DEMAND,
     "    if hit and not fresh and now - hit[0] < FORGE_TTL_SECONDS:\n",
     "    if hit and now - hit[0] < FORGE_TTL_SECONDS:\n"),
    ("a head the forge did not confirm is merged", MODULE,
     "        return bool(gate.look_only and gate.why != DEAF and tried.at_head is True)\n",
     "        return bool(gate.look_only and gate.why != DEAF and tried.at_head is not False)\n"),
    ("the conversation stages a yes on nothing tried", MODULE,
     "        if tried.why:\n"
     "            return accept.Prepared(said=accept_change_said(tried.why, ref=number, "
     "language=lang))\n",
     "        if False:\n"
     "            return accept.Prepared(said=accept_change_said(tried.why, ref=number, "
     "language=lang))\n"),
    ("a preview rebuilt since the proposal is accepted in their name", MODULE,
     "        if head and head != tried.head:\n",
     "        if False:\n"),
    ("a yes that was not written down goes on to merge", MODULE,
     "            return refused(accept.UNRECORDED)\n",
     "            pass\n"),
    ("somebody who did not ask for the card may accept it", MODULE,
     '        if not self.may_send_back(number, actor, vouched=vouched):\n'
     '            return refused("not_yours")\n',
     "        if False:\n"
     '            return refused("not_yours")\n'),
    ("the card says nothing of the yes", MODULE,
     '            self._tracker().comment(f"#{number}", change_accepted_note(\n',
     '            (lambda *a: None)(f"#{number}", change_accepted_note(\n'),
    ("the store refuses the row the yes is", METRICS,
     '                     "card_accepted",\n',
     ""),

    # ── what stands, at each gate ────────────────────────────────────────────────────────────
    ("another pull request's yes stands for this one", ACCEPT,
     '            and (not pr_url or str((r.get("extra") or {}).get("pr_url", "")) == pr_url)]\n',
     "            ]\n"),
    ("the oldest yes stands", ACCEPT,
     '    row = max(mine, key=lambda r: str(r.get("ts", "")))\n',
     '    row = min(mine, key=lambda r: str(r.get("ts", "")))\n'),
    ("a yes on an earlier head reads as current", ACCEPT,
     "            current = (built == acc.head) if built else None\n",
     "            current = True if built else None\n"),
    ("a gate nobody is asked about shows a yes", ACCEPT,
     '    if action.get("auto") or action.get("working") or not pr_url:\n',
     "    if not pr_url:\n"),

    # ── the conversation ─────────────────────────────────────────────────────────────────────
    ("the role's marker is never read", ROLE,
     "        accepted = None if adjusted else _ACCEPT_RE.search(text)\n",
     "        accepted = None\n"),
    ("the engine ignores the gesture", ENGINE,
     '    if getattr(answer, "gesture", "") == "accept" and getattr(answer, "gesture_card", ""):\n',
     "    if False:\n"),
    ("the requester's own yes is refused like any non-approver's", CONFIRM,
     '_THE_REQUESTERS_OWN = frozenset({"adjust", "accept_change"})\n',
     '_THE_REQUESTERS_OWN = frozenset({"adjust"})\n'),
    ("a refused yes is told it was a pass not sent", CONFIRM,
     '        said = accept_change_said if entry.get("kind") == "accept_change" else adjust_said\n',
     "        said = adjust_said\n"),
    ("the yes forgets the conversation it was said in", CONFIRM,
     '                                  where=str(entry.get("conversation") or ""))\n',
     '                                  where="")\n'),
    ("a button posted for one build of the preview records another", STAGING,
     '    if entry.get("head"):\n',
     "    if False:\n"),

    # ── the card on the product view ─────────────────────────────────────────────────────────
    ("the card view never asks whether a yes is offered", CATALOG,
     '        if callable(getattr(module, "accept_view", None)):\n',
     "        if False:\n"),
    ("an operator on the product view is refused the yes", CATALOG,
     "    vouched = bool(by.admin) and by.may_enter(FLOOR)\n"
     '    # WHERE "IT WENT IN" IS TOLD',
     "    vouched = False\n"
     '    # WHERE "IT WENT IN" IS TOLD'),
    ("the product card draws no yes", PANEL,
     '${where === "product" ? pvAcceptBlock(c) + pvAdjustBlock(c) : ""}',
     '${where === "product" ? pvAdjustBlock(c) : ""}'),
    ("the page draws the yes whatever the server says", PANEL,
     '  if(!a.offered)return a.note?`<p class="pv-note" data-accept>',
     '  if(false)return a.note?`<p class="pv-note" data-accept>'),
    ("the click does not carry the head the card showed", PANEL,
     "    {project:_prod.project,number:c.ref,head:(c.accept||{}).head||\"\"}",
     "    {project:_prod.project,number:c.ref}"),

    # ── the person merging sees it ───────────────────────────────────────────────────────────
    ("the inbox never reads the acceptances", APP,
     "    await _stamp_the_acceptances(jobs)\n    for j in jobs:\n",
     "    for j in jobs:\n"),
    ("the inbox item drops the acceptance", APP,
     '                        **({"accepted": j["accepted"]} if j.get("accepted") else {}),\n',
     ""),
    ("the inbox's line leaves it out", PANEL,
     "    (it.accepted&&it.accepted.said?",
     "    (false?"),
    ("the floor bar draws nothing beside the gate's answers", PANEL,
     "        gateAcceptedLine(parked)+\n",
     ""),
    ("a stale yes is drawn as a current one", PANEL,
     'class="badge ${a.current===false?"b-warn":"b-ok"}"',
     'class="badge ${"b-ok"}"'),
    ("the tech-lead is never told", TECHLEAD,
     '        if isinstance(accepted, dict) and str(accepted.get("said") or "").strip():\n',
     "        if False:\n"),

    # ── the requester hears it went in ───────────────────────────────────────────────────────
    # re-pinned 2026-10-05: #448 slice 6 — the telling is the door's `went_in` now
    ("with no stage the requester hears it twice", EVENTS,
     "    if not stages_follow and _the_delivery_says_it(project, card, rows):\n",
     "    if False:\n"),
    ("a delivery waiting on other cards reads as complete", EVENTS,
     "    loops = _deliveries_of(rows, card)\n    if not loops:\n        return False\n",
     "    loops = _deliveries_of(rows, card)\n    if loops:\n        return True\n"),
    # re-pinned 2026-10-05: #448 slice 6 — the telling is the door's `went_in` now
    ("a card with no delivery is told nowhere", EVENTS,
     "    where = requester_conversation(project, card, rows=rows) or _accepted_where(\n"
     "        project, card, pr_url)\n",
     "    where = requester_conversation(project, card, rows=rows)\n"),
    # re-pinned 2026-10-05: #448 slice 6 — the telling is the door's `went_in` now
    ("it is told again on every merge of the same pull request", EVENTS,
     "    said = _event_id(MERGED, project, card, pr_url)\n",
     "    said = _event_id(MERGED, project, card, pr_url, str(time.time()))\n"),
    ("a project with stages hears nothing of them", "openfactory/product/voice.py",
     "    if stages_follow:\n        said += _pick(_MERGED_STAGES, language)\n",
     ""),
]
