"""#500, proven by breaking it — a card the factory finished on the local board is delivered, and
the panel's board shows what was delivered in Done.

WHAT WAS MEASURED, on `main` at 6d8a446, with the first guard below: a card asked for in a
conversation, settled Done by the workflow's own `settle_ticket` and ended by `record_outcome`, sat
OPEN in Done. `triage.Ticket.delivered` never counted it, so `events.card_finished` (the job's
exit) and the sweep's catch-all both announced nothing — 6 of the guard's first 9 cases red, the
requester told nothing — and the door refused to reopen it ("está entregue — não pode ser
reaberto"). Closing it there, as every hosted row does, took it off the panel's board: `/api/board`
listed open cards only, which is why #195 had kept it open. On GitHub that Done was already empty.

THE CLAIMS:

  1. **The factory's Done closes the card as delivered** — `closed`, `completed`, the word
     `close_ticket(delivered=True)` writes — so its requester is told, once
     (`tracker/local.py::move_card`, for `set_state`).
  2. **Leaving Done opens it again**, as on Jira and Azure DevOps, where the status is the state —
     for the factory's move and for a person's drag alike (`LocalBoard.set_column` moves by the
     same rule). A drag INTO Done records no delivery.
  3. **A card closed as not delivered stays that** — Done never turns it into shipped work, and no
     move reopens it.
  4. **The close says nothing of its own**, and a card the board does not hold is not moved.
  5. **The panel's board shows the recent cards closed as delivered** (`api/app.py::
     _delivered_cards`), in the column the board places them in, else the column THIS board calls
     `done` (`board/base.py::stage_column`, asked for one that exists) — bounded in count and age,
     never a card closed as not delivered, and a closed read that failed leaves the open cards
     standing.
  6. **That column is one the board HAS** (review of #505/#506, where `column_for` became a layer
     of `stage_column`): the row's map only when it names a real column, else the first real
     column that is `done`, else none — never the platform's literal on a board that lacks it.

The guards are `tests/test_a_finished_card_on_the_local_board_is_delivered.py` and
`tests/test_the_panels_board_shows_the_delivered_cards.py`.
"""

TEST = "tests/test_a_finished_card_on_the_local_board_is_delivered.py"
PANEL_TEST = "tests/test_the_panels_board_shows_the_delivered_cards.py"

LOCAL = "openfactory/adapters/tracker/local.py"
BOARD = "openfactory/adapters/board/local.py"
BASE = "openfactory/adapters/board/base.py"
APP = "openfactory/api/app.py"

