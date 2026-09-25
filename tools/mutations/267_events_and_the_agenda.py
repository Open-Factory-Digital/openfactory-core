"""Mutation plan for #267 slice 3 — events and the agenda (ADR-0052).

Each row takes away one rule this slice stands on; every row must turn its test file red. In the
order of the slice's acceptance and its security rules:

  - an event cannot be forged from outside: the door every transport reaches refuses one, and the
    factory's own paths are the only way in;
  - a proactive message waits its turn in the conversation's line — never inside a turn, never
    coalesced into a person's words, never counted as somebody's place in the queue;
  - a delivered card is announced when the job that delivered it ends, in its requester's
    conversation, once — the board deciding what was delivered, the ledger what was said;
  - the weekly sweep is the catch-all, and says nothing twice;
  - the other events are said once each, to the requester else the room;
  - the agenda: one rule for who sees an item, on the panel, on the operator's list, in the role's
    own facts, and in which acceptance a reply may answer;
  - where a delivery is announced is read off what was staged, and handed down every filing path;
  - nobody is named, and no event sentence speaks the factory's words.

Every row runs against `tests/test_events_and_the_agenda.py` except the late answer's, which is
the door's own proof (`tests/test_the_one_door.py`, on Temporal's test server).
"""

TEST = "tests/test_events_and_the_agenda.py"
DOOR_TEST = "tests/test_the_one_door.py"

DOOR = "openfactory/product/door.py"
CONVERSATION = "openfactory/runtime/temporal/conversation.py"
EVENTS = "openfactory/product/events.py"
AGENDA = "openfactory/product/agenda.py"
ACTIVITIES = "openfactory/runtime/temporal/activities.py"
MODULE = "openfactory/product/module.py"
ENGINE = "openfactory/product/engine.py"
CONFIRM = "openfactory/product/confirm.py"
FOLLOWUP = "openfactory/product/followup.py"
VOICE = "openfactory/product/voice.py"
APP = "openfactory/api/app.py"
CATALOG = "openfactory/actions/catalog.py"
PANEL = "openfactory/api/panel.html"

