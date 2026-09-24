"""#266 slice 1: the conversation, pinned flow by flow — every flow's own line, cut, must go red.

The suite is the specification slice 2 extracts the turn engine against, so a flow it cannot see
is a flow the extraction may lose without anybody noticing. One row per flow at least, each
cutting the line in `product/channel.py` (or in the module it hands the act to) that the flow
stands on — every `if intent ==` of `_run_intent` among them, since #266 names the intents in
slice 1's scope.

Some rows cut in the OTHER direction: they apply the change a test says is today's behaviour on
purpose — the requester-bound yes and the scoped decision close of slice 4, and the defects pinned
as found (a typed no recorded as an approval, in the durable store and in the intake case; a
refused release that closes its loop; an expired proposal whose durable row brings the notice
back). Those rows prove the pins are pins: the day the change lands, it lands red, as a decision.

ONE OF THEM IS A PROBE, NOT THE FIX, and says so in its label. The intended change for the refused
release spans two sites — the module must leave a release loop open, and `_maybe_release` must
close it once `may_act` passes (or on a "não funcionou") — and a row cuts one. The row keeps a
"worked" from closing any release loop, which is the half the refused-release pin reads; the
other half is pinned by the admin's release test, which asserts an approved release leaves its
loop closed as `worked`.

THE FIRST RUN WAS 61/62 (2026-09-24). "the receipt waits for the authorisation" survived: the
test compared the LAST receipt with the one a "sim" seeds, and the receipts are a small catalogue
picked by the message — the request before it picks the same line, so the comparison held with the
refused yes's receipt gone. The test counts one receipt per message now, and the row is red.

THE SECOND RUN FOLLOWED A REVIEW that cut lines on a scratch copy and watched them stay green:
eleven of the fifteen intent rows, the fall-throughs, the release's three refusals, the merged
draft's second yes, the displacement notice, the never-raises excepts, and the expiry's order.
Each became a test and a row below; 146 rows, every one red (2026-09-24).

The conversation-key row runs against `tests/test_transcript_memory.py`: which conversation a
Slack event belongs to is the transport's contract, pinned where the listener's is.
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

    ("the acceptance check asks the model with no delivery open", MODULE,
     "        if not open_acc:\n            return \"\"\n"
     "        loop = max(open_acc, key=lambda x: x.ts)\n        ctx = self.context()",
     "        if not open_acc:\n"
     "            self._role().judge_acceptance(sandbox=None, workspace=None, reply=text,\n"
     "                                          delivered=\"\")\n"
     "            return \"\"\n"
     "        loop = max(open_acc, key=lambda x: x.ts)\n        ctx = self.context()"),

    # ── 2. a request becomes a draft, staged, with the question ──────────────────────────────────
    ("a request is answered and never drafted", CH,
     "    if answer.is_request:", "    if False:"),

    ("the draft is staged where no yes will look for it", CH,
     'replaced = remember(thread, {"answer": answer,',
     'replaced = remember(thread + "-elsewhere", {"answer": answer,'),

    ("the draft forgets who asked for it", CH,
     '                              asked_by=f"<@{user}>" if user else "", source=source or "")',
     '                              asked_by="", source=source or "")'),

    ("the draft forgets where the request came from", CH,
     '                              asked_by=f"<@{user}>" if user else "", source=source or "")',
     '                              asked_by=f"<@{user}>" if user else "", source="")'),

    ("the role's answer is dropped from in front of the draft", CH,
     '                              preamble=f"{answer.text}\\n\\n" if answer.text else "",',
     '                              preamble="",'),

    ("the buttons are offered without the typed way to answer", CH,
     'posted = confirm(f"{text}\\n\\n{or_just_reply(language=lang)}",',
     'posted = confirm(f"{text}",'),

    ("a proposal posted with its buttons is shown again as prose", CH,
     "    return Posted(text) if posted else text", "    return text"),

    ("a request the role could not draft is answered with silence", CH,
     "        if offered:\n            # returned WHOLE",
     "        if True:\n            # returned WHOLE"),

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

    ("what a click verified never reaches the pop", CH,
     "                        arrival_ts=arrival_ts, fingerprint=fingerprint)",
     '                        arrival_ts=arrival_ts, fingerprint="")'),

    ("a draft that landed opens its card and asks for no second yes", CONFIRM,
     '    if cards:\n        entry["next"] = {', '    if False:\n        entry["next"] = {'),

    ("the second yes is not written on the card", CONFIRM,
     "    if cards:\n        return _stamped_on_the_cards(",
     "    if False:\n        return _stamped_on_the_cards("),

    ("the acceptance on the card forgets whose it is", CONFIRM,
     'requester=_bare_id(entry.get("asked_by", "")),', 'requester="",'),

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

    ("an admin may not reject what somebody else asked for", CH,
     "        if not may_act(project, user, via=via) and not _is_requester(waiting, user):",
     "        if not _is_requester(waiting, user):"),

    ("a typed no is sent to the judge — a model call to read a word the list already read", CH,
     "    if waiting and not is_yes(text) and not is_no(text):",
     "    if waiting and not is_yes(text):"),

    ("…and the reverse: a typed no is recorded durably as a rejection (pinned as found)", CH,
     "                approved=True)\n        # the discarded proposal",
     "                approved=False)\n        # the discarded proposal"),

    ("…and the reverse: a typed no drops the intake case as rejected (pinned as found)", CH,
     "                approved=True)\n        # the discarded proposal",
     "                approved=True)\n"
     "        from openfactory.product import case as _c\n"
     '        _c.hook("rejected", project, waiting_key, waiting)\n'
     "        # the discarded proposal"),

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

    ("a late no on an expired proposal hears nothing about it", CH,
     "    if not waiting and (is_yes(text) or is_no(text)) and _expired_recently(thread, channel):",
     "    if not waiting and is_yes(text) and _expired_recently(thread, channel):"),

    ("the expiry notice is owed to every later yes, not to one", STAGING,
     "            if key and _EXPIRED_TOMBSTONES.pop(key, None) is not None:",
     "            if key and _EXPIRED_TOMBSTONES.get(key) is not None:"),

    ("…and the reverse: an expired proposal's durable row stays expired (pinned as found)",
     STAGING,
     "            _EXPIRED_TOMBSTONES[thread] = time.time()\n",
     "            _EXPIRED_TOMBSTONES[thread] = time.time()\n"
     "            if project is not None:\n"
     "                try:\n"
     "                    from openfactory.memory import messages as _store\n"
     "                    _store.answer(getattr(project, 'name', '') or '',\n"
     "                                  token=proposal_token(thread, entry), answer='expired')\n"
     "                except Exception:  # noqa: BLE001\n"
     "                    pass\n"),

    ("the expiry is read before the delivery a bare yes answers", CH,
     "    if not waiting:\n        answered = module.settle_acceptance(text)\n",
     "    if not waiting and (is_yes(text) or is_no(text)) and "
     "_expired_recently(thread, channel):\n"
     "        from openfactory.product.voice import proposal_expired\n\n"
     "        return Settled(proposal_expired(language=lang), waiting)\n"
     "    if not waiting:\n        answered = module.settle_acceptance(text)\n"),

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

    ("the base is checked before the intents — a status cannot answer when it is down", CH,
     "    matched = match_intent(text)\n    if matched:",
     "    if not module.context().available:\n        return unavailable(language=lang)\n"
     "    matched = match_intent(text)\n    if matched:"),

    ("an intent that gives the message back swallows it instead", CH,
     "        if done:\n            return done", "        return done"),

    ("triage is answered by the model", CH,
     '    if intent == "triage":', '    if intent == "triage-cut":'),

    ("triage reads the board in silence", CH,
     '    if intent == "triage":\n        if on_it:\n            on_it()\n',
     '    if intent == "triage":\n'),

    ("who-are-you is answered by the model", CH,
     '    if intent == "announce":', '    if intent == "announce-cut":'),

    ("what-is-parked is answered by the model", CH,
     '    if intent == "needs_action":', '    if intent == "needs_action-cut":'),

    # ── 8. the write intents ─────────────────────────────────────────────────────────────────────
    ("a dictated decision is answered as conversation", CH,
     '    if intent == "decision":', '    if intent == "decision-cut":'),

    ("the dictated decision does not name who can confirm it", CH,
     "        ask = decision_confirmation(number=number, decision=decision, language=lang)\n"
     "        if not may_act(project, user):",
     "        ask = decision_confirmation(number=number, decision=decision, language=lang)\n"
     "        if False:"),

    ("a decision on a requirement the base does not have breaks the turn", CH,
     "        if instead:\n            return instead\n        if not req.is_live:\n"
     "            # writing into a document",
     "        if not req.is_live:\n            # writing into a document"),

    ("a decision is staged on a retired requirement", CH,
     "        if not req.is_live:\n            # writing into a document",
     "        if False:\n            # writing into a document"),

    ("a confirmed decision has no executor of its own", CONFIRM,
     '    "decision": _confirm_decision,\n', ""),

    ("a dictated fact is answered as conversation", CH,
     '    if intent == "fact":', '    if intent == "fact-cut":'),

    ("a dictation ending in a question mark is staged as a fact", CH,
     '        if not fact or fact.endswith("?"):', "        if not fact:"),

    ("a fact's term is the whole sentence", CH,
     "    words = fact.split()\n", "    return fact\n    words = fact.split()\n"),

    ("an acceptance is answered as conversation", CH,
     '    if intent == "accept":', '    if intent == "accept-cut":'),

    ("what is already agreed is staged for agreement again", CH,
     "        if req.is_promise:\n            return f\"{name}: o requisito {number} já estava "
     "acordado.\"",
     "        if False:\n            return f\"{name}: o requisito {number} já estava "
     "acordado.\""),

    ("a retired requirement is staged to be agreed back into force", CH,
     "        if not req.is_live:\n            # THE MODULE'S OWN QUESTION",
     "        if False:\n            # THE MODULE'S OWN QUESTION"),

    ("an acceptance of a requirement the base does not have breaks the turn", CH,
     "        if instead:\n            return instead\n        if req.is_promise:",
     "        if req.is_promise:"),

    ("a confirmed acceptance has no executor of its own", CONFIRM,
     '    "accept": _confirm_accept,\n', ""),

    ("an acceptance agreed with no card is never broken down", CONFIRM,
     "    return _also_broke_it_down(module, entry[\"number\"], user, head, lang, project)",
     "    return head"),

    ("a drop is answered as conversation", CH,
     '    if intent == "drop":', '    if intent == "drop-cut":'),

    ("what is already off the table is staged to be dropped", CH,
     "        if not req.is_live:\n            # already off the table",
     "        if False:\n            # already off the table"),

    ("a drop of a requirement the base does not have breaks the turn", CH,
     "        if instead:\n            return instead\n        if not req.is_live:\n"
     "            # already off the table",
     "        if not req.is_live:\n            # already off the table"),

    ("a drop forgets why", CH,
     '"reason": (captures.get("reason") or "").strip()[:300],', '"reason": "",'),

    ("a drop does not name who can confirm it", CH,
     "                                was_a_promise=was_a_promise, language=lang)\n"
     "        if not may_act(project, user):",
     "                                was_a_promise=was_a_promise, language=lang)\n"
     "        if False:"),

    ("a confirmed drop has no executor of its own", CONFIRM,
     '    "drop": _confirm_drop,\n', ""),

    ("a close is answered as conversation", CH,
     '    if intent == "close":', '    if intent == "close-cut":'),

    ("a survivor named without a # is guessed at instead of asked about", CH,
     "        if unclear and not in_favour_of:", "        if False:"),

    ("a close forgets the card that survives it", CH,
     '"in_favour_of": in_favour_of, "reason": reason,', '"in_favour_of": None, "reason": reason,'),

    ("a close does not name who can confirm it", CH,
     "                                 language=lang)\n        if not may_act(project, user):\n"
     "            admins = _admin_mentions(project)\n            if admins:\n"
     '                ask += f"\\n\\n({admins}: o encerramento',
     "                                 language=lang)\n        if False:\n"
     "            admins = _admin_mentions(project)\n            if admins:\n"
     '                ask += f"\\n\\n({admins}: o encerramento'),

    ("a confirmed close has no executor of its own", CONFIRM,
     '    "close": _confirm_close,\n', ""),

    ("a correction is answered as conversation", CH,
     '    if intent == "correct":', '    if intent == "correct-cut":'),

    ("a correction does not name who can confirm it", CH,
     "        ask = correct_confirmation(number=number, text=text, title=new_title, "
     "language=lang)\n        if not may_act(project, user):",
     "        ask = correct_confirmation(number=number, text=text, title=new_title, "
     "language=lang)\n        if False:"),

    ("a confirmed correction has no executor of its own", CONFIRM,
     '    "correct": _confirm_correct,\n', ""),

    ("an alignment is answered as conversation", CH,
     '    if intent == "align":', '    if intent == "align-cut":'),

    ("an alignment to what is not a promise is staged anyway", CH,
     "        if not req.is_promise:\n            refusal = _align_refusal(",
     "        if False:\n            refusal = _align_refusal("),

    ("an alignment to a requirement the base does not have breaks the turn", CH,
     "        req, corpus, instead = _named_requirement(project, module, requirement, name, "
     "lang)\n        if instead:\n            return instead\n",
     "        req, corpus, instead = _named_requirement(project, module, requirement, name, "
     "lang)\n"),

    ("an alignment does not name who can confirm it", CH,
     "                                 title=req.title or req.slug, language=lang)\n"
     "        if not may_act(project, user):",
     "                                 title=req.title or req.slug, language=lang)\n"
     "        if False:"),

    ("a text replaced by a promise is refused without naming the promise", CH,
     "        if promise:\n            return align_refused(",
     "        if False:\n            return align_refused("),

    ("a replacement the client dropped is offered as one to agree to", CH,
     "            if not replacement.is_live:", "            if False:"),

    ("a readable replacement is reported as a broken chain", CH,
     "        if replacement is not None:", "        if False:"),

    ("a dropped requirement is refused as a mere proposal", CH,
     "    if not req.is_live:\n"
     "        return align_refused(number=number, requirement=requirement, language=lang)",
     "    if False:\n"
     "        return align_refused(number=number, requirement=requirement, language=lang)"),

    ("a confirmed alignment has no executor of its own", CONFIRM,
     '    "align": _confirm_align,\n', ""),

    ("a breakdown is answered as conversation", CH,
     '    if intent == "breakdown":', '    if intent == "breakdown-cut":'),

    ("a breakdown files work for anybody who types it", CH,
     "            return unauthorized_message(project)\n        if on_it:\n            on_it()\n"
     "        # `asked_for=True`",
     "            pass\n        if on_it:\n            on_it()\n        # `asked_for=True`"),

    ("a refused breakdown still buys a receipt", CH,
     "        if not may_act(project, user):\n            return unauthorized_message(project)\n"
     "        if on_it:\n            on_it()\n        # `asked_for=True`",
     "        if on_it:\n            on_it()\n"
     "        if not may_act(project, user):\n            return unauthorized_message(project)\n"
     "        # `asked_for=True`"),

    ("a typed breakdown is filed as the acceptance's automatic one", CH,
     "        results = module.break_down(number, actor=user, asked_for=True)",
     "        results = module.break_down(number, actor=user, asked_for=False)"),

    ("a refine is answered as conversation", CH,
     '    if intent == "refine":', '    if intent == "refine-cut":'),

    ("a refine writes criteria for anybody who types it", CH,
     "        if not may_act(project, user):\n            return unauthorized_message(project)\n"
     "        if on_it:\n            on_it()\n        return _refine_reply(",
     "        if on_it:\n            on_it()\n        return _refine_reply("),

    ("the first pass is answered as conversation", CH,
     '    if intent == "baseline":', '    if intent == "baseline-cut":'),

    ("the first pass runs for anybody who asks", CH,
     "    if not may_act(project, user):\n        return unauthorized_message(project)\n\n"
     "    lang = getattr(project, \"language\", None)\n    channel_id",
     "    lang = getattr(project, \"language\", None)\n    channel_id"),

    ("a typed what-comes-next is answered by the model", CH,
     '    if intent == "queue":', '    if intent == "queue-cut":'),

    # ── 9. the defect gesture ────────────────────────────────────────────────────────────────────
    ("a broken promise is never staged as a defect", CH,
     '    if getattr(answer, "is_defect", False):', "    if False:"),

    ("the defect forgets who reported it", CH,
     '"restated": text.strip()[:400],\n'
     '                          "reported_by": f"<@{user}>" if user else "",',
     '"restated": text.strip()[:400],\n'
     '                          "reported_by": "",'),

    ("the defect forgets where the report came from", CH,
     '"source": source or "", "channel": channel}, lang=lang, project=project)',
     '"source": "", "channel": channel}, lang=lang, project=project)'),

    ("the restatement is not cut to 400 characters", CH,
     '"restated": text.strip()[:400],', '"restated": text.strip(),'),

    ("an admin's own report is told to ask the admins", CH,
     '        ask = defect_confirmation(violates=getattr(answer, "violates", None), '
     "language=lang)\n        if not may_act(project, user):",
     '        ask = defect_confirmation(violates=getattr(answer, "violates", None), '
     "language=lang)\n        if True:"),

    ("a defect displaces a waiting proposal in silence", CH,
     "they must read it.\n        body = replaced + (",
     "they must read it.\n        body = ("),

    ("a draft displaces a waiting proposal in silence", CH,
     "    return offer_with_buttons(project, thread, preamble + replaced + confirmation_request(",
     "    return offer_with_buttons(project, thread, preamble + confirmation_request("),

    ("a ticket outranks a defect in the one slot the stage has", CH,
     '    if getattr(answer, "is_defect", False):',
     '    if getattr(answer, "is_defect", False) and not getattr(answer, "is_ticket", False):'),

    # ── 10. the ticket gesture, and its siblings ─────────────────────────────────────────────────
    ("a card asked for as described is never staged", CH,
     '    if getattr(answer, "is_ticket", False):', "    if False:"),

    ("a request outranks a card read in the same answer", CH,
     '    if getattr(answer, "is_ticket", False):',
     '    if getattr(answer, "is_ticket", False) and not answer.is_request:'),

    ("the card's title is the person's whole message", CH,
     '        title = ((getattr(answer, "ticket_title", "") or "").strip() or text.strip())[:80]',
     "        title = text.strip()[:80]"),

    ("a card read without a title is staged with none", CH,
     '        title = ((getattr(answer, "ticket_title", "") or "").strip() or text.strip())[:80]',
     '        title = (getattr(answer, "ticket_title", "") or "").strip()[:80]'),

    ("an admin's own card is told to ask the admins", CH,
     "        ask = ticket_confirmation(title=title, language=lang)\n"
     "        if not may_act(project, user):",
     "        ask = ticket_confirmation(title=title, language=lang)\n        if True:"),

    ("an order for the backlog is never staged", CH,
     '    if getattr(answer, "is_reorder", False) and getattr(answer, "order", None):',
     "    if False:"),

    ("a reorder with no order is staged anyway", CH,
     '    if getattr(answer, "is_reorder", False) and getattr(answer, "order", None):',
     '    if getattr(answer, "is_reorder", False):'),

    ("a start the model read is never proposed", CH,
     '    if getattr(answer, "gesture", "") == "queue":', "    if False:"),

    ("a request outranks a start read in the same answer", CH,
     '    if getattr(answer, "gesture", "") == "queue":',
     '    if getattr(answer, "gesture", "") == "queue" and not answer.is_request:'),

    ("the queue proposal drops her answer", CH,
     '                               {"preamble": f"{answer.text}\\n\\n" if answer.text else ""},',
     '                               {"preamble": ""},'),

    ("an empty queue proposal is staged for a yes that promotes nothing", CH,
     "    if proposal and proposal.items:", "    if proposal is not None:"),

    # ── 11. the acceptance loop ──────────────────────────────────────────────────────────────────
    ("a delivery's verdict is answered as conversation", CH,
     "        answered = module.settle_acceptance(text)", "        answered = None"),

    ("a did-not-work is thanked as accepted", CH,
     '            say = accepted_text if verdict == "worked" else rejected_text',
     "            say = accepted_text"),

    ("the delivery a bare yes settled among several is not named", CH,
     "            return Settled(say(loop, agent_name=agent, ambiguous=ambiguous), waiting)",
     "            return Settled(say(loop, agent_name=agent), waiting)"),

    ("a sentence the word list cannot read never reaches the acceptance judge", MODULE,
     "            verdict = self._judge_acceptance(text)", '            verdict = ""'),

    ("an open delivery outranks the proposal just staged", CH,
     "    waiting_key, waiting = find_waiting(thread, channel, project=project)\n",
     "    waiting_key, waiting = find_waiting(thread, channel, project=project)\n"
     "    if waiting and module.settle_acceptance(text):\n"
     '        return Settled("", waiting)\n'),

    ("with a proposal pending, a message the judge left undecided settles the delivery", CH,
     "    if not waiting:\n        answered = module.settle_acceptance(text)\n",
     "    if True:\n        answered = module.settle_acceptance(text)\n"),

    ("the model is not told what is still pending", CH,
     '                           pending=_proposal_summary(waiting) if waiting else "",',
     '                           pending="",'),

    ("a release is put live for anyone who says it worked", CH,
     "    if not may_act(project, user, via=via):\n"
     "        return unauthorized_message(project)\n\n"
     "    from openfactory.product.release import release",
     "    from openfactory.product.release import release"),

    ("a did-not-work on a release puts it live", CH,
     '    if verdict != "worked":\n        return (f"{head}entendi',
     '    if False:\n        return (f"{head}entendi'),

    ("a release the workflow refused is announced as going live", CH,
     '    if not ok:\n        return f"{head}{why}"',
     '    if False:\n        return f"{head}{why}"'),

    ("with two releases waiting, the newest guess is put live", CH,
     "    if ambiguous:\n        # NOTHING was released",
     "    if False:\n        # NOTHING was released"),

    ("…and the reverse, as a probe (not the fix): a worked never closes a release loop",
     MODULE,
     "        rows = close_by_observation(ledger, {(ACCEPTANCE, loop.subject, loop.about): "
     "verdict})",
     '        rows = [] if (is_release(loop) and verdict == "worked") else close_by_observation(\n'
     "            ledger, {(ACCEPTANCE, loop.subject, loop.about): verdict})"),

    # ── 12. one conversation per room, one per thread ────────────────────────────────────────────
    ("a bare message becomes a conversation of its own (the conversation-key defect)", CH,
     '    return event.get("thread_ts") or channel',
     '    return event.get("thread_ts") or event.get("ts") or channel',
     "tests/test_transcript_memory.py"),

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

    ("the person's turn failing to record costs the answer", CH,
     "    except Exception:  # noqa: BLE001 — the record must never cost the person their answer",
     "    except ValueError:  # the record must never cost the person their answer"),

    ("a judge that raises costs the turn", CH,
     "        except Exception:  # noqa: BLE001 — an unreadable judgment leaves the proposal "
     "pending",
     "        except ValueError:  # an unreadable judgment leaves the proposal pending"),

    ("closing the decisions she asked for, failing, costs the answer", CH,
     "        except Exception:  # noqa: BLE001 — bookkeeping must never cost the reply",
     "        except ValueError:  # bookkeeping must never cost the reply"),

    ("recording the decisions she asked for, failing, costs the answer", CH,
     "        except Exception:  # noqa: BLE001\n"
     '            log.warning("[%s] could not record the decisions she asked for"',
     "        except ValueError:\n"
     '            log.warning("[%s] could not record the decisions she asked for"'),

    ("the intake case, failing, costs the answer", CH,
     "    except Exception:  # noqa: BLE001 — the case is bookkeeping; the reply is the act",
     "    except ValueError:  # the case is bookkeeping; the reply is the act"),

    ("buttons the transport failed to post cost the proposal", CH,
     "    except Exception:  # noqa: BLE001 — the affordance is optional; the proposal is not",
     "    except ValueError:  # the affordance is optional; the proposal is not"),

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
