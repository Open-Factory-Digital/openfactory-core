"""A queue a person confirmed is the queue the factory runs, first card first (#512).

Run:  .venv/bin/python tools/mutate.py \
        tools/mutations/512_the_queue_runs_in_the_order_a_person_approved.py

Rows 1-2 are the defect as it shipped, one per board: `promote` writes no order, so Jira hands the
poller the backlog's old rank; and the local board serves its queue by card number. Rows 3-5 break
the chain `promote` writes: the first card goes to the bottom of the queue instead of the top,
the anchor never advances (each card goes to the top in turn, the order reversed), and the anchor
advances past a card whose place was refused (the next card follows a card nobody placed). Rows
6-8 break the sentence: a board that cannot rank is promised the order, `_confirm_queue` reads a
refused rank as kept, and the voice says the old promise whatever it is told. Rows 9-11 break the
local board's own order: a move to where the card is sends it to the back of its column, a card
that enters a column keeps no place there, and a board file from before the position never gains
it. Rows 12-13 break `place_after` on the local board: it places a card that is not in the column,
and it puts a card before its anchor.
"""

TEST = "tests/test_the_queue_runs_in_the_order_a_person_approved.py"

MODULE = "openfactory/product/module.py"
CONFIRM = "openfactory/product/confirm.py"
VOICE = "openfactory/product/voice.py"
LOCAL = "openfactory/adapters/board/local.py"
DB = "openfactory/adapters/board_db.py"

MUTATIONS = [
    ("TODAY'S DEFECT, ON JIRA: promote writes no order, so the queue keeps the backlog's old rank",
     MODULE,
     "        landed = [r for r in out if r.ok]\n        rankable = isinstance(board, Rankable)\n",
     "        landed = []\n        rankable = isinstance(board, Rankable)\n"),

    ("TODAY'S DEFECT, ON THE LOCAL BOARD: the queue is served by card number", LOCAL,
     '                    "ORDER BY c.position ASC, c.ref ASC", (self.project, wanted)).fetchall()',
     '                    "ORDER BY c.ref ASC", (self.project, wanted)).fetchall()'),

    ("the first card approved goes to the bottom of the queue, behind the card queued before it",
     LOCAL,
     "            rest.insert(rest.index(int(anchor)) + 1 if anchor else 0, card)",
     "            rest.insert(rest.index(int(anchor)) + 1 if anchor else len(rest), card)"),

    ("the anchor never advances, so each card goes to the top in turn and the order is reversed",
     MODULE,
     "            anchor = card if kept else anchor\n",
     "            anchor = anchor\n"),

    ("the anchor advances past a card whose place was refused, so the next follows a card nobody "
     "placed", MODULE,
     "            anchor = card if kept else anchor\n",
     "            anchor = card\n"),

    ("a board that cannot rank is promised the order anyway", MODULE,
     '                result.ranked = "unrankable"\n',
     '                result.ranked = "kept"\n'),

    ("the reply reads a refused rank as kept", CONFIRM,
     '    ranked = next((why for why in ("unrankable", "not_kept") if why in ranks), "kept")',
     '    ranked = "kept"'),

    ("the voice says the old promise whatever the order came to", VOICE,
     "    said = _QUEUED_OUT_OF_ORDER.get(ranked, _QUEUED)",
     "    said = _QUEUED"),

    ("a move to where the card already is sends it to the back of its column", DB,
     "       WHEN NEW.column_key IS NOT OLD.column_key\n",
     ""),

    ("a card that enters a column keeps no place there: the triggers are never created", DB,
     "        for statement in _TRIGGERS:\n            conn.execute(statement)\n",
     "        for statement in ():\n            conn.execute(statement)\n"),

    ("a board file from before the position never gains it", DB,
     '    ("cards", "position", "INTEGER NOT NULL DEFAULT 0"),\n',
     ""),

    ("the local board places a card that is not in the column", LOCAL,
     "            if card not in order or (anchor and int(anchor) not in rest):",
     "            if anchor and int(anchor) not in rest:"),

    ("the local board puts a card BEFORE its anchor", LOCAL,
     "            rest.insert(rest.index(int(anchor)) + 1 if anchor else 0, card)",
     "            rest.insert(rest.index(int(anchor)) if anchor else 0, card)"),
]
