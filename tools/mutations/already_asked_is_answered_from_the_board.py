"""#33 slice 5 ("already asked" is answered from the board, not the transcript): every rule of the
read and every hop of the section is a cut — the stem, the two-word floor, the verbs of wanting,
the ordering, the limit, the closed decisions, the empty render, the instruction, the role's
placement, the module's hand-over, the module's board read, and the client's document.
"""

TEST = "tests/test_already_asked_is_answered_from_the_board_not_the_transcript.py"
ASKED = "openfactory/product/asked.py"
MODULE = "openfactory/product/module.py"
ROLE = "openfactory/product/role.py"
DOC = "docs/reference/product-role.md"

MUTATIONS = [
    ("inflection is not folded — a plural is another word", ASKED,
     "    return len(a) >= STEM and len(b) >= STEM and a[:STEM] == b[:STEM]\n",
     "    return False\n"),

    ("one shared word is a lead", ASKED,
     "MIN_SHARED = 2\n", "MIN_SHARED = 1\n"),

    ("the verbs of wanting carry meaning", ASKED,
     "quero queria gostaria preciso precisamos queremos podemos poderia possivel favor\n",
     "\n"),

    ("the weakest lead comes first", ASKED,
     "    found.sort(key=lambda m: (-m.score, -m.shared, m.kind, m.ref))\n",
     "    found.sort(key=lambda m: (m.score, m.shared, m.kind, m.ref))\n"),

    ("the list is everything, not a lead", ASKED,
     "    return found[:limit]\n", "    return found\n"),

    ("an answered decision is still asked", ASKED,
     "    for loop in waiting(list(loops), kind=DECISION):\n",
     "    for loop in [x for x in loops if x.kind == DECISION]:\n"),

    ("a section is drawn for nothing", ASKED,
     '    if not matches:\n        return ""\n',
     '    if not matches:\n        return "# Possibly already asked\\n\\nnothing\\n"\n'),

    ("the role is not told to point instead of drafting", ASKED,
     '        "reference — do not draft it again. If none is, ignore this list; it is a lead, not a "\n',
     '        "reference. If none is, ignore this list; it is a lead, not a "\n'),

    ("the section never reaches the prompt", ROLE,
     '            + (f"{asked}\\n" if asked else "")\n', ""),

    ("the module hands the role nothing", MODULE,
     "            asked=self.already_asked(question))\n",
     '            asked="")\n'),

    ("the module reads no board for it", MODULE,
     "        matches = asked.already_asked(text, cards=self._board_cards(),\n",
     "        matches = asked.already_asked(text, cards=[],\n"),

    ("the client's document forgets it", DOC,
     "**Was this asked before?**", "**Was this decided before?**"),
]
