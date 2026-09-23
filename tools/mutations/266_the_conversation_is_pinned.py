"""#266 slice 1: the conversation, pinned flow by flow — every flow's own line, cut, must go red.

The suite is the specification slice 2 extracts the turn engine against, so a flow it cannot see
is a flow the extraction may lose without anybody noticing. One row per flow at least, each
cutting the line in `product/channel.py` (or in the module it hands the act to) that the flow
stands on.

Some rows cut in the OTHER direction: they apply the change a test says is today's behaviour on
purpose — the requester-bound yes and the scoped decision close of slice 4, and the two defects
pinned as found (a typed no recorded as an approval, a refused release that closes its loop).
Those rows prove the pins are pins: the day the change lands, it lands red, as a decision.

THE FIRST RUN WAS 61/62 (2026-09-24). "the receipt waits for the authorisation" survived: the
test compared the LAST receipt with the one a "sim" seeds, and the receipts are a small catalogue
picked by the message — the request before it picks the same line, so the comparison held with the
refused yes's receipt gone. The test counts one receipt per message now, and the row is red.
"""

TEST = "tests/test_the_conversation_is_pinned.py"
CH = "openfactory/product/channel.py"
CONFIRM = "openfactory/product/confirm.py"
STAGING = "openfactory/product/staging.py"
MODULE = "openfactory/product/module.py"

