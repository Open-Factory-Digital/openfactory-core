"""Mutation plan for #266 slice 3 — one door, parallel conversations (ADR-0051 D1–D6, D13).

Each row takes away one rule the door, the conversation's workflow, the ceiling or the product's
memory stands on; every row must turn its test file red. The rows the brief names, in its order:
the deduplication, the serial turn, the debounce and the coalescing (and nobody jumping the queue),
the anonymity of the acknowledgement, the ceiling, the bound, the product keying and the read of
the partition the registry projects held before the move — and after them the rest of what this
slice promises: the retry that keeps a message across a worker restart, what continue-as-new
carries, the fast path, the acknowledgement reaching a chat transport before the answer, and the
two ways a result comes back through the door.

The conversation's rows run against `tests/test_the_one_door.py`, on Temporal's own test server;
the memory's rows against `tests/test_one_memory_per_product.py`.
"""

TEST = "tests/test_the_one_door.py"
MEMORY_TEST = "tests/test_one_memory_per_product.py"

CONVERSATION = "openfactory/runtime/temporal/conversation.py"
ACTIVITIES = "openfactory/runtime/temporal/activities.py"
DOOR = "openfactory/product/door.py"
CAP = "openfactory/product/cap.py"
ENGINE = "openfactory/product/engine.py"
VOICE = "openfactory/product/voice.py"
TRANSCRIPT = "openfactory/memory/transcript.py"

