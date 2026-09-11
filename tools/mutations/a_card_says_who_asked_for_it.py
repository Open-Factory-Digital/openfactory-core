"""A card says who asked for it — the cuts that route a question back to the bot.

ROW 1: the parser ignores the front matter; ROW 2: the parser ignores the prose labels of older
cards; ROW 3: the builders stop writing the key; ROW 4: `requester_of` answers the creator first —
the bot, on every card the factory opened; ROW 5: "não registrado" is read as a person.

THIS PLAN SHIPPED DEAD (#74, found in review). Row 3's anchor was the one-line `_requester_front_matter`
from before `requester_forge` joined it, and row 2's matched twice once `_requester_forge` grew
the same loop — `mutate.py` refuses the whole plan on either, so none of the five rows ran while
the PR body reported the plans beside it. An anchor is a point-in-time proof of the tree it was
written in: re-run the plan after every refactor of a file it names.
"""

TEST = "tests/test_a_card_says_who_asked_for_it.py"

MUTATIONS = [
    ("the parser ignores the front matter",
     "openfactory/adapters/tracker/parse.py",
     '    named = fm.get("requester")\n',
     '    named = None\n'),

    ("the parser ignores the prose labels of older cards",
     "openfactory/adapters/tracker/parse.py",
     # the `low =` line tells `_requester`'s loop from `_requester_forge`'s, which is otherwise
     # the same two lines
     "    for line in md.splitlines():\n        text = line.strip().replace(\"**\", \"\")\n"
     "        low = _normalise(text.split(\":\", 1)[0]) if \":\" in text else _normalise(text)\n",
     "    for line in []:\n        text = line.strip().replace(\"**\", \"\")\n"
     "        low = _normalise(text.split(\":\", 1)[0]) if \":\" in text else _normalise(text)\n"),

    ("the builders stop writing the key",
     "openfactory/product/authoring.py",
     '    return ["---\\n" + "\\n".join(keys) + "\\n---"]\n',
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
