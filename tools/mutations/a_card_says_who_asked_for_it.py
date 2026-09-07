"""A card says who asked for it — the cuts that route a question back to the bot.

ROW 1: the parser ignores the front matter; ROW 2: the parser ignores the prose labels of older
cards; ROW 3: the builders stop writing the key; ROW 4: `requester_of` answers the creator first —
the bot, on every card the factory opened; ROW 5: "não registrado" is read as a person.
"""

TEST = "tests/test_a_card_says_who_asked_for_it.py"

MUTATIONS = [
    ("the parser ignores the front matter",
     "openfactory/adapters/tracker/parse.py",
     '    named = fm.get("requester")\n',
     '    named = None\n'),

    ("the parser ignores the prose labels of older cards",
     "openfactory/adapters/tracker/parse.py",
     "    for line in md.splitlines():\n        text = line.strip().replace(\"**\", \"\")\n",
     "    for line in []:\n        text = line.strip().replace(\"**\", \"\")\n"),

    ("the builders stop writing the key",
     "openfactory/product/authoring.py",
     '    return [f"---\\nrequester: {json.dumps(who, ensure_ascii=False)}\\n---"] '
     'if who else []\n',
     '    return []\n'),

    ("requester_of answers the creator first — the bot, on every card the factory opened",
     "openfactory/contracts/ticket.py",
     '    named = (getattr(ticket, "requester", None) or "").strip()\n',
     '    named = ""\n'),

    ("'não registrado' is read as a person",
     "openfactory/contracts/ticket.py",
     "    if named and named.lower() not in NOBODY:\n",
     "    if named:\n"),
]
