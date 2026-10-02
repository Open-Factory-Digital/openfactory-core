"""A card the product role opens as a plain card reaches the person who asked for it — its delivery
loop is opened where it was asked, and everything the loop leads to says "card" (#481).

Run:  .venv/bin/python tools/mutate.py \
        tools/mutations/481_a_plain_card_opens_its_delivery_loop.py

Row 1 is the defect as it shipped: `file_ticket` opens no loop. Rows 2-3 widen and narrow who it
opens for: the yes stops handing the staged conversation down, and a card filed with no
conversation opens one anyway. Rows 4-6 break the loop itself: no dedup, a ref keyed as typed
(`#12` and `12` two cards), the title dropped. Rows 7-15 break what the loop leads to: the marker
dropped (so every sentence reads a requirement), the delivery sentence, the acceptance that
forgets it is a card, the disambiguation, the release question naming a handle as a requirement
(for a card and for a defect), the agenda's two lines, and the judge told about a requirement.
"""

TEST = "tests/test_a_plain_card_reaches_the_person_who_asked.py"

MOD = "openfactory/product/module.py"
CONFIRM = "openfactory/product/confirm.py"
FOLLOWUP = "openfactory/product/followup.py"
AGENDA = "openfactory/product/agenda.py"

MUTATIONS = [
    ("TODAY'S DEFECT: a card filed from a conversation opens no delivery loop", MOD,
     "            self._track_ticket(ref, title=name, conversation=conversation, "
     "requester=requester)\n",
     "            pass\n"),

    ("the yes stops handing where the card was asked, and by whom, to the pen", CONFIRM,
     "        **_whose(module.file_ticket, entry))",
     "        )"),

    ("a card filed with no conversation opens a loop anyway — the room is owed a card nobody "
     "asked for there", MOD,
     '        if str(conversation or "").strip():\n'
     "            self._track_ticket(ref, title=name, conversation=conversation, "
     "requester=requester)\n",
     "        if True:\n"
     "            self._track_ticket(ref, title=name, conversation=conversation, "
     "requester=requester)\n"),

    ("the same card is followed twice", MOD,
     "        if subject in already:\n            return\n",
     "        if False:\n            return\n"),

    ("the card's loop is keyed on the ref as typed, so #12 and 12 are two cards", MOD,
     "        ref = canonical_ref(ref)\n        _follow_card(self.project, f\"cartao-{ref}\", ref,",
     "        ref = str(ref)\n        _follow_card(self.project, f\"cartao-{ref}\", ref,"),

    ("the card's title is not carried, so nothing on the loop says what the card is", MOD,
     '                     {"ticket": "1", "title": str(title or "")[:120]},',
     '                     {"ticket": "1", "title": ""},'),

    ("the loop forgets it is a card, and every sentence it leads to names a requirement", MOD,
     '                     {"ticket": "1", "title": str(title or "")[:120]},',
     '                     {"title": str(title or "")[:120]},'),

    ("the delivery of a card is announced as a requirement's", FOLLOWUP,
     '    if (loop.context or {}).get("ticket"):\n        from openfactory.product.voice import '
     "_card\n",
     "    if False:\n        from openfactory.product.voice import _card\n"),

    ("the acceptance the delivery opens forgets it was a card", FOLLOWUP,
     '                                 if ctx.get("ticket") else {})})',
     "                                 if False else {})})"),

    ("two open acceptances name the card as a requirement", FOLLOWUP,
     '    if (loop.context or {}).get("ticket"):\n        # A CARD SOMEBODY ASKED FOR IS NAMED BY ITS '
     "TITLE (#481)",
     "    if False:\n        # A CARD SOMEBODY ASKED FOR IS NAMED BY ITS TITLE (#481)"),

    ("the release question names a card's handle as its requirement", FOLLOWUP,
     '        if loop.kind != DELIVERY or marks.get("ticket") or marks.get("defect"):',
     '        if loop.kind != DELIVERY or marks.get("defect"):'),

    ("…and a defect's", FOLLOWUP,
     '        if loop.kind != DELIVERY or marks.get("ticket") or marks.get("defect"):',
     '        if loop.kind != DELIVERY or marks.get("ticket"):'),

    ("the agenda owes a card as a requirement", AGENDA,
     '        if ctx.get("ticket"):\n            return OWED, say("delivery_ticket")\n',
     '        if False:\n            return OWED, say("delivery_ticket")\n'),

    ("the agenda awaits a card's acceptance as a requirement's", AGENDA,
     '        if ctx.get("ticket"):\n            return AWAITED, say("acceptance_ticket")\n',
     '        if False:\n            return AWAITED, say("acceptance_ticket")\n'),

    ("the acceptance judge is told a requirement was delivered", MOD,
     '            if marks.get("ticket"):\n',
     "            if False:\n"),
]
