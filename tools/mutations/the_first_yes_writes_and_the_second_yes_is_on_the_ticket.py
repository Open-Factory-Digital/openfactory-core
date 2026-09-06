"""The first yes writes, the second yes is on the ticket — the cuts that put ADR-0032's road back.

ROW 1: the first yes writes and opens no card — the requester has nothing to say the second yes to.
ROW 2: the second yes is never staged — the next "sim" finds nothing.
ROW 3: the second yes breaks the requirement down again instead of stamping the cards it has.
ROW 4: the stamp names nobody — an acceptance without a person is not an acceptance.
ROW 5: the card opened from a proposal does not say it awaits anybody.
ROW 6: `open_cards_for` files cards for a requirement that is off the table.
ROW 7: the write takes the review-request road even when the base accepts it (ADR-0032 again).
"""

TEST = "tests/test_the_first_yes_writes_and_the_second_yes_is_on_the_ticket.py"
AUTHORING = "tests/test_product_authoring.py"

MUTATIONS = [
    ("the first yes writes and opens no card",
     "openfactory/product/confirm.py",
     "    cards = _the_official_cards(module, number, user, project)\n",
     "    cards = []\n"),

    ("the second yes is never staged",
     "openfactory/product/confirm.py",
     "        remember(key, follow, lang=lang, project=project)\n",
     "        pass\n"),

    ("the second yes breaks the requirement down again instead of stamping the cards",
     "openfactory/product/confirm.py",
     "    if cards:\n        return _stamped_on_the_cards(module, entry, cards, user, head, lang, "
     "project)\n",
     "    if False:\n        return _stamped_on_the_cards(module, entry, cards, user, head, lang, "
     "project)\n"),

    ("the stamp names nobody",
     "openfactory/product/voice.py",
     '        sig=signature(agent_name), actor=f"<@{bare_actor}>", day=day,\n',
     '        sig=signature(agent_name), actor="", day=day,\n'),

    ("the card opened from a proposal does not say it awaits anybody",
     "openfactory/product/authoring.py",
     "    if awaiting:\n        # THE CARD BEFORE THE PROMISE",
     "    if False:\n        # THE CARD BEFORE THE PROMISE"),

    ("open_cards_for files cards for a requirement that is off the table",
     "openfactory/product/module.py",
     "        if not requirement.is_live:\n            return [WriteResult(ok=False, "
     "detail=f\"o requisito {number} já não vale — não abri \"\n",
     "        if False:\n            return [WriteResult(ok=False, "
     "detail=f\"o requisito {number} já não vale — não abri \"\n"),

    ("the write takes the review-request road even when the base accepts it",
     "openfactory/product/authoring.py",
     '        rc, out = _git(["push", clone_url, f"HEAD:{base}"], cwd=tmp)\n        if rc == 0:\n',
     '        rc, out = _git(["push", clone_url, f"HEAD:{base}"], cwd=tmp)\n        if False:\n',
     AUTHORING),
]
