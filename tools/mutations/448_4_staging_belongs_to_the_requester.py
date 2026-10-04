"""What is ready to try before it reaches anyone is the requester's to try, and their answer is read
where they are (#448, slice 4 — the first part).

The claims, each cut below and each required to go red:

  · the parked job says which run it is in, and the round hands that run to the telling;
  · the requester is told in their own conversation, once per run and again for a new run — where
    the card's delivery recorded it, else where they accepted the change, and never in the room;
  · their copy of the question opens beside the room's, only when they were told, as a row of its
    own that lives in their conversation and carries a digest of who they are;
  · their answer there reaches their copy, one release asked twice is one question and a name for
    it is a name, while another release waiting is still a choice, listed once each;
  · a verdict that counts closes every copy of its release, and no other release;
  · the round asks nothing again while either copy is open, and a post that did not land opens
    nothing;
  · and the sentence they read is the project's language, with no address when none is known.

And the rest of slice 4 — who releases, and what "not yet" does at the last gate:

  · the requester's "it worked" releases only where the project says so (`release_by_requester`,
    off by default) and is never a stranger's or a guest's; where it does not, it is RECORDED —
    their copies close as `worked`, the room's stays open — and the room is told once per run, by
    name when the people store knows one and never by id, and they hear whether the room knows;
  · the release's record says whose yes it was: theirs, an admin's after theirs to THIS asking,
    or an admin's;
  · a "not yet" names the card for another pass only when it named one release; an ambiguous one
    closes nothing and asks which;
  · the turn stages another pass drafted from the conversation, worded and drafted for a change
    already in; the gate a person sends back from includes the last gate, with its refusals, and a
    preview's acceptance does not; the yes delivers the last gate's own answer, sealed as its own
    kind, through a seam that refuses a job not there, a deaf one and a spent budget;
  · the job wakes on a sealed "not yet" at the gate only, counts it on the one budget, and with a
    pass left continues as a new change — the words in its run, the next change number, the
    passes carried, no sizing again, said by the tech-lead — and publishes what is left, what
    happens when nothing is, a refusal, and whether it hears at all;
  · each change has its own branch, every runner of the job (run, adjust, repair, re-review,
    remote box) is built for it, and the words reach the agent's brief;
  · and each change's deploy has its own watch (the review of #503): a later change's id carries
    its number, so it runs beside the first change's watch rather than being refused by it; the
    first change's id is the one it always had and records no marker; a later change whose history
    predates the marker keeps the id it had; and a watch not started says whether it was already
    running or the engine refused it.
"""

TEST = "tests/test_staging_belongs_to_the_requester.py"
#: the rest of slice 4's "not yet" — the conversation, the seam, the job and the runner
NOT_YET = "tests/test_not_yet_at_the_last_gate_is_another_pass.py"
STAGED_PASS = (NOT_YET + "::test_the_requesters_not_yet_stages_another_pass_as_a_new_change_and_"
               "promises_nothing")
SENT_PASS = NOT_YET + "::test_their_yes_corrects_the_bar_then_sends_the_merged_change_back_sealed"
NO_PASS = NOT_YET + "::test_where_no_pass_can_be_sent_the_reply_says_why_and_nothing_is_drafted"
READ_GATE = NOT_YET + "::test_the_last_gate_is_read_with_the_merge_gates_refusals"
SEAM = NOT_YET + "::test_the_seam_refuses_what_the_job_would_refuse_before_any_signal"
SEALED = NOT_YET + "::test_the_seam_seals_the_not_yet_for_this_job_alone"
PARKED = NOT_YET + "::test_the_last_gate_is_read_only_of_a_running_job_parked_there"
NEW_CHANGE = NOT_YET + "::test_a_sealed_not_yet_continues_the_job_as_a_new_change_from_the_base"
UNSEALED = NOT_YET + "::test_a_not_yet_without_the_seal_is_dropped_and_the_gate_waits_on"
SPENT = NOT_YET + "::test_past_the_budget_the_job_stays_at_the_last_gate_and_says_a_person_decides"
EARLY = NOT_YET + "::test_a_not_yet_sent_before_the_job_reaches_its_gate_is_dropped"
DEAF = NOT_YET + "::test_a_run_parked_before_it_could_hear_is_deaf_says_so_and_replays"
WORKER = NOT_YET + "::test_the_run_the_adjust_and_the_re_review_are_built_for_the_same_change"
REMOTE = NOT_YET + "::test_a_remote_box_is_told_which_change_and_what_is_still_wrong"
INPUTS = NOT_YET + "::test_every_input_for_the_cards_pull_request_says_which_change_it_is"
WATCHED = NOT_YET + "::test_a_later_change_watches_its_own_deploy_while_the_first_is_still_watched"
OLD_WATCH = (NOT_YET + "::test_a_later_change_from_before_its_own_watch_keeps_the_id_it_had_and_"
             "replays")
