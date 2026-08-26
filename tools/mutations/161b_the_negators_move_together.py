"""#161 (the negation half): the two lists are one mechanism, and `no` stays out."""

TEST = "tests/test_a_negation_the_bridge_carries_is_refused.py"
INTENTS = "openfactory/product/intents.py"

MUTATIONS = [
    ("the matcher forgets every negator but Portuguese again", INTENTS,
     '_NOT_NEGATED = (r"(?<!n[ãa]o )(?<!nao )(?<!nunca )(?<!jamais )(?<!nem )"\n'
     "                r\"(?<!never )(?<!don't )(?<!dont )(?<!do not )\")",
     '_NOT_NEGATED = r"(?<!n[ãa]o )(?<!nao )(?<!nunca )(?<!jamais )"'),

    ("…and the reverse: it refuses everything, so the surface answers nobody", INTENTS,
     "                r\"(?<!never )(?<!don't )(?<!dont )(?<!do not )\")",
     '                r"(?<!never )(?<!don\'t )(?<!dont )(?<!do not )(?<!x)(?=$a)")'),

    ("the bridge stops carrying the new negators to the lookbehind", INTENTS,
     '           r"n[ãa]o|nunca|jamais|nem|never|don\'?t|do\\s+not|'
     'por\\s+favor|favor)[\\s,]+){0,2}"',
     '           r"n[ãa]o|nunca|jamais|por\\s+favor|favor)[\\s,]+){0,2}"'),

    ("`no` enters the negators — an ordinary instruction is refused", INTENTS,
     '_NOT_NEGATED = (r"(?<!n[ãa]o )(?<!nao )',
     '_NOT_NEGATED = (r"(?<!no )(?<!n[ãa]o )(?<!nao )'),

    ("…and it enters the bridge", INTENTS,
     '           r"n[ãa]o|nunca|jamais|nem|never',
     '           r"no|n[ãa]o|nunca|jamais|nem|never'),
]
