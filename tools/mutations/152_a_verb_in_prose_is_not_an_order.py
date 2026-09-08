"""#152: a verb inside prose is not an order.

The cuts restore each half of the defect, and then go the other way — a matcher that refuses
everything satisfies half of these guards and makes the chat useless, which is the state #120 was
filed to end.
"""

TEST = "tests/test_a_typed_instruction_reaches_the_same_row_as_the_button.py"
INTENTS = "openfactory/actions/floor_intents.py"

MUTATIONS = [
    ("the verb may sit anywhere in the sentence again — the original defect", INTENTS,
     "    if not _commands_its_clause(body, m.start()):\n        return None",
     "    if False:\n        return None"),

    ("…and the reverse: nothing may precede the verb, so 'ok, merge' stops instructing", INTENTS,
     "    return bool(_LEADERS.match(body[_clause_start(body, start):start]))",
     "    return _clause_start(body, start) == start"),

    ("a command may trail off into a predicate, so a narration terminates a run", INTENTS,
     "    if not _fills_its_clause(body, m.end()):\n        return None",
     "    if False:\n        return None"),

    ("…and the reverse: the clause must end exactly, so 'descarta esse' stops instructing",
     INTENTS,
     # re-pinned 2026-09-07: trailing politeness is stripped before the count (#158)
     "    return len(rest.split()) <= 1",
     "    return not rest.strip()"),

    ("a conventional-commit subject is an order again — every ticket title in this product",
     INTENTS,
     r"|adjust|fix|rework)\b(?!\()", r"|adjust|fix|rework)\b"),

    # re-pinned 2026-09-07: the leaders became a named word list (#158)
    ("the leader list swallows a determiner, so 'the fix is incomplete' commands", INTENTS,
     r'_LEADER_WORDS = (r"ok|okay|please|por\s+favor|favor|e|and|then|ent[aã]o|agora|now|also|"',
     r'_LEADER_WORDS = (r"the|a|o|ok|okay|please|por\s+favor|favor|e|and|then|ent[aã]o|agora|now|also|"'),

    ("the clause walk stops finding boundaries, so every verb reads as heading the message",
     INTENTS,
     "    for boundary in _CLAUSES.finditer(body, 0, start):\n        last = boundary.end()",
     "    for boundary in []:\n        last = boundary.end()"),
]
