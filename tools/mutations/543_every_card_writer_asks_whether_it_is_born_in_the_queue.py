"""Every writer that creates a card asks whether it would be born in the queue, and the Jira row
answers it (#543), proven by breaking it.

Run:  .venv/bin/python tools/mutate.py \
        tools/mutations/543_every_card_writer_asks_whether_it_is_born_in_the_queue.py

#536 taught the product role's three filing writers to ask, before they write, whether a card filed
now is born in the pickup column. Four more writers created cards without asking, and the Jira row
— whose create cannot choose a status — had the same defect and no answer. The claims, each a row:

  1. the one decision (`board.base.intake_held`): a card born in the queue is held, and so is one
     whose question raised — unsure is not "safe to spend";
  2. the board's own `card_create` asks before it opens a card to wait, refuses in the project's
     language — saying the person may open it IN the queue — and does not ask about a card the
     person opens in the queue;
  3. a split that keeps its children in the backlog creates none where they would be born queued,
     and a split that sends them straight to the queue is not asked;
  4. the factory's impediment is not filed where it would be born in the product's queue, and one
     on a board of its own — which nothing polls — is not asked;
  5. `preview propose --as-card` files nothing where the card would be born in the queue;
  6. the Jira row says where a new issue is born — the first status of the To Do category of the
     type it creates, the first listed when no category is named, `None` when unread, a declared
     status by name — and that the create cannot choose one; its doctor line keeps every other
     stage of the map; and a card already in the status it is placed in is placed.
"""

TEST = "tests/test_every_card_writer_asks_whether_it_is_born_in_the_queue.py"
BASE = "openfactory/adapters/board/base.py"
CATALOG = "openfactory/actions/catalog.py"
VOICE = "openfactory/product/voice.py"
SPLIT = "openfactory/runtime/temporal/activities.py"
IMPEDIMENT = "openfactory/ops/impediment.py"
PROPOSE = "openfactory/onboarding/preview_propose.py"
JIRA_BOARD = "openfactory/adapters/board/jira.py"
JIRA_TRACKER = "openfactory/adapters/tracker/jira.py"

MUTATIONS = [
    # 1. the one decision
    ("a card born in the queue is let through", BASE,
     "    if born is None or (born.column is not None and not born.queued):",
     "    if born is None or born.column is not None:"),
    ("a question that raised is read as safe to file", BASE,
     '        log.info("could not tell where a card created now would start (%s)", exc)\n'
     '        return Intake(column=None, queue="", queued=False)',
     '        log.info("could not tell where a card created now would start (%s)", exc)\n'
     "        return None"),

    # 2. the board's own card_create
    ("the board opens a card to wait without asking where it is born", CATALOG,
     "    if key == \"backlog\":\n"
     "        bad = await asyncio.to_thread(_born_in_the_queue, proj, tracker, board)\n"
     "        if bad:\n            return bad\n",
     ""),
    ("a card the person opens in the queue is refused too", CATALOG,
     '    if key == "backlog":\n        bad = await asyncio.to_thread(_born_in_the_queue,',
     "    if True:\n        bad = await asyncio.to_thread(_born_in_the_queue,"),
    ("an unread board opens the card", CATALOG,
     '    return refused(UNAVAILABLE, card_open_held("unread", language=lang), '
     "project=proj.name)",
     "    return None"),
    ("the refusal is said in English whatever the project speaks", CATALOG,
     '        return refused(CONFLICT, card_open_held("queue", column=str(born.column), '
     "language=lang),",
     '        return refused(CONFLICT, card_open_held("queue", column=str(born.column), '
     'language="en"),'),
    ("the English sentence drops the way the person has", VOICE,
     '"paid for — without anybody queueing it. To start it now, open it in "',
     '"paid for — without anybody queueing it. "'),
    ("the Portuguese sentence drops what it would have cost", VOICE,
     '"construído — e a custar — sem ninguém colocá-lo na fila. Para começar "',
     '"construído sem ninguém colocá-lo na fila. Para começar "'),

    # 3. a split's children
    ("a split that keeps its children in the backlog creates them where they are born queued",
     SPLIT,
     "    if not to_todo:\n        from openfactory.adapters.board.base import intake_held\n",
     "    if False:\n        from openfactory.adapters.board.base import intake_held\n"),
    ("a split that sends its children to the queue is held as well", SPLIT,
     "    if not to_todo:\n        from openfactory.adapters.board.base import intake_held\n",
     "    if True:\n        from openfactory.adapters.board.base import intake_held\n"),

    # 4. the factory's impediment
    ("the impediment is filed wherever it is born", IMPEDIMENT,
     "        held = _born_in_the_queue(project, trk)\n",
     '        held = ""\n'),
    ("an impediment on a board of its own is asked, and held", IMPEDIMENT,
     '    if declared is not None and getattr(declared, "tracker", None) != getattr(project, '
     '"tracker",\n',
     '    if False and getattr(declared, "tracker", None) != getattr(project, "tracker",\n'),

    # 5. the card onboarding proposes
    ("the preview card is filed wherever it is born", PROPOSE,
     "        if born is not None:\n            where = (",
     "        if False:\n            where = ("),

    # 6. the Jira row
    ("the Jira row no longer says where a new issue is born", JIRA_BOARD,
     "    def intake_column(self, state: str = \"\") -> str | None:",
     "    def _intake_column(self, state: str = \"\") -> str | None:"),
    ("the first status listed is read as the initial one, whatever its category", JIRA_BOARD,
     '        return next((n for n, c in statuses if c == "new"), statuses[0][0])',
     "        return statuses[0][0]"),
    ("a site that names no category is read by its last status", JIRA_BOARD,
     '        return next((n for n, c in statuses if c == "new"), statuses[0][0])',
     '        return next((n for n, c in statuses if c == "new"), statuses[-1][0])'),
    ("an unread Jira project answers that a new issue starts on no column", JIRA_BOARD,
     "        statuses = self._statuses_of_the_type()\n        if not statuses:\n"
     "            return None\n",
     "        statuses = self._statuses_of_the_type()\n        if not statuses:\n"
     '            return ""\n'),
    ("a declared status is matched with its case", JIRA_BOARD,
     "            return next((n for n, _c in statuses if n.casefold() == wanted), \"\")",
     "            return next((n for n, _c in statuses if n == wanted), \"\")"),
    ("the statuses read are another issue type's", JIRA_BOARD,
     '    mine = [t for t in listed if str(t.get("name") or "").strip().casefold() == kind] '
     "or listed",
     '    mine = [t for t in listed if str(t.get("name") or "").strip().casefold() != kind] '
     "or listed"),
    ("the doctor's Jira line unmaps every other stage", JIRA_BOARD,
     '        line = json.dumps({**named, "backlog": column, "todo": "Ready"}, '
     "ensure_ascii=False)",
     '        line = json.dumps({"backlog": column, "todo": "Ready"}, ensure_ascii=False)'),
    ("the doctor's Jira line breaks on a status with an apostrophe", JIRA_BOARD,
     "        quoted = line.replace(\"'\", \"''\")",
     "        quoted = line"),
    ("a card already in the status it is placed in is refused the placement", JIRA_BOARD,
     "        if match is None and self._status_now(issue).lower() == target.lower():",
     "        if False:"),
    ("the Jira tracker claims the create carries the declared backlog", JIRA_TRACKER,
     '        queue a status of its own — the line `openfactory doctor` hands over."""\n'
     '        return ""',
     '        queue a status of its own — the line `openfactory doctor` hands over."""\n'
     '        return self.status_map.get("backlog", "")'),
]
