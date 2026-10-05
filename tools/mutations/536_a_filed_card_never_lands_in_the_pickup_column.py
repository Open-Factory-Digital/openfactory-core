"""A card the product role files is never born in the pickup column (#536), proven by breaking it.

Run:  .venv/bin/python tools/mutate.py \
        tools/mutations/536_a_filed_card_never_lands_in_the_pickup_column.py

On the Azure DevOps process the setup guide built, a new work item was born in `To Do` — the
pickup column — and the poller started work nobody had queued. The claims, each a row below:

  1. the tracker creates the item IN the backlog the deployment declared (`state_map`), on the
     create itself, so no moment exists in which it sits in the queue;
  2. the board says which column a created item is born in: the INCOMING column for the type's
     first state (the first column when no column says), a declared state's own column, and
     `None` — never "not the queue" — when it could not read its columns;
  3. `board.base.intake` puts the two halves together against the board's own pickup column, and
     does not arise on a row whose new card sits on no column;
  4. each of the product role's three filing writers asks BEFORE it writes, and files nothing —
     saying why, in the conversation's language — where the card would be born in the queue, or
     where the board could not say;
  5. `openfactory doctor` FAILS such a board, with the row's own line, which the registry takes;
     an unread board is said once, by `board_columns`;
  6. the setup guide's state table lists the backlog as required, and its two lines are a board
     on which a filed card is born out of the queue.
"""

TEST = "tests/test_a_filed_card_never_lands_in_the_pickup_column.py"
TRACKER = "openfactory/adapters/tracker/azure_devops.py"
BOARD = "openfactory/adapters/board/azure_devops.py"
BASE = "openfactory/adapters/board/base.py"
MODULE = "openfactory/product/module.py"
VOICE = "openfactory/product/voice.py"
DOCTOR = "openfactory/doctor.py"
GUIDE = "docs/setup/azure-devops.md"

MUTATIONS = [
    # 1. the create carries the state
    ("THE DEFECT'S ROOT: the create sends no state, and the item is born in the type's first one",
     TRACKER,
     '                  *([{"op": "add", "path": "/fields/System.State", "value": state}]\n'
     "                    if state else []),\n",
     ""),
    ("the tracker forgets the backlog the deployment declared", TRACKER,
     '        return self.state_map.get("backlog", "")',
     '        return ""'),

    # 2. the board's half
    ("the incoming column is read off the wrong column type", BOARD,
     '        incoming = next((c for c in cols if str(c.get("columnType") or "") == "incoming"),',
     '        incoming = next((c for c in cols if str(c.get("columnType") or "") == "outgoing"),'),
    ("a board whose columns say no type is read by its last column, not its first", BOARD,
     "                            cols[0])",
     "                            cols[-1])"),
    ("an unread board answers that a new card starts on no column", BOARD,
     "        cols = self._board_columns()\n        if cols is None:\n            return None\n"
     '        wanted = (state or "").strip().casefold()',
     "        cols = self._board_columns()\n        if cols is None:\n            return \"\"\n"
     '        wanted = (state or "").strip().casefold()'),
    ("a declared state is found in no column", BOARD,
     "                     if any(str(s).strip().casefold() == wanted\n",
     "                     if any(str(s).strip().casefold() == wanted + \"?\"\n"),
    ("the doctor's line names a backlog column the board does not have", BOARD,
     "tracker's options `columns: '{{\\\"backlog\\\": \\\"{column}\\\", \"",
     "tracker's options `columns: '{{\\\"backlog\\\": \\\"Backlog\\\", \""),

    # 3. the two halves together
    ("a card born in the pickup column is not read as queued", BASE,
     "    queued = bool(column) and column.strip().casefold() == queue.strip().casefold()",
     "    queued = False"),
    ("a row whose new card sits on no column is asked anyway", BASE,
     '    if board is None or not callable(lands):\n        return None\n    said = ',
     '    if board is None or not callable(lands):\n'
     '        return Intake(column="", queue="", queued=False)\n    said = '),

    # 4. the product role asks before it writes
    # two rows re-pinned 2026-10-05: the decision moved to `board.base.intake_held`, which every
    # writer of a new card asks (#543)
    ("the role files wherever the card is born", BASE,
     "    if born is None or (born.column is not None and not born.queued):",
     "    if True:"),
    ("an unread board is read as safe to file on", BASE,
     "    if born is None or (born.column is not None and not born.queued):",
     "    if born is None or not born.queued:"),
    ("a card asked for is filed without asking where it is born", MODULE,
     '        held = self._born_in_the_queue(tracker, board, act="file a ticket")\n'
     "        if held is not None:\n            return held\n",
     ""),
    ("a defect is filed without asking where it is born", MODULE,
     '        held = self._born_in_the_queue(tracker, board, act="file a defect")\n'
     "        if held is not None:\n            return held\n",
     ""),
    ("a breakdown is filed without asking where its cards are born", MODULE,
     '        held = self._born_in_the_queue(tracker, board, act="break a requirement into work")\n'
     "        if held is not None:\n            return [held]\n",
     ""),
    ("the English sentence drops what it would have cost", VOICE,
     '"the factory picks work up from, so it would start being built — and paid "',
     '"the factory picks work up from, so it would start being built and "'),
    ("the Portuguese sentence drops what it would have cost", VOICE,
     '"coluna de onde a fábrica pega trabalho, então ele começaria a ser "',
     '"coluna de onde a fábrica pega trabalho, então ele seria "'),

    # 5. the doctor
    ("the doctor only warns about a board that spends on its own", DOCTOR,
     '            "board_intake", False,\n',
     '            "board_intake", True,\n'),
    ("the doctor never asks", DOCTOR,
     "        board_intake=_intake,\n",
     ""),
    ("an unread board is reported twice", DOCTOR,
     "    except BoardUnreadable:\n        return []\n",
     "    except BoardUnreadable:\n"
     '        return [Finding("board_intake", False, "the board could not be read", "")]\n'),
    ("the probe reports an unread board as one whose new card is on no column", DOCTOR,
     "        if born is not None and born.column is None:",
     "        if False:"),

    # 6. the guide
    ("the guide's state table stops requiring a backlog", GUIDE,
     "| backlog — where a filed card waits | **To Do** (declared, step 5) | yes — **required** |",
     "| backlog — where a filed card waits | **To Do** (declared, step 5) | yes |"),
    ("the guide's lines leave the queue where Azure files a new item", GUIDE,
     "    columns:   '{\"backlog\": \"To Do\", \"todo\": \"Ready\"}'     # the board's columns",
     "    columns:   '{\"backlog\": \"To Do\", \"todo\": \"To Do\"}'     # the board's columns"),
]
