"""The product owner opens a card as described — the verb, cut at each of its seams.

FIVE SEAMS, ONE VERB. The model declares it (the marker), the channel stages it (the draft), the
yes performs it (the executor), the module writes it (the pen), the row exposes it (the panel).
Each row below breaks one seam while every other stays intact — which is the only way to know the
guard file sees the seam and not just the happy path.

ROW 1 IS THE MARKER PARSED AND IGNORED: the model says `[[TICKET: …]]`, the answer says nothing,
and the verb is unreachable from a chat while the prompt still teaches it.

ROW 3 IS THE WRONG KIND: staged as a defect, a yes files a broken promise for something nobody
said was broken — the exact confusion the prompt paragraph exists to prevent, committed by the
plumbing instead of the model.

ROWS 5-7 ARE THE PEN LYING: a duplicate opened twice; an "opened" with no URL, which is a card the
person cannot find; a refused placement reported as a success, which is a card the queue cannot
see (ADR-0030).

ROW 8 IS THE SPEND GATE: without the yes check, the API opens cards on a client's board on any
request that names a title.
"""

TEST = "tests/test_the_product_owner_opens_a_card_as_described.py"

MUTATIONS = [
    ("the marker is parsed and then ignored — the answer never says a card was asked for",
     "openfactory/product/role.py",
     "                             is_ticket=ticket is not None,",
     "                             is_ticket=False,"),

    ("the prompt stops teaching the title form, so the model can only say [[TICKET]] and the "
     "person's whole message becomes the title",
     "openfactory/product/role.py",
     '            "it, rather than discussed into a requirement — end with [[TICKET: <title>]] on its "',
     '            "it, rather than discussed into a requirement — end with [[TICKET]] on its "'),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("the channel stages the draft as a DEFECT, so the yes files a broken promise for something "
     "nobody said was broken",
     "openfactory/product/engine.py",
     '    replaced = remember(ex.key, {"kind": "ticket", "title": title,\n'
     '                                 "described": ex.text.strip()[:1500],',
     '    replaced = remember(ex.key, {"kind": "defect", "title": title,\n'
     '                                 "described": ex.text.strip()[:1500],'),

    ("the ticket kind is not registered, so a yes on a staged card falls through to the default "
     "— a requirement draft",
     "openfactory/product/confirm.py",
     '    "ticket": _confirm_ticket,',
     '    "ticket_": _confirm_ticket,'),

    ("the same title twice opens two cards",
     "openfactory/product/module.py",
     "            existing = tracker.find_ticket(title=name)\n            if existing:",
     "            existing = tracker.find_ticket(title=name)\n            if False:"),

    ("the card is opened and the reply carries no URL — a card the person cannot find",
     "openfactory/product/module.py",
     "        return WriteResult(ok=True, ref=str(ref), url=url, detail=detail)",
     '        return WriteResult(ok=True, ref=str(ref), url="", detail=detail)'),

    # RE-PINNED 2026-10-02 (#414): the three filing writers place a card through its door now, and
    # read one answer for whether it landed — the cut is that answer read as yes whatever it was
    # re-pinned 2026-10-04: filing goes through the door (#458) with the board's name (#505)
    ("a board that refuses the placement is read as having placed it",
     "openfactory/product/module.py",
     '        return board is None or moved.outcome("place").startswith("placed"), column',
     "        return True, column"),

    ("the row opens cards without a yes — the spend gate the whole product area shares, gone "
     "for one verb",
     "openfactory/actions/catalog.py",
     '    if not _said_yes(yes):\n        return refused(INVALID, "nothing was opened: this puts a card on the client\'s board and "',
     '    if False:\n        return refused(INVALID, "nothing was opened: this puts a card on the client\'s board and "'),
]
