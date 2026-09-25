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

THE THIRD RUN FOLLOWED THE EXTRACTION (#266 slice 2). The conversation left `product/channel.py`
for the turn engine (`product/engine.py`), and the suite now drives the engine through the neutral
`Message`. Every row whose line moved is RE-PINNED onto the engine with its claim unchanged, each
marked where it happened. Most anchors moved verbatim; the ones that had to change say so by their
text: the receipt and the decision close are the turn's own (`ex.on_it()`,
`ex.close_decisions_if_she_reads_this()`), what a click verified travels on the message
(`ex.fingerprint`), and the two "falls through" rows cut the pipeline's `if` rather than a stage's
— a stage answering None is the pipeline falling through by design, so cutting it there would
change nothing. The two button rows stay on `channel.py`, re-pinned to the chat adapter's
renderer (`deliver`), which is where a proposal is joined to the typed way to answer and where
"already posted" is said now that the engine posts nothing.

#272 IS FIXED: a typed "não" is recorded as a no. The two reverse rows that applied that change
to prove the pin are retired in place, because their change is the code now, and three rows put
the wrong record back: the approval's flag at the typed rejection, and each of the two records
the flag drives (the durable answer, the intake case). "a no leaves the proposal staged" is
re-pinned onto the new flag, its claim unchanged. 147 rows, every one red (2026-09-24).

#273 IS FIXED, at the two sites the probe could only point at: `settle_acceptance` hands every
release loop back open, and `_maybe_release` closes it — on a "não funcionou", and on a
"funcionou" once `may_act` passes. The probe is retired in place, because its change is the code
now. The rows that replace it cut each site (the module closes the loop again; the gate closes it
before asking who is speaking) and each flow the fix's tests pin: an authorised "funcionou" that
leaves the loop open, a "não funcionou" that leaves it open, a close that waits for the workflow,
and a carve-out widened past releases. The two rows anchored on the gate's refusal are re-pinned
onto its new text, claims unchanged, here and in `public_product_conversation_is_core.py`. 151
rows, every one red (2026-09-24).

#274 IS FIXED, by the decision that expiry answers the proposal's durable row (`expired`, by
nobody), so the notice is said once. That alone would have hidden the proposal the notice tells
the person to ask for again, since its token names its content, so the store's fold now reads an
answer as settling the ask before it. The reverse row that answered the row on expiry is retired
in place, because its change is the code now. Four rows replace it: the expiry left unanswered,
the expiry recorded as a decision, and the old fold put back in each of its two readers
(`pending`, `answer_of`). 149 rows, every one red (2026-09-24). A fifth row, added in review,
keeps the panel's route from writing the click after the gate's `expired`: the audit trail
would say a person approved what nothing performed. It runs against the panel's own test.