NOT_STARTED = (NOT_YET + "::test_a_watch_not_started_says_whether_it_runs_already_or_the_engine_"
               "refused")
RELEASE = "openfactory/product/release.py"
EVENTS = "openfactory/product/events.py"
FOLLOWUP = "openfactory/product/followup.py"
ACTIVITIES = "openfactory/runtime/temporal/activities.py"
ENGINE = "openfactory/product/engine.py"
MODULE = "openfactory/product/module.py"
VOICE = "openfactory/product/voice.py"
PROJECT = "openfactory/contracts/project.py"
ADJUST = "openfactory/product/adjust.py"
VIEW = "openfactory/runtime/temporal/view.py"
WORKFLOW = "openfactory/runtime/temporal/workflow.py"
NAMESPACE = "openfactory/namespace.py"
MACHINE = "openfactory/orchestrator/machine.py"
BRIEF = "openfactory/adapters/agent/base.py"
BOXED = "openfactory/runtime/boxed_job.py"

MUTATIONS = [
    # ── the run ──────────────────────────────────────────────────────────────────────────────
    ("the parked job never says which run it is in", RELEASE,
     '            out.append((issue, where, str(getattr(wf, "run_id", "") or "")))\n',
     '            out.append((issue, where, ""))\n'),
    ("the round tells every run of a card as one", ACTIVITIES,
     "        if await asyncio.to_thread(events.staged_for_you, project, card=str(issue), "
     "where=where,\n"
     "                                   run=run):\n",
     "        if await asyncio.to_thread(events.staged_for_you, project, card=str(issue), "
     "where=where,\n"
     '                                   run=""):\n'),

    # ── the requester is told, where they asked, once per run ────────────────────────────────
    ("the round never tells the requester", ACTIVITIES,
     "        if await asyncio.to_thread(events.staged_for_you, project, card=str(issue), "
     "where=where,\n"
     "                                   run=run):\n",
     "        if False:\n"),
    # re-pinned 2026-10-05: #448 slice 6 — the telling is the door's `to_try_at_the_stage` now
    ("a new run of the card is never told again", EVENTS,
     "    said = _event_id(STAGED, project, card, run)\n",
     "    said = _event_id(STAGED, project, card)\n"),
    # re-pinned 2026-10-05: #448 slice 6 — the telling is the door's `to_try_at_the_stage` now
    ("it is told again every hour of the same run", EVENTS,
     "    said = _event_id(STAGED, project, card, run)\n",
     "    said = _event_id(STAGED, project, card, run, str(time.time()))\n"),
    # re-pinned 2026-10-05: #448 slice 6 — the telling is the door's `to_try_at_the_stage` now
    ("a card nobody asked for in a conversation is told to nobody's conversation", EVENTS,
     "    if not to:\n        return \"nobody to tell: nobody asked for it in a conversation\"\n",
     ""),
    # re-pinned 2026-10-05: #448 slice 6 — the telling is the door's `to_try_at_the_stage` now
    ("a requester who asked in the room is told twice there", EVENTS,
     "    if to == room_of(project):\n"
     "        return \"nobody to tell: they asked in the room, which was asked\"\n",
     ""),
    ("a card with no delivery is told nowhere", EVENTS,
     "        if acc is not None and acc.where:\n            return acc.where, sealed(acc.by)\n",
     ""),
    ("the person who accepted it is kept as a name", EVENTS,
     "            return acc.where, sealed(acc.by)\n",
     "            return acc.where, acc.by\n"),

    # ── their copy of the question ───────────────────────────────────────────────────────────
    ("no copy of theirs is opened when they were told", ACTIVITIES,
     "            if theirs:\n                opened.append(followup.release_of(",
     "            if False:\n                opened.append(followup.release_of("),
    ("their copy is opened though the telling never reached them", ACTIVITIES,
     "        if await asyncio.to_thread(events.staged_for_you, project, card=str(issue), "
     "where=where,\n"
     "                                   run=run):\n",
     "        if [await asyncio.to_thread(events.staged_for_you, project, card=str(issue), "
     "where=where,\n"
     "                                    run=run)]:\n"),
    ("their copy and the room's are one row of the ledger", FOLLOWUP,
     "                     about=where_asked or channel,\n",
     "                     about=channel,\n"),
    ("their copy lives in the room", FOLLOWUP,
     '                              **({"conversation": where_asked} if where_asked else {}),\n',
     ""),
    ("their copy does not say whose it is", FOLLOWUP,
     # re-pinned 2026-10-04: the run rides beside it (#448 slice 4)
     '                              **({"requester": str(requester)}\n'
     '                                 if where_asked and str(requester or "").strip() else {}),\n',
     ""),

    # ── their answer reaches it ──────────────────────────────────────────────────────────────
    ("the copy asked where they wrote is not the one settled", MODULE,
     "        loop = next((x for x in open_acc if _question_of(x) == _question_of(loop)\n"
     '                     and here and str((x.context or {}).get("conversation") or "") == here), '
     "loop)\n",
     ""),
    ("one release asked in two places is read as two", MODULE,
     "        ambiguous = named is None and len({_question_of(x) for x in open_acc}) > 1\n",
     "        ambiguous = named is None and len(open_acc) > 1\n"),
    ("naming a release with two copies is read as a guess", MODULE,
     "    return candidates[0] if len({_question_of(x) for x in candidates}) == 1 else None\n",
     "    return candidates[0] if len(candidates) == 1 else None\n"),
    ("another release waiting is not a choice", MODULE,
     '    return ("release", canonical_ref(issue).upper()) if issue else loop.key\n',
     '    return "release" if issue else loop.key\n'),
    ("the releases to choose from are listed once per copy", ENGINE,
     "        return list(dict.fromkeys(is_release(x) for x in sorted(loops, "
     "key=lambda x: x.ts)))\n",
     "        return [is_release(x) for x in sorted(loops, key=lambda x: x.ts)]\n"),

    # ── a verdict closes every copy, of its own release only ─────────────────────────────────
    ("a verdict closes only the copy it landed on", ENGINE,
     "        observed = {(ACCEPTANCE, x.subject, x.about): verdict\n"
     "                    for x in waiting(ledger, owner=OWNER)\n"
     "                    if issue and x.kind == ACCEPTANCE and is_release(x) == issue}\n",
     "        observed = {}\n"),
    ("a verdict closes every release waiting", ENGINE,
     "                    if issue and x.kind == ACCEPTANCE and is_release(x) == issue}\n",
     "                    if issue and x.kind == ACCEPTANCE and is_release(x)}\n"),

    # ── the round asks once, and only what landed ────────────────────────────────────────────
    ("the room is asked again while only their copy is open", ACTIVITIES,
     "    asked = {followup.is_release(x) for x in open_now}\n",
     '    asked = {followup.is_release(x) for x in open_now\n'
     '             if not (x.context or {}).get("conversation")}\n'),
    ("they are asked again while only the room's copy is open", ACTIVITIES,
     "    asked = {followup.is_release(x) for x in open_now}\n",
     '    asked = {followup.is_release(x) for x in open_now\n'
     '             if (x.context or {}).get("conversation")}\n'),
    ("a room post that did not land still opens the question", ACTIVITIES,
     "        if not await asyncio.to_thread(_product_post, channel, project, cfg, text):\n"
     "            continue\n"
     "        room = channel_destination(project, product=True)\n"
     "        ts = _now_iso()\n",
     "        await asyncio.to_thread(_product_post, channel, project, cfg, text)\n"
     "        room = channel_destination(project, product=True)\n"
     "        ts = _now_iso()\n"),

    # ── in their words, and a known kind ─────────────────────────────────────────────────────
    ("an unknown address is written as if there were one", VOICE,
     "    middle = (_pick(_STAGED_TRY, language).format(where=where) if where\n"
     "              else _pick(_STAGED_NOWHERE, language))\n",
     "    middle = _pick(_STAGED_TRY, language).format(where=where)\n"),
    ("the event is not a kind the module knows", EVENTS,
     # re-pinned 2026-10-04: `tried` joined it (#448 slice 4)
     "         READY_FOR_YOU, MERGED, STAGED, TRIED)\n",
     "         READY_FOR_YOU, MERGED, TRIED)\n"),
    # ── who puts it in front of everyone (slice 4, the rest) ─────────────────────────────────
    ("the requester's yes never releases, even where the project lets it", ENGINE,
     '    if not admin and not (theirs and getattr(project, "release_by_requester", False) '
     'is True):\n',
     "    if not admin and not (theirs and False):\n"),
    ("the requester's yes is refused like a stranger's where it does not release", ENGINE,
     "        if theirs:\n            # THEIR YES IS RECORDED",
     "        if False:\n            # THEIR YES IS RECORDED"),
    ("anybody who answers is taken for the card's requester", ENGINE,
     "    theirs = not admin and _asked_for(module, issue, user)\n",
     "    theirs = not admin\n"),
    ("their yes closes the room's question too", ENGINE,
     '    _close_release(project, loop, "worked", only_theirs=True)\n',
     '    _close_release(project, loop, "worked")\n'),
    ("their yes is not recorded", ENGINE,
     '    _close_release(project, loop, "worked", only_theirs=True)\n',
     ""),
    ("the room is never told they said it is right", ENGINE,
     "    told = events.tried_and_right(project, card=issue,\n",
     "    told = False and events.tried_and_right(project, card=issue,\n"),
    ("the room is told again for every yes of the same run", EVENTS,
     "    event = _event_id(TRIED, project, card, run)\n",
     "    event = _event_id(TRIED, project, card, run, str(time.time()))\n"),
    ("a later run is never told", EVENTS,
     "    event = _event_id(TRIED, project, card, run)\n",
     "    event = _event_id(TRIED, project, card)\n"),
    # re-pinned 2026-10-05: #448 slice 6 — the telling is the door's `tried_it_right` now
    ("a room told already is said not to know", EVENTS,
     '            if event in _read(path)["told"]:\n',
     "            if False:\n"),
    ("the run is not recorded on the question", FOLLOWUP,
     '                              **({"run": str(run)} if str(run or "").strip() else {})})',
     "                              })"),
    ("the room's line names an address where none is known", VOICE,
     '        at=_pick(_TRIED_AT, language).format(where=where) if where else "")',
     "        at=_pick(_TRIED_AT, language).format(where=where))"),
    ("the requester is never named", ENGINE,
     '    return display if display and display != str(user) else ""\n',
     '    return ""\n'),
    ("an id is said as a name", ENGINE,
     '    return display if display and display != str(user) else ""\n',
     "    return display\n"),
    ("an admin's release after their yes does not say so", ENGINE,
     '            else "released_after_the_requester" if '
     '_the_requester_said_right(project, loop)\n',
     '            else "released_after_the_requester" if False\n'),
    ("an admin's release says the requester said so of an asking they never answered", ENGINE,
     "and is_release(x) == issue and x.ts == loop.ts\n",
     "and is_release(x) == issue\n"),
    ("a requester's release is recorded as a client's", ENGINE,
     '    said = ("released_by_requester" if not admin\n',
     '    said = ("released_by_client" if not admin\n'),
    ("a not-yet that could be either of two closes the newest", ENGINE,
     '        if ambiguous:\n            # NOR IS A "NOT YET" GUESSED',
     '        if False:\n            # NOR IS A "NOT YET" GUESSED'),
    ("a yes asks for another pass too", ENGINE,
     '                               if verdict != "worked" and not ambiguous else "")',
     '                               if not ambiguous else "")'),
    ("the requester's word releases by default", PROJECT,
     "    release_by_requester: bool = False\n",
     "    release_by_requester: bool = True\n"),
    ("the requester's yes is not a kind the module knows", EVENTS,
     "         READY_FOR_YOU, MERGED, STAGED, TRIED)\n",
     "         READY_FOR_YOU, MERGED, STAGED)\n"),

    # ── "not yet" is another pass: the conversation ──────────────────────────────────────────
    ("a not-yet at the last gate is answered with a promise again", ENGINE,
     "    if settled.not_yet:\n",
     "    if False:\n", STAGED_PASS),
    ("the pass is drafted from the message alone", ENGINE,
     '    prepared = prepare(number, actor=ex.user, conversation=said, reply="", '
     'request=ex.text,\n',
     '    prepared = prepare(number, actor=ex.user, conversation="", reply="", '
     'request=ex.text,\n',
     STAGED_PASS),
    ("the proposal is worded as a pass on the same change", ENGINE,
     '                              language=ex.lang, merged=bool(getattr(gate, "merged", False)))',
     "                              language=ex.lang, merged=False)", STAGED_PASS),
    ("the draft is asked for the same pull request", MODULE,
     "                               request=request, reply=reply, language=lang,\n"
     "                               merged=gate.merged)\n",
     "                               request=request, reply=reply, language=lang,\n"
     "                               merged=False)\n", STAGED_PASS),
    ("the conversation asks only the merge gate", MODULE,
     "        # product's users, is sent back too — as a new change (`Gate.merged`)\n"
     "        gate = adjust.pass_gate_of(self.project, number)\n",
     "        # product's users, is sent back too — as a new change (`Gate.merged`)\n"
     "        gate = adjust.gate_of(self.project, number)\n", STAGED_PASS),
    ("the card view never offers the pass at the last gate", MODULE,
     "        gate = adjust.pass_gate_of(self.project, number)       # the last gate too",
     "        gate = adjust.gate_of(self.project, number)       # the last gate too",
     NOT_YET + "::test_the_card_offers_the_pass_at_the_last_gate_too"),

    # ── the gate a person sends back from ────────────────────────────────────────────────────
    ("the last gate is never read", ADJUST,
     "        if not gate and last:\n",
     "        if False:\n", STAGED_PASS),
    ("a preview's acceptance is taken at the last gate", ADJUST,
     "    return _gate(project, card, last=False)\n",
     "    return _gate(project, card, last=True)\n",
     NOT_YET + "::test_a_that_s_it_at_the_last_gate_is_not_a_preview_acceptance"),
    ("a deaf last gate reads as one that hears", ADJUST,
     '    if gate.get("hears") is not True:\n        return Gate(why=DEAF, **said)\n',
     "    if False:\n        return Gate(why=DEAF, **said)\n", READ_GATE),
    ("a spent budget at the last gate reads as open", ADJUST,
     '    if gate.get("hears") is not True:\n        return Gate(why=DEAF, **said)\n'
     "    if left == 0:\n",
     '    if gate.get("hears") is not True:\n        return Gate(why=DEAF, **said)\n'
     "    if left == -1:\n", READ_GATE),
    ("no job at the last gate reads as an engine that could not be asked", ADJUST,
     "    if not gate:\n        return Gate(card=card, why=NOT_WAITING)\n"
     '    passes, left = _count(gate.get("adjust_passes")), _count(gate.get("adjusts_left"))\n'
     "    said = dict(card=card, passes=passes, left=left, merged=True)\n",
     '    passes, left = _count(gate.get("adjust_passes")), _count(gate.get("adjusts_left"))\n'
     "    said = dict(card=card, passes=passes, left=left, merged=True)\n", NO_PASS),

    # ── the yes delivers the last gate's own answer ──────────────────────────────────────────
    ("the last gate's pass is sent as a merge-gate adjust", ADJUST,
     "    if merged:\n        return _not_yet(project, card, instruction=instruction, by=by)\n",
     "", SENT_PASS),
    ("the module sends a merged change back as a pass on its pull request", MODULE,
     "        why = adjust.send_back(self.project, number, instruction=said, by=actor,\n"
     "                               merged=gate.merged)\n",
     "        why = adjust.send_back(self.project, number, instruction=said, by=actor,\n"
     "                               merged=False)\n", SENT_PASS),
    ("the person is told the pass works on the same change", MODULE,
     "                           passes=gate.passes, merged=gate.merged,",
     "                           passes=gate.passes, merged=False,", SENT_PASS),
    ("the seam signals a job not at its last gate", VIEW,
     "    if not await handle.query(JobWorkflow.awaiting_approval):\n"
     '        raise RuntimeError("this job is not waiting at its last gate")\n',
     "", SEAM),
    ("the seam signals a deaf job", VIEW,
     '    if gate.get("hears") is not True:\n        raise GateDeaf(',
     "    if False:\n        raise GateDeaf(", SEAM),
    ("the seam sends a pass past the budget", VIEW,
     '    if gate.get("adjusts_left") == 0:\n'
     '        raise AdjustsSpent(int(gate.get("adjust_passes") or 0))\n'
     "    seal = gate_seal.seal(gate_seal.NOT_YET",
     "    seal = gate_seal.seal(gate_seal.NOT_YET", SEAM),
    ("a not-yet is sealed as a release approval", VIEW,
     "    seal = gate_seal.seal(gate_seal.NOT_YET, wf_id, instruction, by)\n",
     "    seal = gate_seal.seal(gate_seal.APPROVE_PROD, wf_id, instruction, by)\n", SEALED),
    ("a finished job is read as parked at its last gate", VIEW,
     "    if described.status != WorkflowExecutionStatus.RUNNING:\n        return None\n"
     "    if not await handle.query(JobWorkflow.awaiting_approval):\n        return None\n",
     "    if not await handle.query(JobWorkflow.awaiting_approval):\n        return None\n",
     PARKED),
    ("a job at no gate is read as one at the last", VIEW,
     "    if not await handle.query(JobWorkflow.awaiting_approval):\n        return None\n"
     "    return dict(",
     "    return dict(", PARKED),

    # ── the job leaves the gate for a new change ─────────────────────────────────────────────
    ("the last gate never wakes for a not-yet", WORKFLOW,
     "                    lambda: self._approval is not None or self._not_yet is not None,\n",
     "                    lambda: self._approval is not None,\n", NEW_CHANGE),
    ("a not-yet that arrives before the gate fires when it opens", WORKFLOW,
     "        if not (self._awaiting_approval and self._hears_not_yet):\n            return\n"
     "        self._not_yet = ",
     "        self._not_yet = ", EARLY),
    ("an unsealed not-yet sends the change back", WORKFLOW,
     '                    if await self._gate_sealed(\n                            "not_yet",',
     '                    if True or await self._gate_sealed(\n'
     '                            "not_yet",',
     UNSEALED),
    ("a not-yet past the budget sends the change back", WORKFLOW,
     "                        if self._adjust_passes < params.adjust_passes:\n"
     "                            another = asked\n",
     "                        if True:\n                            another = asked\n", SPENT),
    ("the job never leaves the gate for the new change", WORKFLOW,
     "        if another is not None:\n            await self._another_change(params, another)",
     "        if False:\n            await self._another_change(params, another)", NEW_CHANGE),
    ("the pass is not counted", WORKFLOW,
     "        self._adjust_passes += 1\n        await self._coord_say(\n"
     '            tl_voice.say(tl_voice.NARRATION, "prod.another-change"',
     "        await self._coord_say(\n"
     '            tl_voice.say(tl_voice.NARRATION, "prod.another-change"', NEW_CHANGE),
    ("the budget starts again on the new change", WORKFLOW,
     "        self._adjust_passes = params.passes_spent\n",
     "", NEW_CHANGE),
    ("the passes spent are not carried", WORKFLOW,
     '            "passes_spent": self._adjust_passes,\n',
     "", NEW_CHANGE),
    ("the words never reach the new change", WORKFLOW,
     '            "another_pass": str(asked.get("instruction") or "")'
     '[:_ADJUST_CHARS],\n',
     "", NEW_CHANGE),
    ("the new change works on the merged change's number", WORKFLOW,
     '            "change": params.change + 1}))',
     '            "change": params.change}))', NEW_CHANGE),
    ("the run never hands the words to the agent", WORKFLOW,
     "                another_pass=params.another_pass,\n                change=params.change,\n",
     "                change=params.change,\n", NEW_CHANGE),
    ("the run builds every change as the first", WORKFLOW,
     "                another_pass=params.another_pass,\n                change=params.change,\n",
     "                another_pass=params.another_pass,\n", NEW_CHANGE),
    ("a merged card is sized again", WORKFLOW,
     "        pre_pending = not params.another_pass\n",
     "        pre_pending = True\n", NEW_CHANGE),
    ("the tech-lead says nothing of the new change", WORKFLOW,
     "        await self._coord_say(\n"
     '            tl_voice.say(tl_voice.NARRATION, "prod.another-change"',
     "        await (lambda *a: asyncio.sleep(0))(\n"
     '            tl_voice.say(tl_voice.NARRATION, "prod.another-change"', NEW_CHANGE),
    ("the last gate publishes the whole budget whatever was spent", WORKFLOW,
     "        left = max(0, params.adjust_passes - self._adjust_passes)\n",
     "        left = params.adjust_passes\n", NEW_CHANGE),
    ("a spent last gate says nothing of what happens next", WORKFLOW,
     "        if self._hears_not_yet and not left:\n"
     '            wait["note"] = release_passes_spent_note(params.adjust_passes)\n',
     "", SPENT),
    ("a refused not-yet is not said on the gate", WORKFLOW,
     '        if self._gate_refused and wait.get("hears"):\n'
     '            wait["refused"] = self._gate_refused\n',
     "", UNSEALED),
    ("a run parked before it could hear says it hears", WORKFLOW,
     "        self._hears_not_yet = workflow.patched(_NOT_YET_AT_THE_LAST_GATE)\n",
     "        self._hears_not_yet = True\n", DEAF),

    # ── each change has its own branch, and every runner of the job knows which ─────────────
    ("a later change is pushed over the first change's branch", NAMESPACE,
     '    return f"{BRANCH_PREFIX}/{bare}-{change + 1}" if change > 0 else '
     'f"{BRANCH_PREFIX}/{bare}"',
     '    return f"{BRANCH_PREFIX}/{bare}"', NOT_YET),
    ("the runner names every change's branch as the first's", MACHINE,
     "        return namespace.job_branch(ticket.id, change=self.change)",
     "        return namespace.job_branch(ticket.id)", NOT_YET),
    ("the words never reach the agent's context", MACHINE,
     "            ctx.another_pass = self._another_pass  # what the last change still got wrong "
     "(#448)\n",
     "", NOT_YET + "::test_the_new_change_is_built_from_the_base_and_never_pushed_over_the_merged"
         "_one"),
    ("the brief drops the words", BRIEF,
     "    if context.another_pass:\n        # A NEW CHANGE",
     "    if False:\n        # A NEW CHANGE",
     NOT_YET + "::test_the_brief_carries_the_words_fenced_beside_the_card"),
    ("the run is built for the first change", ACTIVITIES,
     "image=inp.image, review=inp.review,\n        repo_key=repo_key, change=inp.change,\n",
     "image=inp.image, review=inp.review,\n        repo_key=repo_key,\n", WORKER),
    ("the run's words never reach the runner", ACTIVITIES,
     "                        another_pass=inp.another_pass)  # #448 slice 4: the card's next "
     "change",
     "                        )  # #448 slice 4: the card's next change", WORKER),
    ("an adjust on a later change repairs the first change's branch", ACTIVITIES,
     "                           sandbox=inp.sandbox, attempt=inp.attempt, change=inp.change)",
     "                           sandbox=inp.sandbox, attempt=inp.attempt)", WORKER),
    ("a re-review reads the first change's branch", ACTIVITIES,
     "            image=_resolved_image(project, sandbox=inp.sandbox), review=True,\n"
     "            repo_key=repo_key, change=inp.change,\n",
     "            image=_resolved_image(project, sandbox=inp.sandbox), review=True,\n"
     "            repo_key=repo_key,\n", WORKER),
    ("a repair builds for the first change's branch", ACTIVITIES,
     "            image=_resolved_image(project, sandbox=inp.sandbox), review=False,\n"
     "            repo_key=repo_key, change=inp.change,\n",
     "            image=_resolved_image(project, sandbox=inp.sandbox), review=False,\n"
     "            repo_key=repo_key,\n", WORKER),
    ("a remote box is never told which change", ACTIVITIES,
     '    if change:\n        out["OPENFACTORY_CHANGE"] = str(change)\n',
     "", REMOTE),
    ("a remote box never reads what is still wrong", BOXED,
     '        another_pass=env.get("OPENFACTORY_ANOTHER_PASS") or "",\n',
     "", REMOTE),
    ("a remote box builds on the first branch", BOXED,
     '        change=_a_count(env.get("OPENFACTORY_CHANGE")),\n',
     "", REMOTE),
    ("a remote box hands its runner no change number", BOXED,
     '    return {"change": change} if change else {}\n',
     "    return {}\n", REMOTE),
    ("a CI repair on a later change is asked for the first change's branch", WORKFLOW,
     "                        change=params.change,  # #448 slice 4: the branch of this change\n",
     "", INPUTS),
    ("a re-review on a later change is asked for the first change's branch", WORKFLOW,
     "                                sandbox=params.sandbox, attempt=self._review_passes,\n"
     "                                change=params.change),",
     "                                sandbox=params.sandbox, attempt=self._review_passes),",
     INPUTS),
    ("an adjust on a later change is asked for the first change's branch", WORKFLOW,
     '                        source=REVIEW_THREAD if threads else "", by=who,\n'
     "                        change=params.change),",
     '                        source=REVIEW_THREAD if threads else "", by=who),', INPUTS),

    # ── each change's deploy has its own watch (the review of #503) ──────────────────────────
    ("a later change's deploy watch takes the first change's id", WORKFLOW,
     '            watch_id = f"{watch_id}-{params.change + 1}"\n',
     "            pass\n", WATCHED),
    ("a first change's deploy watch moves to a new id", WORKFLOW,
     '        watch_id = f"openfactory-deploy-{params.project}-{params.issue}"\n',
     '        watch_id = f"openfactory-deploy-{params.project}-{params.issue}-1"\n', WATCHED),
    ("a first change's deploy watch records the marker", WORKFLOW,
     "        if params.change and workflow.patched(_A_LATER_CHANGE_WATCHES_ITS_OWN_DEPLOY):\n",
     "        if workflow.patched(_A_LATER_CHANGE_WATCHES_ITS_OWN_DEPLOY) and params.change:\n",
     WATCHED),
    ("a later change's deploy watch changes its id without a marker", WORKFLOW,
     "        if params.change and workflow.patched(_A_LATER_CHANGE_WATCHES_ITS_OWN_DEPLOY):\n",
     "        if params.change:\n", OLD_WATCH),
    ("the engine refusing a deploy watch reads as a re-run", WORKFLOW,
     "        except WorkflowAlreadyStartedError:\n",
     "        except Exception:\n", NOT_STARTED),
    ("a deploy watch already running reads as the engine refusing", WORKFLOW,
     "        except WorkflowAlreadyStartedError:\n",
     "        except ZeroDivisionError:\n", NOT_STARTED),
]