MUTATIONS = [
    # ── an event cannot be forged from outside ───────────────────────────────────────────────────
    ("the people's door takes an event again — a transport can forge 'your card is ready'", DOOR,
     '    if message.replies or str(message.via or "").strip().lower() == EVENT:\n',
     "    if False:\n"),
    ("a message that says it came through the event transport is let in", DOOR,
     '    if message.replies or str(message.via or "").strip().lower() == EVENT:\n',
     "    if message.replies:\n"),
    ("the late answer is handed to the people's door, which refuses it", DOOR,
     '    return await _admit(Message(id=id, project=getattr(project, "name", "") or "",\n',
     '    return await receive(Message(id=id, project=getattr(project, "name", "") or "",\n',
     DOOR_TEST),

    # ── the door's path for what happened ────────────────────────────────────────────────────────
    ("an announcement the door refused is recorded as said", DOOR,
     "                  conversation, ack.reason)\n        return ack\n",
     "                  conversation, ack.reason)\n"),
    ("an announcement enters as an answer, published the moment it arrives", DOOR,
     "        ack = await _admit(event, project=project, client=client, kind=EVENT_KIND)\n",
     "        ack = await _admit(event, project=project, client=client)\n"),
    ("the door drops what kind of item it enqueues", DOOR,
     '                       kind=kind if event else "")\n',
     '                       kind="")\n'),

    # ── a proactive message waits its turn ───────────────────────────────────────────────────────
    ("an event is published the moment it arrives, inside the turn in progress", CONVERSATION,
     "        if _happened(arrival) and arrival.replies:\n",
     "        if False:\n"),
    ("an event counts as somebody's place in the queue", CONVERSATION,
     "        if not _happened(a) and _speaker(a) not in groups:\n",
     "        if _speaker(a) not in groups:\n"),
    ("an event at the head of the line is turned like a person's message", CONVERSATION,
     "        if _happened(self._pending[0]):\n            return [self._pending.pop(0)]\n",
     "        if False:\n            return [self._pending.pop(0)]\n"),
    ("an event is coalesced into the next person's turn", CONVERSATION,
     "        turn = [a for a in self._pending if not _happened(a) and _speaker(a) == head]\n",
     "        turn = [a for a in self._pending if _happened(a) or _speaker(a) == head]\n"),
    ("an event's turn publishes nothing", CONVERSATION,
     "        self._joined = True\n"
     "        self._publish([arrival.id], list(arrival.replies), final=True)\n",
     "        self._joined = True\n"),
    ("the role does not take part in a room it announced something in", CONVERSATION,
     "        self._joined = True\n"
     "        self._publish([arrival.id], list(arrival.replies), final=True)\n",
     "        self._publish([arrival.id], list(arrival.replies), final=True)\n"),

    # ── a delivered card, when it is delivered, where it was asked ──────────────────────────────
    ("the job's one exit no longer asks what it delivered", ACTIVITIES,
     "    if inp.state in _THE_CARD_IS_DONE:\n",
     "    if False:\n"),
    ("a job that parked asks what it delivered", ACTIVITIES,
     "_THE_CARD_IS_DONE = frozenset({JobState.DONE.value, JobState.MERGED.value})\n",
     "_THE_CARD_IS_DONE = frozenset({JobState.DONE.value, JobState.MERGED.value,\n"
     "                               JobState.ON_HOLD.value})\n"),
    ("a finished card never looks for the delivery it completes", EVENTS,
     '        if not _deliveries_of(loop_store.read(getattr(project, "name", "") or ""), card):\n',
     "        if True:\n"),
    ("the job's word is trusted when the board cannot be read", EVENTS,
     "        if delivered is None:\n            return []\n",
     "        if delivered is None:\n            delivered = {str(card)}\n"),
    ("a delivery is announced in the room, not where its requester asked", EVENTS,
     '                where = str((loop.context or {}).get("conversation") or "") '
     "or room_of(project)\n",
     "                where = room_of(project)\n"),
    ("a requirement is announced when SOME of its work is delivered", FOLLOWUP,
     "        if issues and issues <= closed_issues:\n",
     "        if issues and issues & closed_issues:\n"),
    ("a delivery the door did not take is closed as announced", EVENTS,
     "                             conversation=where, text=text):\n                    continue\n",
     "                             conversation=where, text=text):\n                    pass\n"),
    ("the acceptance forgets where it was asked", EVENTS,
     '                    **(asked.context or {}), "conversation": where,\n',
     "                    **(asked.context or {}),\n"),
    ("the oldest request on a card decides where its events go", EVENTS,
     "        for loop in reversed(_deliveries_of(rows, card)):\n",
     "        for loop in _deliveries_of(rows, card):\n"),

    # ── the sweep is the catch-all, and nothing is said twice ────────────────────────────────────
    ("the sweep no longer catches what an event missed", ACTIVITIES,
     "    told = events.deliver(project, delivered=_closed_issue_numbers(module))\n",
     "    told = []\n"),
    ("the telling reads every row, and announces a closed delivery again", EVENTS,
     "            open_now = waiting(loop_store.read(name), owner=OWNER)\n",
     "            open_now = loop_store.read(name)\n"),
    ("each telling of a delivery is a fresh event, so a retold one is two", EVENTS,
     "                if not _tell(project, id=_event_id(DELIVERED, project, *loop.key),\n",
     '                if not _tell(project, id=f"{DELIVERED}-{uuid.uuid4().hex}",\n'),
    ("a room post goes beside the door again", ACTIVITIES,
     "    del channel, cfg  # the product's room is read from the project, like every other gate "
     "here\n    if not events.to_room(project, text):\n",
     "    if not channel.say(project=project, channel=events.room_of(project), text=text):\n"),

    # ── the other events: once each, to the requester, else the room ─────────────────────────────
    ("what was told once is told again", EVENTS,
     '            if event_id in data["told"]:\n',
     "            if False:\n"),
    ("a red check is one event per card, not per pull request", EVENTS,
     "    return _once(project, _event_id(CI_RED, project, card, pr_url), lambda: (\n",
     "    return _once(project, _event_id(CI_RED, project, card), lambda: (\n"),
    ("the repair pass no longer tells the product role", ACTIVITIES,
     "    await asyncio.to_thread(_the_checks_went_red, inp)\n",
     ""),
    ("a pull request is said to wait the first time it is seen", EVENTS,
     "                if now - first >= PR_WAIT_HOURS * 3600:\n",
     "                if now - first >= 0:\n"),
    ("the wait is counted from the latest round, so it never reaches 48 h", EVENTS,
     '                first = float(data["seen"].setdefault(f"{card}|{pr}", now))\n',
     "                first = now\n"),
    ("the tech-lead's round hands no merge gate to the product role", ACTIVITIES,
     '                at_the_merge_gate.append((ticket, str(payload.get("pr_url"))))\n',
     "                pass\n"),
    ("a preview is said to the room, not to the card's requester", EVENTS,
     "        conversation_for(project, card),\n        voice.preview_up(",
     "        room_of(project),\n        voice.preview_up("),
    ("a document is said to the room even when it was brought elsewhere", EVENTS,
     "        conversation or room_of(project),\n",
     "        room_of(project),\n"),
    ("a project with no product role is told events anyway", EVENTS,
     '    return cfg is not None and bool(getattr(cfg, "enabled", True))\n',
     "    return True\n"),

    # ── the agenda: one rule for who sees an item ────────────────────────────────────────────────
    # RE-PINNED 2026-09-25 (#335): the viewer is read by its owner key
    ("a private item is seen by anybody", AGENDA,
     "    return bool(viewer.own) and _sealed(owner_of(viewer.own)) == where.conversation\n",
     "    return True\n"),
    ("the room's items reach a viewer who may not read the room", AGENDA,
     "        return viewer.may_read_room\n",
     "        return True\n"),
    ("a private conversation's delivery is read as the room's", AGENDA,
     "        if is_private(where):\n",
     "        if False:\n"),
    ("a decision asked in private is read as the room's", AGENDA,
     "        if asked_in == _sealed(room) or loop.about:\n",
     "        if True:\n"),
    ("an item never says 'you' to the person it is for", AGENDA,
     "    return bool(viewer.person) and bool(where.person) and _sealed(viewer.person) == "
     "where.person\n",
     "    return False\n"),
    ("the agenda carries the tech-lead's loops", AGENDA,
     "    for loop in sorted(waiting(rows, owner=OWNER), key=lambda x: x.ts):\n",
     "    for loop in sorted(waiting(rows), key=lambda x: x.ts):\n"),
    ("an item carries the person a question was put to", AGENDA,
     '        what = str(ctx.get("asked") or ctx.get("title") or "").strip()[:_WHAT_CHARS]\n',
     '        what = str(ctx.get("person") or ctx.get("asked") or ctx.get("title") or "")'
     ".strip()[:_WHAT_CHARS]\n"),
    ("the panel's agenda reads nobody's conversation, so a person's own items never show",
     CATALOG,
     '    viewer = agenda.Viewer(own=getattr(by, "conversation", "") or "", person=by.id,\n',
     '    viewer = agenda.Viewer(own="", person=by.id,\n'),
    ("the operator's list of loops carries everybody's private items", APP,
     "    loops = waiting(agenda.visible(loop_store.read(project), viewer, room=room))\n",
     "    loops = waiting(loop_store.read(project))\n"),
    # re-pinned 2026-09-24 (#269): the boot line reads the documents after the agenda
    ("the product page never reads its agenda", PANEL,
     "  if(_prod.project){paintScope();loadProductStatus();loadRequirements();loadAgenda();"
     "loadDocuments()}\n",
     "  if(_prod.project){paintScope();loadProductStatus();loadRequirements();loadDocuments()}\n"),
    ("the agenda is not read again when the role speaks", PANEL,
     "    pchatAgendaMoved();\n",
     ""),
    ("the status line counts somebody's private delivery", FOLLOWUP,
     "                          and audience(x, room=project_name).room])\n",
     "])\n"),

    # ── the role reads the agenda its conversation may see ───────────────────────────────────────
    ("the role's facts read everybody's loops", MODULE,
     "    return agenda.visible(loop_store.read(name), agenda.Viewer(own=conversation),\n"
     "                          room=events.room_of(project))\n",
     "    return loop_store.read(name)\n"),
    ("the facts pack is written for nobody's conversation", MODULE,
     '        self._conversation = str(conversation or "")\n',
     '        self._conversation = ""\n'),
    ("the engine never says which conversation it answers in", ENGINE,
     "        answering_in(thread)\n",
     '        answering_in("")\n'),

    # ── an acceptance is answered where it was asked ────────────────────────────────────────────
    ("an acceptance asked in private is answered from anywhere", MODULE,
     "    if conversation is None:\n        return open_acc\n",
     "    if True:\n        return open_acc\n"),
    ("the turn does not say where the reply was written", ENGINE,
     '            text, **({"conversation": thread}\n',
     '            text, **({"conversation": None}\n'),
    ("a did-it-work reminder is said to the room whatever conversation it was asked in",
     ACTIVITIES,
     "        if not where or where == room:\n",
     "        if True:\n"),
    ("a decision asked in private is chased in the room", ACTIVITIES,
     "                and agenda.audience(x, room=room).room]\n",
     "]\n"),

    # ── where a delivery is announced: read off what was staged, handed down ────────────────────
    ("the delivery forgets where it was asked", FOLLOWUP,
     '        out["conversation"] = str(conversation).strip()\n',
     "        pass\n"),
    ("the requester is written in clear on the delivery", FOLLOWUP,
     '        out["requester"] = sealed(requester)\n',
     '        out["requester"] = requester\n'),
    ("the confirmation stops handing the staged conversation to the filing", CONFIRM,
     '    return {"conversation": str(entry.get("conversation") or ""),\n',
     '    return {"conversation": "",\n'),
    ("the confirmation stops handing who asked to the filing", CONFIRM,
     '            "requester": requester_of(entry)}\n',
     '            "requester": ""}\n'),
    ("the filing forgets where it was asked on its way to the delivery", MODULE,
     "        self._open_delivery(requirement, results, conversation=conversation,\n"
     "                            requester=requester)\n",
     "        self._open_delivery(requirement, results)\n"),
    ("the defect's delivery forgets where it was reported", MODULE,
     "            self._track_defect(number, conversation=conversation, requester=requester)\n",
     "            self._track_defect(number)\n"),
    ("the official cards forget where the requirement was asked for", MODULE,
     "        return self.file_issues(requirement, actor=actor, tracker=tracker, board=board,\n"
     "                                conversation=conversation, requester=requester)\n",
     "        return self.file_issues(requirement, actor=actor, tracker=tracker, board=board)\n"),
    ("the breakdown forgets where the requirement was asked for", MODULE,
     "        return self.file_issues(requirement, actor=actor, board=board,\n"
     "                                conversation=conversation, requester=requester)\n",
     "        return self.file_issues(requirement, actor=actor, board=board)\n"),

    # ── nobody named, and none of the factory's words ───────────────────────────────────────────
    ("a red check is told in the factory's own words", VOICE,
     '    "pt-BR": ("{sig}{card} não passou nas verificações automáticas. O time já está '
     'corrigindo — "\n',
     '    "pt-BR": ("{sig}{card} não passou no CI do pull request. O time já está '
     'corrigindo — "\n'),
]