AFTER THE DOOR (#266 slice 3), six rows are re-pinned, each marked. The turn records under the
registry PROJECT, whose product the transcript keys by (the two record rows and the history read);
the baseline's outcome goes back through the door to the conversation that asked, so its gate row
stands on the line after it; and the read-only path (`engine.fast`) repeats two of the turn's
never-raises lines word for word, so the crash and the failed-record rows take one line of the
turn's own context to cut the TURN's.


SLICE 4 (#266) CHANGED THE TWO PINS IT NAMED, ON PURPOSE. The first yes is bound to the requester
(another admin's "sim" confirms only where the product sets `accept_on_behalf`), and a message
closes only the decisions asked of its speaker, in its conversation. The two reverse rows that
applied slice 4's change to prove the pins were pins are RETIRED in place, each saying why: the
requester's one applied a rule slice 4 did not make (a requester off the admin list confirming),
and the decisions' one scoped by the room alone, which is less than slice 4 does. Two rows put
the old behaviour back instead — any admin's yes confirming whatever is staged, and any message
closing every open decision — and both go red against the flipped tests. Eight rows are
re-pinned, each marked: the turn's two transcript records carry the message's id and what it
answers, the staging lookup and the decisions' record carry the speaker, the defect's staging
line broke where it takes the person, and the room-level scan moved into `staging._staged_here`.
146 rows, every one red (2026-09-24).

ON ONE BRANCH (2026-09-25): 156 rows, with the fixes of #272, #273, #274 side by side.
"""

TEST = "tests/test_the_conversation_is_pinned.py"
CH = "openfactory/product/channel.py"
ENGINE = "openfactory/product/engine.py"
CONFIRM = "openfactory/product/confirm.py"
STAGING = "openfactory/product/staging.py"
MODULE = "openfactory/product/module.py"
MESSAGES = "openfactory/memory/messages.py"

MUTATIONS = [
    # ── 1. a question ────────────────────────────────────────────────────────────────────────────
    # RE-PINNED 2026-09-24: moved to engine.py
    # RE-PINNED 2026-09-24 (#266 slice 3): the turn records under the PROJECT, whose product the
    # transcript keys by; the comment above it pins the TURN's record, not the read-only path's
    # identical one
    # RE-PINNED 2026-09-24 (#266 slice 4): the record carries what the reply answers
    ("the agent's turn is never recorded — her memory loses what she said", ENGINE,
     "            # proposal she made, whichever way it reaches the person\n"
     '            transcript.record(project, thread=thread, role="agent", text=_text_of(reply),\n'
     "                              channel=channel, in_reply_to=message.id)",
     "            # proposal she made, whichever way it reaches the person\n"
     "            pass"),

    # RE-PINNED 2026-09-24: moved to engine.py
    # RE-PINNED 2026-09-24 (#266 slice 3): the call wrapped when it began recording under the
    # project
    # RE-PINNED 2026-09-24 (#266 slice 4): the record carries the message's id and what it
    # replies to on the same line; the cut still drops who said it
    ("the person's turn is recorded without who said it", ENGINE,
     'role="person", text=text,\n'
     "                                       actor=user, channel=channel, message_id=message.id,",
     'role="person", text=text,\n'
     '                                       actor="", channel=channel, message_id=message.id,'),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("the receipt goes silent before the model", ENGINE,
     "    ex.on_it()\n"
     "\n"
     "    from openfactory.memory import transcript\n",
     "\n"
     "    from openfactory.memory import transcript\n"),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("a question is answered with nothing", ENGINE,
     "        return offered\n"
     "    return answer.text\n",
     "        return offered\n"
     "    return None\n"),

    ("the acceptance check asks the model with no delivery open", MODULE,
     "        if not open_acc:\n            return \"\"\n"
     "        loop = max(open_acc, key=lambda x: x.ts)\n        ctx = self.context()",
     "        if not open_acc:\n"
     "            self._role().judge_acceptance(sandbox=None, workspace=None, reply=text,\n"
     "                                          delivered=\"\")\n"
     "            return \"\"\n"
     "        loop = max(open_acc, key=lambda x: x.ts)\n        ctx = self.context()"),

    # ── 2. a request becomes a draft, staged, with the question ──────────────────────────────────
    # RE-PINNED 2026-09-24: moved to engine.py
    ("a request is answered and never drafted", ENGINE,
     "    if answer.is_request:", "    if False:"),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("the draft is staged where no yes will look for it", ENGINE,
     'replaced = remember(thread, {"answer": answer,',
     'replaced = remember(thread + "-elsewhere", {"answer": answer,'),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("the draft forgets who asked for it", ENGINE,
     '                              asked_by=f"<@{user}>" if user else "", source=ex.source or "")',
     '                              asked_by="", source=ex.source or "")'),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("the draft forgets where the request came from", ENGINE,
     '                              asked_by=f"<@{user}>" if user else "", source=ex.source or "")',
     '                              asked_by=f"<@{user}>" if user else "", source="")'),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("the role's answer is dropped from in front of the draft", ENGINE,
     '                              preamble=f"{answer.text}\\n\\n" if answer.text else "",',
     '                              preamble="",'),

    # RE-PINNED 2026-09-24: the join moved into channel.deliver, the chat adapter's renderer
    ("the buttons are offered without the typed way to answer", CH,
     '        posted = confirm(f"{reply.text}\\n\\n{options.typed}",',
     '        posted = confirm(f"{reply.text}",'),

    # RE-PINNED 2026-09-24: the join moved into channel.deliver, the chat adapter's renderer
    ("a proposal posted with its buttons is shown again as prose", CH,
     "    return None if posted else reply.text",
     "    return reply.text"),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("a request the role could not draft is answered with silence", ENGINE,
     "    if offered:\n"
     "        # returned WHOLE and untouched, so the confirmation it carries",
     "    if True:\n"
     "        # returned WHOLE and untouched, so the confirmation it carries"),

    # ── 3. a yes confirms the staged proposal, once ──────────────────────────────────────────────
    # RE-PINNED 2026-09-24: moved to engine.py
    ("a typed yes on a staged proposal is not performed", ENGINE,
     "    if waiting and (is_yes(text) or judged_yes):", "    if False:"),

    ("the performed proposal is not consumed — a second yes writes it again", CONFIRM,
     "    performed = consume(key, entry, fingerprint=fingerprint, project=project, by=user,\n"
     "                        approved=True)",
     "    performed = entry"),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("the judge's approval of a sentence is ignored", ENGINE,
     '        judged_yes = verdict == "approve"', "        judged_yes = False"),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("the judge's rejection of a sentence is ignored", ENGINE,
     '        judged_no = verdict == "reject"', "        judged_no = False"),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("what a click verified never reaches the pop", ENGINE,
     "fingerprint=ex.fingerprint",
     'fingerprint=""'),

    ("a draft that landed opens its card and asks for no second yes", CONFIRM,
     '    if cards:\n        entry["next"] = {', '    if False:\n        entry["next"] = {'),

    ("the second yes is not written on the card", CONFIRM,
     "    if cards:\n        return _stamped_on_the_cards(",
     "    if False:\n        return _stamped_on_the_cards("),

    ("the acceptance on the card forgets whose it is", CONFIRM,
     'requester=_bare_id(entry.get("asked_by", "")),', 'requester="",'),

    # ── 4. a no rejects it ───────────────────────────────────────────────────────────────────────
    # RE-PINNED 2026-09-24: moved to engine.py
    # RE-PINNED 2026-09-24 (#272): the anchor carries the flag, which is `approved=False` now
    ("a no leaves the proposal staged", ENGINE,
     "        consume(waiting_key, waiting, fingerprint=fingerprint, project=project, by=user,\n"
     "                approved=False)",
     "        pass"),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("the discarded proposal stays in the prompt as still pending", ENGINE,
     "        waiting_key, waiting = None, None", "        pass"),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("the requester may not take their own proposal back", ENGINE,
     "        if not may_act(project, user, via=via) and not _is_requester(waiting, user):",
     "        if not may_act(project, user, via=via):"),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("anybody may destroy a proposal", ENGINE,
     "        if not may_act(project, user, via=via) and not _is_requester(waiting, user):",
     "        if False:"),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("an admin may not reject what somebody else asked for", ENGINE,
     "        if not may_act(project, user, via=via) and not _is_requester(waiting, user):",
     "        if not _is_requester(waiting, user):"),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("a typed no is sent to the judge — a model call to read a word the list already read", ENGINE,
     "    if waiting and not is_yes(text) and not is_no(text):",
     "    if waiting and not is_yes(text):"),

    # RETIRED 2026-09-24 (#272): "…and the reverse: a typed no is recorded durably as a rejection
    # (pinned as found)". The row applied `approved=False` to the typed rejection to prove the pin
    # was a pin; that change IS the fix now, so the line it cut is gone on purpose. Its claim is
    # carried the other way round by the rows below, which put the approval back.
    #
    # RETIRED 2026-09-24 (#272): "…and the reverse: a typed no drops the intake case as rejected
    # (pinned as found)". Same reason: the rejection's own `consume` now fires the `rejected` hook,
    # so the extra hook this row added is what the code does. The intake half is carried below.

    # #272, FIXED — each row puts the wrong record back, at the root and in each half it drove
    ("a typed no is recorded as an approval again, in the store and in the case (#272)", ENGINE,
     "                approved=False)\n        # the discarded proposal",
     "                approved=True)\n        # the discarded proposal"),

    ("a rejection is written to the durable store as an approval (#272)", STAGING,
     '                                answer="approve" if approved else "reject", by=by)',
     '                                answer="approve", by=by)'),

    ("a rejection moves the requester's intake case to confirmed (#272)", STAGING,
     '    _case.hook("confirmed" if approved else "rejected", project, key, verified)',
     '    _case.hook("confirmed", project, key, verified)'),

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

    # RETIRED 2026-09-24 (#266 slice 4): "…and the reverse: the requester's own yes confirms
    # (slice 4's rule, unannounced)". It proved the pin by letting a requester OFF the admin list
    # confirm their own draft — a rule slice 4 did not make: the admin list still decides who may
    # write at all (ADR-0047 §4), and slice 4 added whose proposal it is on top of it. The pin it
    # proved is flipped now, and the row below puts the old behaviour back instead.

    # #266 SLICE 4, THE REQUESTER-BOUND YES — the old rule back: any admin's yes confirms
    ("any admin's yes confirms a draft somebody else asked for again (slice 4 undone)", CONFIRM,
     "    refused = not_theirs(project, entry, user)\n"
     "    if refused:\n"
     "        return refused\n\n"
     "    # exactly the entry the caller read",
     "    # exactly the entry the caller read"),

    # ── 6. an expired proposal ───────────────────────────────────────────────────────────────────
    # RE-PINNED 2026-09-24: moved to engine.py
    ("a late yes on an expired proposal is answered by the model", ENGINE,
     "    if not waiting and (is_yes(text) or is_no(text)) and _expired_recently(thread, channel):",
     "    if False:"),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("a late no on an expired proposal hears nothing about it", ENGINE,
     "    if not waiting and (is_yes(text) or is_no(text)) and _expired_recently(thread, channel):",
     "    if not waiting and is_yes(text) and _expired_recently(thread, channel):"),

    ("the expiry notice is owed to every later yes, not to one", STAGING,
     "            if key and _EXPIRED_TOMBSTONES.pop(key, None) is not None:",
     "            if key and _EXPIRED_TOMBSTONES.get(key) is not None:"),

    # RETIRED 2026-09-24 (#274): "…and the reverse: an expired proposal's durable row stays expired
    # (pinned as found)". The row answered the durable row on expiry to prove the pin was a pin;
    # that is the fix now (`staging._answer_expired`), so the answer it added is a second one the
    # code already writes and the cut changes nothing. Replaced by the rows below, which take the
    # fix back out and put the old fold back.

    # #274, FIXED — expiry answers the durable row, and an answer settles only the ask before it
    ("an expired proposal's durable row is left unanswered — the notice is said again (#274)",
     STAGING,
     "    _answer_expired(thread, entry, project)\n",
     ""),

    ("an expiry is recorded durably as a rejection (#274)", STAGING,
     'EXPIRED = "expired"', 'EXPIRED = "reject"'),

    ("an answer to a token closes every later asking of it — a re-ask after expiry is hidden "
     "(#274)", MESSAGES,
     "            if answered_at.get(m.token, -1) < at]",
     "            if m.token not in answered_at]"),

    ("an answer to an earlier asking is read as the new one's — a re-ask is refused as decided "
     "(#274)", MESSAGES,
     "        if m.kind == ASKED:\n            return None\n",
     ""),

    ("a click on an expired proposal records the person's approve after the factory's expired "
     "(#274)", "openfactory/api/app.py",
     '            with _readable_store("retire that question"):\n'
     '                if token in [q.token for q in channel.pending(project)]:\n'
     '                    channel.answer(project, token=token, answer=EXPIRED)\n',
     '            channel.answer(project, token=token, answer=answer, by=by)\n',
     "tests/test_the_panel_is_a_channel.py"),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("the expiry is read before the delivery a bare yes answers", ENGINE,
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
    # RE-PINNED 2026-09-24: moved to engine.py
    ("status is answered by the model", ENGINE,
     '    if intent == "status":', '    if intent == "status-cut":'),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("the status forgets what she is still waiting on", ENGINE,
     "            language=lang) + _waiting_line(project)", "            language=lang)"),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("a status closes the decisions she asked for", ENGINE,
     "    matched = match_intent(ex.text)\n",
     "    ex.close_decisions_if_she_reads_this()\n"
     "    matched = match_intent(ex.text)\n"),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("the base is checked before the intents — a status cannot answer when it is down", ENGINE,
     "    matched = match_intent(ex.text)\n"
     "    if not matched:",
     "    from openfactory.product.voice import unavailable\n"
     "    if not ex.module.context().available:\n"
     "        return unavailable(language=ex.lang)\n"
     "    matched = match_intent(ex.text)\n"
     "    if not matched:"),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("an intent that gives the message back swallows it instead", ENGINE,
     "    done = intents(ex)\n"
     "    if done:\n"
     "        return done",
     "    done = intents(ex)\n"
     "    return done"),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("triage is answered by the model", ENGINE,
     '    if intent == "triage":', '    if intent == "triage-cut":'),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("triage reads the board in silence", ENGINE,
     '    if intent == "triage":\n        if on_it:\n            on_it()\n',
     '    if intent == "triage":\n'),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("who-are-you is answered by the model", ENGINE,
     '    if intent == "announce":', '    if intent == "announce-cut":'),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("what-is-parked is answered by the model", ENGINE,
     '    if intent == "needs_action":', '    if intent == "needs_action-cut":'),

    # ── 8. the write intents ─────────────────────────────────────────────────────────────────────
    # RE-PINNED 2026-09-24: moved to engine.py
    ("a dictated decision is answered as conversation", ENGINE,
     '    if intent == "decision":', '    if intent == "decision-cut":'),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("the dictated decision does not name who can confirm it", ENGINE,
     "        ask = decision_confirmation(number=number, decision=decision, language=lang)\n"
     "        if not may_act(project, user):",
     "        ask = decision_confirmation(number=number, decision=decision, language=lang)\n"
     "        if False:"),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("a decision on a requirement the base does not have breaks the turn", ENGINE,
     "        if instead:\n            return instead\n        if not req.is_live:\n"
     "            # writing into a document",
     "        if not req.is_live:\n            # writing into a document"),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("a decision is staged on a retired requirement", ENGINE,
     "        if not req.is_live:\n            # writing into a document",
     "        if False:\n            # writing into a document"),

    ("a confirmed decision has no executor of its own", CONFIRM,
     '    "decision": _confirm_decision,\n', ""),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("a dictated fact is answered as conversation", ENGINE,
     '    if intent == "fact":', '    if intent == "fact-cut":'),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("a dictation ending in a question mark is staged as a fact", ENGINE,
     '        if not fact or fact.endswith("?"):', "        if not fact:"),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("a fact's term is the whole sentence", ENGINE,
     "    words = fact.split()\n", "    return fact\n    words = fact.split()\n"),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("an acceptance is answered as conversation", ENGINE,
     '    if intent == "accept":', '    if intent == "accept-cut":'),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("what is already agreed is staged for agreement again", ENGINE,
     "        if req.is_promise:\n            return f\"{name}: o requisito {number} já estava "
     "acordado.\"",
     "        if False:\n            return f\"{name}: o requisito {number} já estava "
     "acordado.\""),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("a retired requirement is staged to be agreed back into force", ENGINE,
     "        if not req.is_live:\n            # THE MODULE'S OWN QUESTION",
     "        if False:\n            # THE MODULE'S OWN QUESTION"),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("an acceptance of a requirement the base does not have breaks the turn", ENGINE,
     "        if instead:\n            return instead\n        if req.is_promise:",
     "        if req.is_promise:"),

    ("a confirmed acceptance has no executor of its own", CONFIRM,
     '    "accept": _confirm_accept,\n', ""),

    ("an acceptance agreed with no card is never broken down", CONFIRM,
     "    return _also_broke_it_down(module, entry[\"number\"], user, head, lang, project)",
     "    return head"),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("a drop is answered as conversation", ENGINE,
     '    if intent == "drop":', '    if intent == "drop-cut":'),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("what is already off the table is staged to be dropped", ENGINE,
     "        if not req.is_live:\n            # already off the table",
     "        if False:\n            # already off the table"),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("a drop of a requirement the base does not have breaks the turn", ENGINE,
     "        if instead:\n            return instead\n        if not req.is_live:\n"
     "            # already off the table",
     "        if not req.is_live:\n            # already off the table"),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("a drop forgets why", ENGINE,
     '"reason": (captures.get("reason") or "").strip()[:300],', '"reason": "",'),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("a drop does not name who can confirm it", ENGINE,
     "                                was_a_promise=was_a_promise, language=lang)\n"
     "        if not may_act(project, user):",
     "                                was_a_promise=was_a_promise, language=lang)\n"
     "        if False:"),

    ("a confirmed drop has no executor of its own", CONFIRM,
     '    "drop": _confirm_drop,\n', ""),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("a close is answered as conversation", ENGINE,
     '    if intent == "close":', '    if intent == "close-cut":'),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("a survivor named without a # is guessed at instead of asked about", ENGINE,
     "        if unclear and not in_favour_of:", "        if False:"),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("a close forgets the card that survives it", ENGINE,
     '"in_favour_of": in_favour_of, "reason": reason,', '"in_favour_of": None, "reason": reason,'),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("a close does not name who can confirm it", ENGINE,
     "                                 language=lang)\n        if not may_act(project, user):\n"
     "            admins = _admin_mentions(project)\n            if admins:\n"
     '                ask += f"\\n\\n({admins}: o encerramento',
     "                                 language=lang)\n        if False:\n"
     "            admins = _admin_mentions(project)\n            if admins:\n"
     '                ask += f"\\n\\n({admins}: o encerramento'),

    ("a confirmed close has no executor of its own", CONFIRM,
     '    "close": _confirm_close,\n', ""),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("a correction is answered as conversation", ENGINE,
     '    if intent == "correct":', '    if intent == "correct-cut":'),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("a correction does not name who can confirm it", ENGINE,
     "        ask = correct_confirmation(number=number, text=text, title=new_title, "
     "language=lang)\n        if not may_act(project, user):",
     "        ask = correct_confirmation(number=number, text=text, title=new_title, "
     "language=lang)\n        if False:"),

    ("a confirmed correction has no executor of its own", CONFIRM,
     '    "correct": _confirm_correct,\n', ""),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("an alignment is answered as conversation", ENGINE,
     '    if intent == "align":', '    if intent == "align-cut":'),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("an alignment to what is not a promise is staged anyway", ENGINE,
     "        if not req.is_promise:\n            refusal = _align_refusal(",
     "        if False:\n            refusal = _align_refusal("),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("an alignment to a requirement the base does not have breaks the turn", ENGINE,
     "        req, corpus, instead = _named_requirement(project, module, requirement, name, "
     "lang)\n        if instead:\n            return instead\n",
     "        req, corpus, instead = _named_requirement(project, module, requirement, name, "
     "lang)\n"),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("an alignment does not name who can confirm it", ENGINE,
     "                                 title=req.title or req.slug, language=lang)\n"
     "        if not may_act(project, user):",
     "                                 title=req.title or req.slug, language=lang)\n"
     "        if False:"),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("a text replaced by a promise is refused without naming the promise", ENGINE,
     "        if promise:\n            return align_refused(",
     "        if False:\n            return align_refused("),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("a replacement the client dropped is offered as one to agree to", ENGINE,
     "            if not replacement.is_live:", "            if False:"),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("a readable replacement is reported as a broken chain", ENGINE,
     "        if replacement is not None:", "        if False:"),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("a dropped requirement is refused as a mere proposal", ENGINE,
     "    if not req.is_live:\n"
     "        return align_refused(number=number, requirement=requirement, language=lang)",
     "    if False:\n"
     "        return align_refused(number=number, requirement=requirement, language=lang)"),

    ("a confirmed alignment has no executor of its own", CONFIRM,
     '    "align": _confirm_align,\n', ""),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("a breakdown is answered as conversation", ENGINE,
     '    if intent == "breakdown":', '    if intent == "breakdown-cut":'),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("a breakdown files work for anybody who types it", ENGINE,
     "            return unauthorized_message(project)\n        if on_it:\n            on_it()\n"
     "        # `asked_for=True`",
     "            pass\n        if on_it:\n            on_it()\n        # `asked_for=True`"),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("a refused breakdown still buys a receipt", ENGINE,
     "        if not may_act(project, user):\n            return unauthorized_message(project)\n"
     "        if on_it:\n            on_it()\n        # `asked_for=True`",
     "        if on_it:\n            on_it()\n"
     "        if not may_act(project, user):\n            return unauthorized_message(project)\n"
     "        # `asked_for=True`"),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("a typed breakdown is filed as the acceptance's automatic one", ENGINE,
     "        results = module.break_down(number, actor=user, asked_for=True)",
     "        results = module.break_down(number, actor=user, asked_for=False)"),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("a refine is answered as conversation", ENGINE,
     '    if intent == "refine":', '    if intent == "refine-cut":'),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("a refine writes criteria for anybody who types it", ENGINE,
     "        if not may_act(project, user):\n            return unauthorized_message(project)\n"
     "        if on_it:\n            on_it()\n        return _refine_reply(",
     "        if on_it:\n            on_it()\n        return _refine_reply("),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("the first pass is answered as conversation", ENGINE,
     '    if intent == "baseline":', '    if intent == "baseline-cut":'),

    # RE-PINNED 2026-09-24: moved to engine.py
    # RE-PINNED 2026-09-24 (#266 slice 3): the channel the outcome was said on became the
    # conversation it goes back to
    ("the first pass runs for anybody who asks", ENGINE,
     "    if not may_act(project, user):\n        return unauthorized_message(project)\n\n"
     "    lang = getattr(project, \"language\", None)\n    where = conversation",
     "    lang = getattr(project, \"language\", None)\n    where = conversation"),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("a typed what-comes-next is answered by the model", ENGINE,
     '    if intent == "queue":', '    if intent == "queue-cut":'),

    # ── 9. the defect gesture ────────────────────────────────────────────────────────────────────
    # RE-PINNED 2026-09-24: moved to engine.py
    ("a broken promise is never staged as a defect", ENGINE,
     '    if getattr(answer, "is_defect", False):', "    if False:"),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("the defect forgets who reported it", ENGINE,
     '"restated": text.strip()[:400],\n'
     '                          "reported_by": f"<@{user}>" if user else "",',
     '"restated": text.strip()[:400],\n'
     '                          "reported_by": "",'),

    # RE-PINNED 2026-09-24: moved to engine.py
    # RE-PINNED 2026-09-24 (#266 slice 4): the call now takes the person on the line after, so
    # the anchor is the defect's own comment and the source it stages, and the card's twin line is
    # not cut in its place
    ("the defect forgets where the report came from", ENGINE,
     "# had is a fabricated classification the fix queue would sort by\n"
     '                          "source": source or "", "channel": channel},',
     "# had is a fabricated classification the fix queue would sort by\n"
     '                          "source": "", "channel": channel},'),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("the restatement is not cut to 400 characters", ENGINE,
     '"restated": text.strip()[:400],', '"restated": text.strip(),'),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("an admin's own report is told to ask the admins", ENGINE,
     '        ask = defect_confirmation(violates=getattr(answer, "violates", None), '
     "language=lang)\n        if not may_act(project, user):",
     '        ask = defect_confirmation(violates=getattr(answer, "violates", None), '
     "language=lang)\n        if True:"),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("a defect displaces a waiting proposal in silence", ENGINE,
     "they must read it.\n        body = replaced + (",
     "they must read it.\n        body = ("),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("a draft displaces a waiting proposal in silence", ENGINE,
     "    return offer(project, thread, preamble + replaced + confirmation_request(",
     "    return offer(project, thread, preamble + confirmation_request("),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("a ticket outranks a defect in the one slot the stage has", ENGINE,
     '    if getattr(answer, "is_defect", False):',
     '    if getattr(answer, "is_defect", False) and not getattr(answer, "is_ticket", False):'),

    # ── 10. the ticket gesture, and its siblings ─────────────────────────────────────────────────
    # RE-PINNED 2026-09-24: moved to engine.py
    ("a card asked for as described is never staged", ENGINE,
     '    if getattr(answer, "is_ticket", False):', "    if False:"),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("a request outranks a card read in the same answer", ENGINE,
     '    if getattr(answer, "is_ticket", False):',
     '    if getattr(answer, "is_ticket", False) and not answer.is_request:'),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("the card's title is the person's whole message", ENGINE,
     '        title = ((getattr(answer, "ticket_title", "") or "").strip() or text.strip())[:80]',
     "        title = text.strip()[:80]"),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("a card read without a title is staged with none", ENGINE,
     '        title = ((getattr(answer, "ticket_title", "") or "").strip() or text.strip())[:80]',
     '        title = (getattr(answer, "ticket_title", "") or "").strip()[:80]'),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("an admin's own card is told to ask the admins", ENGINE,
     "        ask = ticket_confirmation(title=title, language=lang)\n"
     "        if not may_act(project, user):",
     "        ask = ticket_confirmation(title=title, language=lang)\n        if True:"),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("an order for the backlog is never staged", ENGINE,
     '    if getattr(answer, "is_reorder", False) and getattr(answer, "order", None):',
     "    if False:"),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("a reorder with no order is staged anyway", ENGINE,
     '    if getattr(answer, "is_reorder", False) and getattr(answer, "order", None):',
     '    if getattr(answer, "is_reorder", False):'),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("a start the model read is never proposed", ENGINE,
     '    if getattr(answer, "gesture", "") == "queue":', "    if False:"),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("a request outranks a start read in the same answer", ENGINE,
     '    if getattr(answer, "gesture", "") == "queue":',
     '    if getattr(answer, "gesture", "") == "queue" and not answer.is_request:'),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("the queue proposal drops her answer", ENGINE,
     '                               {"preamble": f"{answer.text}\\n\\n" if answer.text else ""},',
     '                               {"preamble": ""},'),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("an empty queue proposal is staged for a yes that promotes nothing", ENGINE,
     "    if proposal and proposal.items:", "    if proposal is not None:"),

    # ── 11. the acceptance loop ──────────────────────────────────────────────────────────────────
    # RE-PINNED 2026-09-24: moved to engine.py
    ("a delivery's verdict is answered as conversation", ENGINE,
     "        answered = module.settle_acceptance(text)", "        answered = None"),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("a did-not-work is thanked as accepted", ENGINE,
     '            say = accepted_text if verdict == "worked" else rejected_text',
     "            say = accepted_text"),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("the delivery a bare yes settled among several is not named", ENGINE,
     "            return Settled(say(loop, agent_name=agent, ambiguous=ambiguous), waiting)",
     "            return Settled(say(loop, agent_name=agent), waiting)"),

    ("a sentence the word list cannot read never reaches the acceptance judge", MODULE,
     "            verdict = self._judge_acceptance(text)", '            verdict = ""'),

    # RE-PINNED 2026-09-24: moved to engine.py
    # RE-PINNED 2026-09-24 (#266 slice 4): the lookup carries the speaker, whose own proposal
    # it finds first
    ("an open delivery outranks the proposal just staged", ENGINE,
     "    waiting_key, waiting = find_waiting(thread, channel, project=project, person=user)\n",
     "    waiting_key, waiting = find_waiting(thread, channel, project=project, person=user)\n"
     "    if waiting and module.settle_acceptance(text):\n"
     '        return Settled("", waiting)\n'),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("with a proposal pending, a message the judge left undecided settles the delivery", ENGINE,
     "    if not waiting:\n        answered = module.settle_acceptance(text)\n",
     "    if True:\n        answered = module.settle_acceptance(text)\n"),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("the model is not told what is still pending", ENGINE,
     '                           pending=_proposal_summary(waiting) if waiting else "",',
     '                           pending="",'),

    # RE-PINNED 2026-09-24: moved to engine.py
    # RE-PINNED 2026-09-24 (#273): the refusal carries a comment now, so the anchor is the gate
    # and that comment's first line; the cut still removes the gate, and the claim is unchanged
    ("a release is put live for anyone who says it worked", ENGINE,
     "    if not may_act(project, user, via=via):\n"
     "        # THE QUESTION STAYS OPEN FOR SOMEBODY WHO MAY ANSWER IT (#273).",
     "    if False:\n"
     "        # THE QUESTION STAYS OPEN FOR SOMEBODY WHO MAY ANSWER IT (#273)."),

    # RE-PINNED 2026-09-24: moved to engine.py
    # RE-PINNED 2026-09-24 (#273): the branch closes the loop before it answers now, so the anchor
    # is the branch and its comment's first line; the claim is unchanged
    ("a did-not-work on a release puts it live", ENGINE,
     '    if verdict != "worked":\n        # A "NÃO FUNCIONOU" CLOSES THE LOOP',
     '    if False:\n        # A "NÃO FUNCIONOU" CLOSES THE LOOP'),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("a release the workflow refused is announced as going live", ENGINE,
     '    if not ok:\n        return f"{head}{why}"',
     '    if False:\n        return f"{head}{why}"'),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("with two releases waiting, the newest guess is put live", ENGINE,
     "    if ambiguous:\n        # NOTHING was released",
     "    if False:\n        # NOTHING was released"),

    # RETIRED 2026-09-24 (#273): "…and the reverse, as a probe (not the fix): a worked never
    # closes a release loop". The probe kept `settle_acceptance` from closing a release loop on a
    # "worked", which was one half of the fix; the fix now returns every release loop open before
    # that line, so the cut changes nothing and the behaviour it probed is the code. Replaced by
    # the rows below, one per site the fix spans and one per flow its tests pin.

    # #273, FIXED — the module hands a release loop back open, and the gate closes it
    ("a release loop is closed by the verdict before anybody asks who spoke (#273)", MODULE,
     "        if is_release(loop):\n            return verdict, loop, ambiguous\n",
     ""),

    ("the release gate closes the loop before it asks who is speaking (#273)", ENGINE,
     "    if not may_act(project, user, via=via):\n"
     "        # THE QUESTION STAYS OPEN FOR SOMEBODY WHO MAY ANSWER IT (#273).",
     "    _close_release(project, loop, verdict)\n"
     "    if not may_act(project, user, via=via):\n"
     "        # THE QUESTION STAYS OPEN FOR SOMEBODY WHO MAY ANSWER IT (#273)."),

    ("an admin's worked releases and leaves the release question open (#273)", ENGINE,
     "    # whether the workflow was still there to take it.\n"
     "    _close_release(project, loop, verdict)\n",
     "    # whether the workflow was still there to take it.\n"),

    ("a did-not-work on a release leaves its loop open (#273)", ENGINE,
     "        # it: it spends nothing, and a release that did not work is not waiting on anybody's "
     "yes.\n"
     "        _close_release(project, loop, verdict)\n",
     "        # it: it spends nothing, and a release that did not work is not waiting on anybody's "
     "yes.\n"),

    ("an authorised worked closes the release only when the workflow took it (#273)", ENGINE,
     "    _close_release(project, loop, verdict)\n\n"
     "    from openfactory.product.release import release\n\n"
     "    ok, why = release(project, issue, approver=user,\n"
     '                      comment="aprovado pelo cliente no canal de produto")\n'
     "    if not ok:\n"
     '        return f"{head}{why}"\n',
     "    from openfactory.product.release import release\n\n"
     "    ok, why = release(project, issue, approver=user,\n"
     '                      comment="aprovado pelo cliente no canal de produto")\n'
     "    if not ok:\n"
     '        return f"{head}{why}"\n'
     "    _close_release(project, loop, verdict)\n"),

    ("every acceptance, not only a release, is handed back open (#273)", MODULE,
     "        if is_release(loop):\n            return verdict, loop, ambiguous\n",
     "        if True:\n            return verdict, loop, ambiguous\n"),

    # ── 12. one conversation per room, one per thread ────────────────────────────────────────────
    ("a bare message becomes a conversation of its own (the conversation-key defect)", CH,
     '    return event.get("thread_ts") or channel',
     '    return event.get("thread_ts") or event.get("ts") or channel',
     "tests/test_transcript_memory.py"),

    # RE-PINNED 2026-09-24: moved to engine.py
    # RE-PINNED 2026-09-24 (#266 slice 3): the history is read from the project's PRODUCT, handed
    # the project itself
    ("a thread's history forgets the room's rolling exchange", ENGINE,
     "        [t for t in transcript.recent(project, thread=thread, channel=channel)",
     '        [t for t in transcript.recent(project, thread=thread, channel="")'),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("the current message is handed to the model as its own history", ENGINE,
     "         if not (arrival_ts and t.ts == arrival_ts)],", "         if True],"),

    # RE-PINNED 2026-09-24 (#266 slice 4): the scan moved into `_staged_here`, which finds a
    # proposal by its room OR by its conversation (another person's key in the same one); the cut
    # takes the room half away, which is the half a bare yes at room level stands on
    ("a bare yes cannot find a proposal staged inside a thread", STAGING,
     '        return ((bool(channel) and entry.get("channel") == channel)\n'
     "                or conversation_of(key, entry) == thread)",
     "        return conversation_of(key, entry) == thread"),

    # ── 13. when the module cannot answer ────────────────────────────────────────────────────────
    # RE-PINNED 2026-09-24: moved to engine.py
    ("an unreadable base still sends a receipt and asks the model", ENGINE,
     '        log.warning("[%s] product module unavailable: %s", project.name, ctx.reason)\n'
     "        return unavailable(language=lang)\n",
     '        log.warning("[%s] product module unavailable: %s", project.name, ctx.reason)\n'),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("an answer the model could not give is passed on as one", ENGINE,
     "    if not answer.ok:\n        return unavailable(language=lang)",
     "    if False:\n        return unavailable(language=lang)"),

    # RE-PINNED 2026-09-24: moved to engine.py
    # RE-PINNED 2026-09-24 (#266 slice 3): the read-only path says the same sentence twice, so the
    # turn's own import before it is what pins the TURN's
    ("a crash goes silent", ENGINE,
     "        from openfactory.product.voice import broke\n\n"
     '        reply = broke(language=getattr(project, "language", None))',
     "        from openfactory.product.voice import broke\n\n"
     "        reply = None"),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("a crash is not paged", ENGINE,
     '        log.error("OPENFACTORY_PRODUCT_MUTE project=%s thread=%s — the client got no "',
     '        log.error("product channel mute project=%s thread=%s — the client got no "'),

    # RE-PINNED 2026-09-24: moved to engine.py
    # RE-PINNED 2026-09-24 (#266 slice 3): the read-only path carries the same guard, so the turn's
    # record before it pins the TURN's
    # RE-PINNED 2026-09-24 (#266 slice 4): the call ends on what the message replies to now
    ("the person's turn failing to record costs the answer", ENGINE,
     "                                       in_reply_to=message.in_reply_to) or \"\"\n"
     "    except Exception:  # noqa: BLE001 — the record must never cost the person their answer",
     "                                       in_reply_to=message.in_reply_to) or \"\"\n"
     "    except ValueError:  # the record must never cost the person their answer"),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("a judge that raises costs the turn", ENGINE,
     "        except Exception:  # noqa: BLE001 — an unreadable judgment leaves the proposal "
     "pending",
     "        except ValueError:  # an unreadable judgment leaves the proposal pending"),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("closing the decisions she asked for, failing, costs the answer", ENGINE,
     "        except Exception:  # noqa: BLE001 — bookkeeping must never cost the reply",
     "        except ValueError:  # bookkeeping must never cost the reply"),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("recording the decisions she asked for, failing, costs the answer", ENGINE,
     "        except Exception:  # noqa: BLE001\n"
     '            log.warning("[%s] could not record the decisions she asked for — "',
     "        except ValueError:\n"
     '            log.warning("[%s] could not record the decisions she asked for — "'),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("the intake case, failing, costs the answer", ENGINE,
     "    except Exception:  # noqa: BLE001 — the case is bookkeeping; the reply is the act",
     "    except ValueError:  # the case is bookkeeping; the reply is the act"),

    ("buttons the transport failed to post cost the proposal", CH,
     "    except Exception:  # noqa: BLE001 — the affordance is optional; the proposal is not",
     "    except ValueError:  # the affordance is optional; the proposal is not"),

    # ── 14. a reply that claims a write ──────────────────────────────────────────────────────────
    # RE-PINNED 2026-09-24: moved to engine.py
    ("a reply claiming a write goes unobserved", ENGINE,
     "    if claim:\n", "    if False:\n"),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("a reply claiming a write is corrected in front of the client", ENGINE,
     '    claim = claims_a_write(getattr(answer, "text", "") or "")\n',
     '    claim = claims_a_write(getattr(answer, "text", "") or "")\n'
     '    answer = answer.model_copy(update={"text": answer.text + " (nada foi gravado)"}) '
     "if claim else answer\n"),

    # ── what she asks a person, and what closes it ───────────────────────────────────────────────
    # RE-PINNED 2026-09-24: moved to engine.py
    ("what she asks a person to decide is never tracked", ENGINE,
     '    if getattr(answer, "decisions", None):', "    if False:"),

    # RE-PINNED 2026-09-24: moved to engine.py
    # RE-PINNED 2026-09-24 (#266 slice 4): the call carries whom the decision is asked of, on
    # the line after
    ("a decision is opened about no conversation", ENGINE,
     "            module.record_decisions(answer.decisions, channel=channel,\n",
     '            module.record_decisions(answer.decisions, channel="",\n'),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("a message she reads no longer closes what she asked", ENGINE,
     "    ex.close_decisions_if_she_reads_this()\n",
     ""),

    # RETIRED 2026-09-24 (#266 slice 4): "…and the reverse: decisions close only in their own
    # conversation (slice 4, unannounced)". It scoped the close by the ROOM alone, to prove the pin
    # was a pin; slice 4 scopes it by the person the decision was asked of and the conversation it
    # was asked in, so the row's change is less than the code now and cuts nothing it holds. The
    # pin is flipped, and the row below puts the old behaviour back instead.

    # #266 SLICE 4, THE SCOPED CLOSE — the old rule back: any message closes every open decision
    ("any message closes every open decision of the project again (slice 4 undone)", MODULE,
     "        if person or conversation:\n"
     "            live = [x for x in live if _answered_by(",
     "        if False:\n"
     "            live = [x for x in live if _answered_by("),

    # ── the intake ───────────────────────────────────────────────────────────────────────────────
    # RE-PINNED 2026-09-24: moved to engine.py
    ("the model is never handed the intake", ENGINE,
     '                           **({"intake": intake} if intake and _accepts_intake(module) '
     "else {}))",
     "                           **{})"),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("a turn never joins the intake case", ENGINE,
     "        _case.note_turn(project, thread, user, text, answer)", "        pass"),
]
