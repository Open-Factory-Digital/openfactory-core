"""#158: courtesy on either side of the verb is still an order.

Both cuts restore a refusal the pilot actually hit, and both reverses restore the false positive
the refusing rules exist to prevent — including the one that makes `vai` alone unsafe in
Portuguese, where it is the future auxiliary as well as the imperative.
"""

TEST = "tests/test_a_typed_instruction_reaches_the_same_row_as_the_button.py"
INTENTS = "openfactory/actions/floor_intents.py"

MUTATIONS = [
    ("`vai lá` and `pode` stop being courtesy — the pilot's own sentence again", INTENTS,
     r'r"tamb[eé]m|depois|a[ií]|beleza|blz|pode|podes|poderia|"'
     "\n"
     r'                 r"vai\s+l[aá]|v[aá]\s+l[aá]|go\s+ahead")',
     r'r"tamb[eé]m|depois|a[ií]|beleza|blz")'),

    ("…and the reverse: bare `vai` becomes courtesy, so a FUTURE tense commands", INTENTS,
     r"vai\s+l[aá]|v[aá]\s+l[aá]|go\s+ahead", r"vai|v[aá]|go\s+ahead"),

    ("a trailing `por favor` counts as the sentence carrying on", INTENTS,
     '''    rest = re.sub(rf"\\b(?:{_LEADER_WORDS}|obrigad[oa]|thanks|thank\\s+you)\\b", " ",
                  body[end:clause_end], flags=re.I)
    return len(rest.split()) <= 1''',
     "    return len(body[end:clause_end].split()) <= 1"),

    ("…and the reverse: anything may trail a command, so a narration terminates a run", INTENTS,
     '''    rest = re.sub(rf"\\b(?:{_LEADER_WORDS}|obrigad[oa]|thanks|thank\\s+you)\\b", " ",
                  body[end:clause_end], flags=re.I)
    return len(rest.split()) <= 1''',
     "    return True"),
]