MUTATIONS = [
    # ── the deduplication ────────────────────────────────────────────────────────────────────────
    ("a message sent twice is two turns — the id is not the key", CONVERSATION,
     "        if arrival.id in self._known:\n",
     "        if False:\n"),
    # RE-PINNED 2026-09-24 (#266 slice 5): continue-as-new carries the conversation's number too,
    # on the line after
    ("continue-as-new forgets the ids it has seen, so a retry after the move is a second turn",
     CONVERSATION,
     "            seen=list(self._seen), outbox=list(self._outbox), pending=list(self._pending),\n",
     "            seen=[], outbox=list(self._outbox), pending=list(self._pending),\n"),

    # ── one turn at a time inside a conversation ─────────────────────────────────────────────────
    ("the next turn starts beside the one still running — a conversation answers two at once",
     CONVERSATION,
     "            await self._take(self._next_turn())\n",
     "            self._keep(asyncio.create_task(self._take(self._next_turn())))\n"),

    # ── the debounce, the coalescing, and nobody jumping the queue ───────────────────────────────
    ("a turn starts on a speaker's first line, never hearing out the burst", CONVERSATION,
     "        if self._debounce <= 0:\n            return\n",
     "        if True:\n            return\n"),
    ("each line of a burst is its own turn — nothing is coalesced", CONVERSATION,
     "        turn = [a for a in self._pending if _speaker(a) == head]\n"
     "        self._pending = [a for a in self._pending if _speaker(a) != head]\n",
     "        turn = self._pending[:1]\n"
     "        self._pending = self._pending[1:]\n"),
    ("the turn goes to whoever wrote LAST — the newest message jumps the queue", CONVERSATION,
     "        head = _speaker(self._pending[0])\n        turn = [",
     "        head = _speaker(self._pending[-1])\n        turn = ["),

    # ── the acknowledgement: at once, and naming nobody ──────────────────────────────────────────
    ("the busy acknowledgement grows a place for the name of whoever the role is answering",
     VOICE,
     '    "pt-BR": "recebi sua mensagem — a próxima resposta é a sua.",',
     '    "pt-BR": "recebi sua mensagem — estou com {who}; a próxima resposta é a sua.",'),
    ("a message with turns in front of it is told nothing of where it stands", DOOR,
     "        return voice.you_are_next(ahead=ahead, language=lang, agent_name=agent)\n",
     "        return \"\"\n"),
    ("the chat transport hears the acknowledgement only beside the answer, if at all", DOOR,
     "    if acknowledged is not None:\n        try:\n            acknowledged(ack)\n",
     "    if False:\n        try:\n            acknowledged(ack)\n"),

    # ── the ceiling ──────────────────────────────────────────────────────────────────────────────
    ("a turn takes no slot at all — the ceiling is gone", ACTIVITIES,
     "    with ceiling().hold(inp.product, abandoned=abandoned):\n",
     "    if abandoned is not None:\n"),
    ("the ceiling is kept per REGISTRY project, so one product's two projects each get their own",
     ACTIVITIES,
     "    with ceiling().hold(inp.product, abandoned=abandoned):\n",
     "    with ceiling().hold(inp.project, abandoned=abandoned):\n"),
    ("every product shares one product's slots — the ceiling orders products behind each other",
     CAP,
     "        mine = self._of(product)\n",
     "        mine = self._of(\"\")\n"),
    ("the deployment's ceiling is a hundred times what was declared", CAP,
     "        self._deployment = threading.BoundedSemaphore(per_deployment)\n",
     "        self._deployment = threading.BoundedSemaphore(per_deployment * 100)\n"),

    # ── the bound, and the way back through the door ─────────────────────────────────────────────
    ("a turn holds its conversation for as long as it runs — no bound", CONVERSATION,
     "            await workflow.wait_condition(handle.done, timeout=timedelta(seconds=self._bound))",
     "            await workflow.wait_condition(handle.done)"),
    ("past the bound the conversation still waits for the turn it handed off", CONVERSATION,
     "            self._keep(asyncio.create_task(self._report_later(handle, work, last)))\n",
     "            await self._report_later(handle, work, last)\n"),
    ("the late answer is published in place, never coming back through the door", CONVERSATION,
     "                await workflow.execute_activity(\n"
     "                    conversation_report,\n",
     "                self._publish([*work.ids], replies, final=True)\n"
     "                return\n"
     "                await workflow.execute_activity(\n"
     "                    conversation_report,\n"),
    ("the first pass's outcome is never told to the conversation that asked", ENGINE,
     "            told = door.tell(project, conversation=where, text=text, room=room,\n"
     "                             in_reply_to=asked, addressed_to=user)\n",
     "            told = False\n"),
    ("an internal event is published without being recorded — memory misses what the role said",
     DOOR,
     "        transcript.record(project, thread=conversation, role=\"agent\", text=said, "
     "channel=room)\n",
     "        pass\n"),

    # ── a worker restart, and continue-as-new ────────────────────────────────────────────────────
    ("a turn whose worker died is never run again — the message is lost with the process",
     CONVERSATION,
     "TURN_RETRY = RetryPolicy(maximum_attempts=2, initial_interval=timedelta(seconds=1))",
     "TURN_RETRY = RetryPolicy(maximum_attempts=1, initial_interval=timedelta(seconds=1))"),
    # RE-PINNED 2026-09-24 (#266 slice 5): continue-as-new carries the conversation's number too,
    # on the line after
    ("continue-as-new drops what it published, so a retry after the move reads no answer",
     CONVERSATION,
     "            seen=list(self._seen), outbox=list(self._outbox), pending=list(self._pending),\n",
     "            seen=list(self._seen), outbox=[], pending=list(self._pending),\n"),

    # ── the fast path, and what the door refuses ─────────────────────────────────────────────────
    ("a read waits its turn behind a busy conversation", DOOR,
     "    arrival = _arrival(message, project, fast=not event and reads_only(message.text),\n",
     "    arrival = _arrival(message, project, fast=False,\n"),
    ("an empty message is enqueued as a turn", DOOR,
     "    if not said:\n"
     "        return \"say something to the product role — an empty message is not a turn.\"\n",
     ""),

    # ── the product is the key ───────────────────────────────────────────────────────────────────
    ("the door keys a conversation by REGISTRY project — one product, two queues", DOOR,
     "    key = product_key(project)\n",
     "    key = f\"project:{project.name}\"\n"),
    ("memory is kept per REGISTRY project again — one product remembered by halves", TRANSCRIPT,
     "        return product_key(project)\n",
     "        return f\"project:{project.name}\"\n",
     MEMORY_TEST),

    # ── the read-through of the partitions the registry projects held before the move ─────────────
    ("the rows written before the move are not read — the history before the deploy is gone",
     TRANSCRIPT,
     "            if mark == where.key or (not mark and name in where.members):\n",
     "            if mark == where.key:\n",
     MEMORY_TEST),
    ("an unmarked row is read from any partition — a project named like a product key leaks in",
     TRANSCRIPT,
     "            if mark == where.key or (not mark and name in where.members):\n",
     "            if mark == where.key or not mark:\n",
     MEMORY_TEST),
    ("the product's members' old partitions are never asked", TRANSCRIPT,
     "    for name in dict.fromkeys((where.key, *where.members)):\n"
     "        got = records_of_kind(",
     "    for name in (where.key,):\n"
     "        got = records_of_kind(",
     MEMORY_TEST),
    ("a deletion leaves the rows still under a member's own name", TRANSCRIPT,
     "    for name in dict.fromkeys((where.key, *where.members)):\n"
     "        gone += forget_project(",
     "    for name in (where.key,):\n"
     "        gone += forget_project(",
     MEMORY_TEST),
    ("a deletion by partition takes the rows of whoever shares the partition's name",
     TRANSCRIPT,
     "    if where.shadowed:\n        raise ValueError(\n",
     "    if False:\n        raise ValueError(\n",
     MEMORY_TEST),
]