MUTATIONS = [
    # ── 1. Done closes as delivered ────────────────────────────────────────────────────────────
    ("THE FIX ITSELF: a card the factory finished stays open in Done, so it is never delivered and "
     "its requester is never told", LOCAL,
     "    if key == done and is_open and closes_at_done:\n",
     "    if False:\n"),

    ("the factory's Done closes the card as NOT delivered, so shipped work reads as withdrawn",
     LOCAL,
     '        now, word = "closed", "completed"',
     '        now, word = "closed", "not_planned"'),

    # ── 2. leaving Done reopens ────────────────────────────────────────────────────────────────
    ("a delivered card the factory moves out of Done stays closed, in a column nothing reads",
     LOCAL,
     "    elif key != done and not is_open and not withdrawn:\n",
     "    elif False:\n"),

    ("the board moves a card by a rule the tracker abandoned: a delivered card dragged out of Done "
     "on the panel stays closed, and snaps back into Done", BOARD,
     '            moved = move_card(conn, self.project, int(bare), col["key"], '
     "closes_at_done=False)",
     '            moved = conn.execute("UPDATE cards SET column_key = ?, updated_at = ? '
     'WHERE project = ? AND ref = ?", (col["key"], now_iso(), self.project, '
     "int(bare))).rowcount", PANEL_TEST),

    ("a person dragging a card into Done records it as delivered, with no close and no comment",
     BOARD,
     "closes_at_done=False)",
     "closes_at_done=True)", PANEL_TEST),

    # ── 3. not delivered stays not delivered ───────────────────────────────────────────────────
    ("a move out of Done reopens a WITHDRAWN card too, bringing back work nobody wants", LOCAL,
     '    withdrawn = not is_open and card["closed_reason"] == "not_planned"',
     "    withdrawn = False"),

    ("Done turns a card closed as not delivered into shipped work", LOCAL,
     "    if key == done and is_open and closes_at_done:\n",
     "    if key == done and closes_at_done:\n"),

    # ── 4. nothing said twice; nothing moved that is not there ─────────────────────────────────
    ("the close writes a comment of its own, beside the note the door or the job already gave",
     LOCAL,
     '        now, word = "closed", "completed"\n',
     '        now, word = "closed", "completed"\n'
     '        conn.execute("INSERT INTO comments(project, ref, seq, author, body, created_at) '
     'VALUES (?,?,?,?,?,?)", (project, bare, 1, BOT_AUTHOR, "delivered", now_iso()))\n'),

    ("a move of a card this board does not hold is reported as a move", LOCAL,
     "    if card is None:\n        return False",
     "    if card is None:\n        return True"),

    # ── 5. the panel's board shows what was delivered ──────────────────────────────────────────
    ("THE PANEL'S HALF: the board lists the open cards only, so Done is empty on every row that "
     "closes what it delivers", APP,
     "        cards += _delivered_cards(proj, board, tracker, placed=placed, names=names,\n"
     '                                  shown={c["ref"] for c in cards})',
     "        cards += []", PANEL_TEST),

    ("a card closed as NOT delivered is drawn in Done as shipped work", APP,
     "        if not Ticket(number=s.ref, title=s.title, state=s.state,\n"
     "                      state_reason=s.state_reason).delivered:\n"
     "            continue",
     "        if False:\n            continue", PANEL_TEST),

    ("the whole history of closed cards is read on every tick of a watched board", APP,
     '        closed = tracker.list_tickets(state="closed", limit=DELIVERED_SHOWN_AT_MOST)',
     '        closed = tracker.list_tickets(state="closed", limit=0)', PANEL_TEST),

    ("a card delivered months ago is still drawn in Done", APP,
     "        if s.ref in shown or _updated_before(s.updated_at, since):",
     "        if s.ref in shown:", PANEL_TEST),

    ("Done is the platform's literal, so a renamed board's delivered cards land in a column it "
     "does not draw", APP,
     # re-pinned 2026-10-04: one inverse of stage_key (review of #505/#506)
     '                done = stage_column(board, "done", existing=True, names=names)',
     '                done = "Done"', PANEL_TEST),

    ("the board's own name for a stage is guessed from the platform's vocabulary instead of asked "
     "of the board", BASE,
     # re-pinned 2026-10-04: one inverse of stage_key (review of #505/#506)
     '    walked = next((name for name in real if stage_key(board, name) == wanted), "")\n',
     '    walked = {"done": "Done"}.get(wanted, "")\n', PANEL_TEST),

    ("a delivered card is drawn in Done whatever column its board places it in", APP,
     '        column = placed.get(s.ref, "")\n',
     '        column = ""\n', PANEL_TEST),

    ("a closed read that failed reaches the page as an unreadable board — or as a 500", APP,
     '                    "read, so Done shows only the open cards in it", name)\n'
     "        return []",
     '                    "read, so Done shows only the open cards in it", name)\n'
     "        return None", PANEL_TEST),

    ("a row that breaks the port's promise and raises takes the whole board down with it", APP,
     "    try:\n"
     '        closed = tracker.list_tickets(state="closed", limit=DELIVERED_SHOWN_AT_MOST)\n'
     "    except Exception:  # noqa: BLE001 — the port promises not to raise; the open cards still "
     "stand\n"
     '        log.warning("the tracker of %s raised listing its closed cards", name, '
     "exc_info=True)\n"
     "        closed = None",
     '    closed = tracker.list_tickets(state="closed", limit=DELIVERED_SHOWN_AT_MOST)',
     PANEL_TEST),

    # ── 6. a column the board has (review of #505/#506) ────────────────────────────────────────
    ("a name the row's map declares for `done` is drawn though the board has no such column", BASE,
     "    if mapped and mapped in real:\n        return mapped\n",
     "    if mapped:\n        return mapped\n", PANEL_TEST),

    ("the panel asks for Done as a move does, and draws the platform's `Done` on a board without "
     "one", APP,
     'stage_column(board, "done", existing=True, names=names)',
     'stage_column(board, "done", existing=False, names=names)', PANEL_TEST),

    ("a caller that draws is answered by the platform's literal when no column is the stage", BASE,
     "    if walked or existing:\n        return walked\n",
     "    if walked:\n        return walked\n", PANEL_TEST),
]
