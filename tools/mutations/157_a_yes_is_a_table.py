"""#157: what counts as yes is a table, not a pattern — and every row is live at once.

The pilot's own question filed this (translated): "that is not hard-coded, right? because it will
not necessarily be in Portuguese." And the pilot is also why the UNION, not the config, is matched:
his project says `language: en` and he types "sim".
"""

TEST = "tests/test_a_yes_is_an_answer.py"
INTENTS = "openfactory/actions/floor_intents.py"

MUTATIONS = [
    ("the union collapses to English — the configured-language mistake from the other side",
     INTENTS,
     "    words = tuple(w for row in YES_WORDS.values() for w in row)",
     '    words = tuple(YES_WORDS["en"])'),

    ("…and the reverse: bare `ta` enters a row, so a British thank-you presses a staged merge",
     INTENTS,
     '    "pt-br": ("sim", "isso", "isso aí", "beleza", "blz", "tá", "tá bom", "ta bom", '
     '"fechado",',
     '    "pt-br": ("sim", "ta", "isso", "isso aí", "beleza", "blz", "tá", "tá bom", "ta bom", '
     '"fechado",'),

    ("multi-word forms stop matching across a double space", INTENTS,
     '    alternatives = "|".join(re.escape(w).replace(r"\\ ", r"\\s+") for w in words)',
     '    alternatives = "|".join(re.escape(w) for w in words)'),

    ("the pattern grows a cache, so a new language row is dead until a restart", INTENTS,
     '    return re.compile(rf"^\\s*(?P<gesture>{alternatives})\\s*[.!?]*\\s*$", re.I)',
     '    pat = re.compile(rf"^\\s*(?P<gesture>{alternatives})\\s*[.!?]*\\s*$", re.I)\n'
     '    if not hasattr(_yes_pattern, "_c"):\n'
     "        _yes_pattern._c = pat\n"
     "    return _yes_pattern._c"),
]
