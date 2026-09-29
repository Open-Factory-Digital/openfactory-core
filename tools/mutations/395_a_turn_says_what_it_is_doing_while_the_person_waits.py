"""A turn says what it is doing while the person waits (#395).

ROWS 1-4 ARE THE ENGINE GOING QUIET AGAIN: a stage the person waits through is not told (the
conversation, the model, the draft), or the turn never installs the sink it was handed — the
receipt, then minutes of nothing, which is what a person read as a broken product.

ROWS 5-6 ARE THE HOOK: a sink that raises takes the answer down with it, and a stage no language
has words for reaches a surface as its key.

ROW 7 IS THE HAND-OFF FORGETTING THE STAGE — the one word a chat add-on hears while it waits.

ROWS 8-12 ARE THE WORKER: the loop waits for the whole turn before it tells anything (the shape the
first draft of this change had — `asyncio.wait` defaults to ALL_COMPLETED), a tell that failed is
tried on every stage, the heartbeat waits for the tell again (review of #398: a slow status signal
held the beat for as long as it took — 8.31 s for an 8 s tell, no ceiling — and at
`conversation.HEARTBEAT` the engine re-runs the turn), a tell that never answers is held until the
turn ends instead of given up at `_TELL_WITHIN`, and the activity hands the turn no sink at all.

ROWS 13-16 ARE THE CONVERSATION: the hand-off is composed without the stage it holds, a stage for a
turn it is not waiting on is kept, the running turn's stage outlives its answer, and a turn past
its bound is not counted as at work.

ROWS 17-18 ARE THE PANEL'S SOCKET: a turn past its bound reads as idle — the silence #395 measured
began exactly there — and an idle role still carries the last stage it said.

THE LAST ROW IS THE PAGE: the stage arrives and the page still says "is thinking…".
"""

TEST = "tests/test_a_turn_says_what_it_is_doing_while_the_person_waits.py"

ENGINE = "openfactory/product/engine.py"
PROGRESS = "openfactory/product/progress.py"
VOICE = "openfactory/product/voice.py"
ACTIVITIES = "openfactory/runtime/temporal/activities.py"
CONVERSATION = "openfactory/runtime/temporal/conversation.py"
CHAT = "openfactory/api/product_chat.py"
PANEL = "openfactory/api/panel.html"

MUTATIONS = [
    ("the conversation and the memory are read with no word of it", ENGINE,
     '    ex.progress("reading")\n',
     "\n"),
    ("the model answers for minutes with no word of it", ENGINE,
     '    ex.progress("answering")\n',
     "\n"),
    ("the draft is written with no word of it", ENGINE,
     '    _progress.stage("drafting")    # a model call of its own',
     "    # a model call of its own"),
    ("the turn is handed a sink and never installs it", ENGINE,
     "        with _progress.reporting(progress):\n",
     "        with _progress.reporting(None):\n"),

    ("a sink that raises takes the answer down with it", PROGRESS,
     "    try:\n        sink(name, dict(counts))\n",
     "    sink(name, dict(counts))\n    try:\n        pass\n"),
    ("a stage no language has words for reaches the surface as its key", PROGRESS,
     "    if name not in STAGES:\n",
     "    if False:\n"),

    ("the hand-off forgets the stage it was handed", VOICE,
     "    if stage.strip():\n        return sig + _pick(_HANDED_OFF_AT, language)",
     "    if False:\n        return sig + _pick(_HANDED_OFF_AT, language)"),

    ("the worker waits for the whole turn before it tells a single stage", ACTIVITIES,
     "            await asyncio.wait(waiting, timeout=_TURN_PULSE,\n"
     "                               return_when=asyncio.FIRST_COMPLETED)\n",
     "            await asyncio.wait(waiting, timeout=_TURN_PULSE)\n"),
    ("a tell that failed is tried again on every stage", ACTIVITIES,
     "                if failed is not None:  # a status must never cost the turn\n"
     "                    telling = False\n",
     "                if failed is not None:  # a status must never cost the turn\n"
     "                    pass\n"),
    ("the heartbeat waits for the tell, so a slow status re-runs the turn", ACTIVITIES,
     "                out = asyncio.ensure_future(asyncio.wait_for(tell(*stages.told),\n"
     "                                                             timeout=_TELL_WITHIN))\n",
     "                await tell(*stages.told)\n"),
    ("a tell that never answers is held until the turn ends", ACTIVITIES,
     "                out = asyncio.ensure_future(asyncio.wait_for(tell(*stages.told),\n"
     "                                                             timeout=_TELL_WITHIN))\n",
     "                out = asyncio.ensure_future(tell(*stages.told))\n"),
    ("the activity hands the turn no sink", ACTIVITIES,
     "                                                                  progress=stages.say),\n",
     "                                                                  progress=None),\n"),

    ("the hand-off is composed without the stage the conversation holds", CONVERSATION,
     "                                                            stage=at),\n",
     '                                                            stage=""),\n'),
    ("a stage for a turn the conversation is not waiting on is kept", CONVERSATION,
     "        if step.turn not in self._working:\n            return\n",
     "        if False:\n            return\n"),
    ("the running turn's stage outlives its answer", CONVERSATION,
     "        self._working.pop(work.id, None)\n        self._publish(ids, self._replies_of(",
     "        self._publish(ids, self._replies_of("),
    ("a turn past its bound is not counted as at work", CONVERSATION,
     '                "working": len(self._working), "stage": self._stage_now()}',
     '                "working": 0, "stage": self._stage_now()}'),

    ("a turn past its bound reads as a role with nothing to do", CHAT,
     "            or int(raw.get(\"working\") or 0) > 0)\n",
     "            or False)\n"),
    ("an idle role still carries the last stage it said", CHAT,
     '    stage = str(raw.get("stage") or "").strip() if busy else ""\n',
     '    stage = str(raw.get("stage") or "").strip()\n'),

    ("the stage arrives and the page still says it is thinking", PANEL,
     "                                 :p.stage?`${a} — ${p.stage}…`:`${a} is thinking…`;",
     "                                 :false?`${a} — ${p.stage}…`:`${a} is thinking…`;"),
]
