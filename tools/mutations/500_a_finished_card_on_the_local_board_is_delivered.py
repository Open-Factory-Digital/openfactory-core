"""#500, proven by breaking it — a card the factory finished on the local board is delivered.

WHAT WAS MEASURED, on `main` at 6d8a446, with the guard below: a card asked for in a conversation,
settled Done by the workflow's own `settle_ticket` and ended by `record_outcome`, sat OPEN in Done.
`triage.Ticket.delivered` never counted it, so `events.card_finished` (the job's exit) and the
sweep's catch-all both announced nothing — 6 of the guard's first 9 cases red, the requester told
nothing — and the door refused to reopen it ("está entregue — não pode ser reaberto").

FIVE CLAIMS, all in `LocalTracker.set_state`:

  1. **The factory's Done closes the card as delivered** — `closed`, `completed`, the word
     `close_ticket(delivered=True)` writes — so its requester is told, once.
  2. **Leaving Done opens it again**, as on Jira and Azure DevOps, where the status is the state:
     a delivered card the factory queues is on the board, not a closed card in a column nothing
     reads.
  3. **A card closed as not delivered stays that** — Done never turns it into shipped work, and no
     move reopens it.
  4. **The close says nothing of its own**: the row writes no `reason`, so nothing on the card is
     said twice.
  5. **A card the board does not hold is not reported moved.**

The guard is `tests/test_a_finished_card_on_the_local_board_is_delivered.py`.
"""

TEST = "tests/test_a_finished_card_on_the_local_board_is_delivered.py"

LOCAL = "openfactory/adapters/tracker/local.py"

MUTATIONS = [
    # ── 1. Done closes as delivered ────────────────────────────────────────────────────────────
    ("THE FIX ITSELF: a card the factory finished stays open in Done, so it is never delivered and "
     "its requester is never told", LOCAL,
     "            if key == done and is_open:\n",
     "            if False:\n"),

    ("the factory's Done closes the card as NOT delivered, so shipped work reads as withdrawn",
     LOCAL,
     '                now, word = "closed", "completed"',
     '                now, word = "closed", "not_planned"'),

    # ── 2. leaving Done reopens ────────────────────────────────────────────────────────────────
    ("a delivered card the factory moves out of Done stays closed, in a column nothing reads",
     LOCAL,
     "            elif key != done and not is_open and not withdrawn:\n",
     "            elif False:\n"),

    # ── 3. not delivered stays not delivered ───────────────────────────────────────────────────
    ("a move out of Done reopens a WITHDRAWN card too, bringing back work nobody wants", LOCAL,
     '            withdrawn = not is_open and card["closed_reason"] == "not_planned"',
     "            withdrawn = False"),

    ("Done turns a card closed as not delivered into shipped work", LOCAL,
     "            if key == done and is_open:\n",
     "            if key == done:\n"),

    # ── 4. nothing said twice ──────────────────────────────────────────────────────────────────
    ("the close writes a comment of its own, beside the note the door or the job already gave",
     LOCAL,
     '                now, word = "closed", "completed"\n',
     '                now, word = "closed", "completed"\n'
     '                conn.execute("INSERT INTO comments(project, ref, seq, author, body, '
     'created_at) VALUES (?,?,?,?,?,?)", (self.project, bare, 1, BOT_AUTHOR, "delivered", '
     "when))\n"),

    # ── 5. a card that is not there ────────────────────────────────────────────────────────────
    ("a move of a card this board does not hold is reported as a move", LOCAL,
     "            if card is None:\n                return False",
     "            if card is None:\n                return True"),
]