MUTATIONS = [
    # ── 1. a question ────────────────────────────────────────────────────────────────────────────
    ("the agent's turn is never recorded — her memory loses what she said", CH,
     '            transcript.record(name, thread=thread, role="agent", text=str(reply), '
     'channel=channel)',
     "            pass"),

    ("the person's turn is recorded without who said it", CH,
     'role="person", text=text, actor=user,',
     'role="person", text=text, actor="",'),

    ("the receipt goes silent before the model", CH,
     "    _on_it()\n\n    from openfactory.memory import transcript\n",
     "\n    from openfactory.memory import transcript\n"),

    ("a question is answered with nothing", CH,
     "    return answer.text\n\n\ndef offer_draft(",
     "    return None\n\n\ndef offer_draft("),

    # ── 2. a request becomes a draft, staged, with the question ──────────────────────────────────
    ("a request is answered and never drafted", CH,
     "    if answer.is_request:", "    if False:"),

    ("the draft is staged where no yes will look for it", CH,
     'replaced = remember(thread, {"answer": answer,',
     'replaced = remember(thread + "-elsewhere", {"answer": answer,'),

    ("the draft forgets who asked for it", CH,
     '                              asked_by=f"<@{user}>" if user else "", source=source or "")',
     '                              asked_by="", source=source or "")'),

    ("the role's answer is dropped from in front of the draft", CH,
     '                              preamble=f"{answer.text}\\n\\n" if answer.text else "",',
     '                              preamble="",'),

    ("the buttons are offered without the typed way to answer", CH,
     'posted = confirm(f"{text}\\n\\n{or_just_reply(language=lang)}",',
     'posted = confirm(f"{text}",'),

    ("a proposal posted with its buttons is shown again as prose", CH,
     "    return Posted(text) if posted else text", "    return text"),

    # ── 3. a yes confirms the staged proposal, once ──────────────────────────────────────────────
    ("a typed yes on a staged proposal is not performed", CH,
     "    if waiting and (is_yes(text) or judged_yes):", "    if False:"),

    ("the performed proposal is not consumed — a second yes writes it again", CONFIRM,
     "    performed = consume(key, entry, fingerprint=fingerprint, project=project, by=user,\n"
     "                        approved=True)",
     "    performed = entry"),

    ("the judge's approval of a sentence is ignored", CH,
     '        judged_yes = verdict == "approve"', "        judged_yes = False"),

    ("the judge's rejection of a sentence is ignored", CH,
     '        judged_no = verdict == "reject"', "        judged_no = False"),

    # ── 4. a no rejects it ───────────────────────────────────────────────────────────────────────
    ("a no leaves the proposal staged", CH,
     "        consume(waiting_key, waiting, fingerprint=fingerprint, project=project, by=user,\n"
     "                approved=True)",
     "        pass"),

    ("the discarded proposal stays in the prompt as still pending", CH,
     "        waiting_key, waiting = None, None", "        pass"),

    ("the requester may not take their own proposal back", CH,
     "        if not may_act(project, user, via=via) and not _is_requester(waiting, user):",
     "        if not may_act(project, user, via=via):"),

    ("anybody may destroy a proposal", CH,
     "        if not may_act(project, user, via=via) and not _is_requester(waiting, user):",
     "        if False:"),

    ("…and the reverse: a typed no is recorded durably as a rejection (pinned as found)", CH,
     "                approved=True)\n        # the discarded proposal",
     "                approved=False)\n        # the discarded proposal"),

    # ── 5. a yes from someone who may not write ──────────────────────────────────────────────────
    ("a yes from someone off the admin list performs the write", CONFIRM,
     "    if not may_act(project, user, via=via):\n"
     "        return unauthorized_message(project)\n\n"
     "    from openfactory.product.staging import consume\n",
     "    from openfactory.product.staging import consume\n"),

    ("the receipt waits for the authorisation", CONFIRM,
     "    if on_it is not None:\n        on_it()\n    if not may_act(project, user, via=via):",
     "    if not may_act(project, user, via=via):\n        return unauthorized_message(project)\n"
     "    if on_it is not None:\n        on_it()\n    if not may_act(project, user, via=via):"),

    ("…and the reverse: the requester's own yes confirms (slice 4's rule, unannounced)", CONFIRM,
     "    if not may_act(project, user, via=via):\n"
     "        return unauthorized_message(project)\n\n"
     "    from openfactory.product.staging import consume\n",
     "    if not may_act(project, user, via=via) and not _is_requester(entry, user):\n"
     "        return unauthorized_message(project)\n\n"
     "    from openfactory.product.staging import consume\n"),

    # ── 6. an expired proposal ───────────────────────────────────────────────────────────────────
    ("a late yes on an expired proposal is answered by the model", CH,
     "    if not waiting and (is_yes(text) or is_no(text)) and _expired_recently(thread, channel):",
     "    if False:"),

    ("a staged proposal never expires", STAGING,
     "        if staged is not None and (time.time() - float(staged)) > PROPOSAL_TTL_SECONDS:",
     "        if False:"),

    # ── 7. the read-only intents ─────────────────────────────────────────────────────────────────
    ("status is answered by the model", CH,
     '    if intent == "status":', '    if intent == "status-cut":'),

    ("the status forgets what she is still waiting on", CH,
     "            language=lang) + _waiting_line(project)", "            language=lang)"),

    ("a status closes the decisions she asked for", CH,
     "    matched = match_intent(text)\n",
     "    _close_decisions_if_she_reads_this()\n    matched = match_intent(text)\n"),

    ("triage is answered by the model", CH,
     '    if intent == "triage":', '    if intent == "triage-cut":'),

    ("triage reads the board in silence", CH,
     '    if intent == "triage":\n        if on_it:\n            on_it()\n',
     '    if intent == "triage":\n'),

    # ── 8. the write intents ─────────────────────────────────────────────────────────────────────
    ("a dictated decision is answered as conversation", CH,
     '    if intent == "decision":', '    if intent == "decision-cut":'),

    ("the dictated decision does not name who can confirm it", CH,
     "        ask = decision_confirmation(number=number, decision=decision, language=lang)\n"
     "        if not may_act(project, user):",
     "        ask = decision_confirmation(number=number, decision=decision, language=lang)\n"
     "        if False:"),

    ("a confirmed decision has no executor of its own", CONFIRM,
     '    "decision": _confirm_decision,\n', ""),

    ("a dictated fact is answered as conversation", CH,
     '    if intent == "fact":', '    if intent == "fact-cut":'),

    # ── 9. the defect gesture ────────────────────────────────────────────────────────────────────
    ("a broken promise is never staged as a defect", CH,
     '    if getattr(answer, "is_defect", False):', "    if False:"),

    ("the defect forgets who reported it", CH,
     '"restated": text.strip()[:400],\n'
     '                          "reported_by": f"<@{user}>" if user else "",',
     '"restated": text.strip()[:400],\n'
     '                          "reported_by": "",'),

    ("a ticket outranks a defect in the one slot the stage has", CH,
     '    if getattr(answer, "is_defect", False):',
     '    if getattr(answer, "is_defect", False) and not getattr(answer, "is_ticket", False):'),

    # ── 10. the ticket gesture, and its siblings ─────────────────────────────────────────────────
    ("a card asked for as described is never staged", CH,
     '    if getattr(answer, "is_ticket", False):', "    if False:"),

    ("the card's title is the person's whole message", CH,
     '        title = ((getattr(answer, "ticket_title", "") or "").strip() or text.strip())[:80]',
     "        title = text.strip()[:80]"),

    ("an order for the backlog is never staged", CH,
     '    if getattr(answer, "is_reorder", False) and getattr(answer, "order", None):',
     "    if False:"),

    ("a start the model read is never proposed", CH,
     '    if getattr(answer, "gesture", "") == "queue":', "    if False:"),

    ("the queue proposal drops her answer", CH,
     '                               {"preamble": f"{answer.text}\\n\\n" if answer.text else ""},',
     '                               {"preamble": ""},'),

    # ── 11. the acceptance loop ──────────────────────────────────────────────────────────────────
    ("a delivery's verdict is answered as conversation", CH,
     "        answered = module.settle_acceptance(text)", "        answered = None"),

    ("a did-not-work is thanked as accepted", CH,
     '            say = accepted_text if verdict == "worked" else rejected_text',
     "            say = accepted_text"),

    ("an open delivery outranks the proposal just staged", CH,
     "    waiting_key, waiting = find_waiting(thread, channel, project=project)\n",
     "    waiting_key, waiting = find_waiting(thread, channel, project=project)\n"
     "    if waiting and module.settle_acceptance(text):\n"
     '        return Settled("", waiting)\n'),

    ("a release is put live for anyone who says it worked", CH,
     "    if not may_act(project, user, via=via):\n"
     "        return unauthorized_message(project)\n\n"
     "    from openfactory.product.release import release",
     "    from openfactory.product.release import release"),

    ("…and the reverse: a release loop stays open until an approver answers (pinned as found)",
     MODULE,
     "        rows = close_by_observation(ledger, {(ACCEPTANCE, loop.subject, loop.about): "
     "verdict})",
     "        rows = [] if is_release(loop) else close_by_observation(\n"
     "            ledger, {(ACCEPTANCE, loop.subject, loop.about): verdict})"),

    # ── 12. one conversation per room, one per thread ────────────────────────────────────────────
    ("a bare message becomes a conversation of its own (the conversation-key defect)", CH,
     '    return event.get("thread_ts") or channel',
     '    return event.get("thread_ts") or event.get("ts") or channel'),

    ("a thread's history forgets the room's rolling exchange", CH,
     "        [t for t in transcript.recent(project.name, thread=thread, channel=channel)",
     '        [t for t in transcript.recent(project.name, thread=thread, channel="")'),

    ("the current message is handed to the model as its own history", CH,
     "         if not (arrival_ts and t.ts == arrival_ts)],", "         if True],"),

    ("a bare yes cannot find a proposal staged inside a thread", STAGING,
     '                          if e.get("channel") == channel and k not in (thread, channel)]',
     "                          if False]"),

    # ── 13. when the module cannot answer ────────────────────────────────────────────────────────
    ("an unreadable base still sends a receipt and asks the model", CH,
     '        log.warning("[%s] product module unavailable: %s", project.name, ctx.reason)\n'
     "        return unavailable(language=lang)\n",
     '        log.warning("[%s] product module unavailable: %s", project.name, ctx.reason)\n'),

    ("an answer the model could not give is passed on as one", CH,
     "    if not answer.ok:\n        return unavailable(language=lang)",
     "    if False:\n        return unavailable(language=lang)"),

    ("a crash goes silent", CH,
     '        reply = broke(language=getattr(project, "language", None))', "        reply = None"),

    ("a crash is not paged", CH,
     '        log.error("OPENFACTORY_PRODUCT_MUTE project=%s thread=%s — the client got no "',
     '        log.error("product channel mute project=%s thread=%s — the client got no "'),

    # ── 14. a reply that claims a write ──────────────────────────────────────────────────────────
    ("a reply claiming a write goes unobserved", CH,
     "    if claim:\n", "    if False:\n"),

    ("a reply claiming a write is corrected in front of the client", CH,
     '    claim = claims_a_write(getattr(answer, "text", "") or "")\n',
     '    claim = claims_a_write(getattr(answer, "text", "") or "")\n'
     '    answer = answer.model_copy(update={"text": answer.text + " (nada foi gravado)"}) '
     "if claim else answer\n"),

    # ── what she asks a person, and what closes it ───────────────────────────────────────────────
    ("what she asks a person to decide is never tracked", CH,
     '    if getattr(answer, "decisions", None):', "    if False:"),

    ("a decision is opened about no conversation", CH,
     "            module.record_decisions(answer.decisions, channel=channel)",
     '            module.record_decisions(answer.decisions, channel="")'),

    ("a message she reads no longer closes what she asked", CH,
     "    _close_decisions_if_she_reads_this()\n", ""),

    ("…and the reverse: decisions close only in their own conversation (slice 4, unannounced)",
     MODULE,
     "        live = [x for x in waiting(ledger, owner=OWNER) if x.kind == DECISION]\n",
     "        live = [x for x in waiting(ledger, owner=OWNER) if x.kind == DECISION\n"
     "                and x.about == channel]\n"),

    # ── the intake ───────────────────────────────────────────────────────────────────────────────
    ("the model is never handed the intake", CH,
     '                           **({"intake": intake} if intake and _accepts_intake(module) '
     "else {}))",
     "                           **{})"),

    ("a turn never joins the intake case", CH,
     "        _case.note_turn(project, thread, user, text, answer)", "        pass"),
]
