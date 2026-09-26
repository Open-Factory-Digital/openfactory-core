"""Mutation plan for #266 slice 4 — the speaker and the reply (ADR-0051 D1's `speaker` and
`in_reply_to`, D11's staging and decision scoping, D5/D9's no names across conversations).

Each row takes away one rule this slice stands on; every row must turn its test file red. In the
brief's order: the speaker as a person with a role per product; `in_reply_to` kept in the
transcript; staging keyed by the conversation AND the person, with the confirmation bound to the
requester and `accept_on_behalf` the one door past it — typed, clicked, and from a process that
never staged the draft; a decision closed only by the person it was asked of, where it was asked;
and no name across conversations — the glossary, the sweep's "already noted", the key and the
token, the decision's scope.

The rows run against `tests/test_the_speaker_and_the_reply.py`; the one that lays the expiry's
tombstone on the conversation runs against the characterisation suite, which pins the late "sim"
that tombstone is for. The two rows that put slice 4's flipped pins back as they were live in
`266_the_conversation_is_pinned.py`, beside the pins.
"""

TEST = "tests/test_the_speaker_and_the_reply.py"
PINNED = "tests/test_the_conversation_is_pinned.py"

ENGINE = "openfactory/product/engine.py"
STAGING = "openfactory/product/staging.py"
CONFIRM = "openfactory/product/confirm.py"
MODULE = "openfactory/product/module.py"
CASE = "openfactory/product/case.py"
SPEAKER = "openfactory/product/speaker.py"
ROLE = "openfactory/product/role.py"
DOMAIN = "openfactory/product/domain.py"
TRANSCRIPT = "openfactory/memory/transcript.py"

MUTATIONS = [
    # ── the speaker is a person with a role in the product ───────────────────────────────────────
    ("an engineer is read as whatever else they are — `engineers` is never looked at", SPEAKER,
     "    if who in engineers:\n", "    if False:\n"),
    ("a product admin is spoken to as a client", SPEAKER,
     "    return Person(id=who, role=ADMIN if approver else CLIENT, approver=approver)",
     "    return Person(id=who, role=CLIENT, approver=approver)"),
    ("an allowlist that cannot be read makes everybody an approver", SPEAKER,
     "        approver = False\n", "        approver = True\n"),
    ("the engine never tells the answer who is speaking", ENGINE,
     '                           **({"speaker": ex.person} if _accepts(module.answer, "speaker") '
     "else {}),\n",
     ""),
    ("the module drops the speaker on the way to the role", MODULE,
     '            **({"speaker": speaker} if speaker is not None else {}),\n', ""),
    ("the role's prompt never says who is speaking", ROLE,
     '            + (f"{who}\\n\\n" if (who := render_speaker(speaker)) else "")\n', ""),
    ("a client is not told their yes records nothing — the role may promise them a write",
     SPEAKER,
     "    elif not speaker.approver:\n", "    elif False:\n"),

    # ── in_reply_to kept in the transcript ───────────────────────────────────────────────────────
    # RE-PINNED 2026-09-25 (#336): the person's line records the files it carried too
    ("the person's turn forgets which message it is and what it replies to", ENGINE,
     "                                       actor=user, channel=channel, message_id=message.id,\n"
     "                                       in_reply_to=message.in_reply_to,\n"
     '                                       **_files_of(message)) or ""',
     '                                       actor=user, channel=channel,\n'
     '                                       **_files_of(message)) or ""'),
    ("the role's turn forgets which message it answers", ENGINE,
     "            # proposal she made, whichever way it reaches the person\n"
     '            transcript.record(project, thread=thread, role="agent", text=_text_of(reply),\n'
     "                              channel=channel, in_reply_to=message.id)",
     "            # proposal she made, whichever way it reaches the person\n"
     '            transcript.record(project, thread=thread, role="agent", text=_text_of(reply),\n'
     "                              channel=channel)"),
    ("the transcript writes neither id onto the row it was handed them for", TRANSCRIPT,
     '        if message_id:\n            extra["id"] = str(message_id)\n'
     '        if in_reply_to:\n            extra["in_reply_to"] = str(in_reply_to)\n',
     ""),
    # RE-PINNED 2026-09-24 (#266 slice 6): the reader carries `addressed` after the two ids now,
    # so the two lines end in a comma and the cut leaves that argument standing
    ("the transcript's reader drops both ids", TRANSCRIPT,
     '              id=str((r.get("extra") or {}).get("id", "") or ""),\n'
     '              in_reply_to=str((r.get("extra") or {}).get("in_reply_to", "") or ""),\n',
     ""),

    # ── staging keyed by the conversation and the person ─────────────────────────────────────────
    ("a turn stages under the conversation alone — a second request displaces the first person's",
     ENGINE,
     "        self.key = key_for(message.conversation, message.speaker)",
     "        self.key = message.conversation"),
    ("the key holds the person's own id — a name travels on every token and every button",
     STAGING,
     "    person = sealed(person)\n", '    person = str(person or "").strip()\n'),
    ("a person's own proposal is not looked for first — an older anonymous one is taken",
     STAGING,
     "    tried: set[str] = set()\n    if person:\n",
     "    tried: set[str] = set()\n    if False:\n"),
    ("the room's scan takes somebody else's newest before the speaker's own", STAGING,
     "    own = [kv for kv in staged if person and requester_of(kv[1]) == person]",
     "    own = []"),
    ("a proposal another process staged is never found for somebody else's yes", STAGING,
     "    for key, entry in _stored(project):", "    for key, entry in []:"),
    ("the entry never says whose it is — the queue, which has no `asked_by`, is anybody's",
     STAGING,
     '        entry["requester"] = str(person)\n', ""),
    ("the entry's conversation is its key — the requester's intake case never moves", STAGING,
     '        entry["conversation"] = _stem(thread, person)\n',
     '        entry["conversation"] = thread\n'),
    ("the panel's pending row names the key where it named the conversation", STAGING,
     "                             channel=where, payload=_freeze(entry))",
     "                             channel=thread, payload=_freeze(entry))"),
    ("the case a staging moves is anybody's in the conversation — another person's intake is "
     "taken", CASE,
     "    return not person or case.opened_by == person", "    return True"),
    ("an expired proposal keyed by its person lays no tombstone where a late typed yes looks",
     STAGING,
     "            if where != thread:\n                _EXPIRED_TOMBSTONES[where] = time.time()",
     "            if False:\n                _EXPIRED_TOMBSTONES[where] = time.time()",
     PINNED),

    # ── the confirmation bound to the requester ──────────────────────────────────────────────────
    ("any admin's typed yes confirms a draft somebody else asked for", CONFIRM,
     "    refused = not_theirs(project, entry, user)\n"
     "    if refused:\n"
     "        return refused\n",
     ""),
    ("an admin's click on somebody else's proposal is not refused by name — the panel records a "
     "decision", CONFIRM,
     "    refused = not_theirs(project, entry, user)\n"
     "    if refused:\n"
     '        return "unauthorized", refused\n',
     ""),
    ("`accept_on_behalf` is never read — no admin can confirm for the requester", CONFIRM,
     '    if getattr(getattr(project, "product", None), "accept_on_behalf", False):\n'
     '        return ""\n',
     ""),
    ("`accept_on_behalf` also lets somebody off the admin list confirm", CONFIRM,
     "    if not may_act(project, user, via=via):\n"
     "        return unauthorized_message(project)\n\n"
     "    from openfactory.product.staging import consume\n",
     "    if not may_act(project, user, via=via) and not getattr(\n"
     '            getattr(project, "product", None), "accept_on_behalf", False):\n'
     "        return unauthorized_message(project)\n\n"
     "    from openfactory.product.staging import consume\n"),
    ("the requester is found INSIDE a mention again — `ana` confirms for `<@joana>`", CONFIRM,
     "    return bool(user) and requester_of(entry) == user",
     '    return bool(user) and any(user in str(entry.get(k) or "")\n'
     '                              for k in ("asked_by", "said_by", "reported_by", "actor"))'),
    ("somebody whose id sits inside the requester's confirms for them", CONFIRM,
     "    if not requester or requester == user:", "    if not requester or user in requester:"),
    ("the admins are named under a proposal their yes cannot confirm", ENGINE,
     '    if not getattr(cfg, "accept_on_behalf", False):\n        return ""\n', ""),

    # ── a decision closed only by the person it was asked of, where ──────────────────────────────
    ("any message closes every open decision again", MODULE,
     "        if person or conversation:\n"
     "            live = [x for x in live if _answered_by(",
     "        if False:\n"
     "            live = [x for x in live if _answered_by("),
    ("the engine closes decisions for nobody in particular", ENGINE,
     "                **_scoped(self.module.close_decisions_answered, self.thread, self.user))",
     "                )"),
    ("the engine opens decisions as asked of nobody — the room's next message answers them",
     ENGINE,
     "                                    **_scoped(module.record_decisions, thread, user))",
     "                                    )"),
    ("one answer closes the same decision asked of two people", MODULE,
     '            live, {(DECISION, x.subject, x.about): "answered" for x in live})',
     '            ledger, {(DECISION, x.subject, x.about): "answered" for x in live})'),
    ("the same decision asked of a second person is folded into the first's", MODULE,
     "                   if x.kind == DECISION and (not scope or _scope_of(x) == scope)}",
     "                   if x.kind == DECISION}"),
    # RE-PINNED 2026-09-25 (#335): a private conversation is sealed by its owner
    ("whom a decision was asked of is kept by name", MODULE,
     '    return {"asked_of": who, "asked_in": sealed(owner_of(conversation))}',
     '    return {"asked_of": str(person), "asked_in": sealed(owner_of(conversation))}'),
    ("a decision opened before this slice closes on a message anywhere", MODULE,
     "        return loop.about == room", "        return True"),

    # ── no name across conversations ─────────────────────────────────────────────────────────────
    ("the glossary carries who told each fact into every conversation's prompt", DOMAIN,
     '    rows = ["| termo | status |", "|---|---|"]\n'
     "    for f in sorted(live, key=lambda x: x.term.lower())[:limit]:\n"
     '        rows.append(f"| {f.term} | {f.status} |")',
     '    rows = ["| termo | status | fonte |", "|---|---|---|"]\n'
     "    for f in sorted(live, key=lambda x: x.term.lower())[:limit]:\n"
     "        rows.append(f\"| {f.term} | {f.status} | {f.source or '—'} |\")"),
    ("the role is told to say who told it a learned fact", ROLE,
     '                "never authoritative — when you use one, say it is what you were told in a "',
     '                "ATTRIBUTED, never authoritative — say who told you when you use one. When '
     'you use one, say it is what you were told in a "'),
    ("the card sweep's \"already noted\" names who said it", MODULE,
     '                                   detail=f"já tenho isto anotado sobre {term!r}: "',
     '                                   detail=f"já tenho isto anotado sobre {term!r} (por '
     '{existing.source}): "'),
    ("a click is recorded under the proposal's key, not in its conversation", CONFIRM,
     "    where = conversation_of(key, entry)", "    where = key"),
]
