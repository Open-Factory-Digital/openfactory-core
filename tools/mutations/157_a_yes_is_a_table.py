"""#157: what counts as yes is a table, not a pattern — and every row is live at once.

The pilot's own question filed this (translated): "that is not hard-coded, right? because it will
not necessarily be in Portuguese." And the pilot is also why the UNION, not the config, is matched:
his project says `language: en` and he types "sim".
"""

TEST = "tests/test_a_yes_is_an_answer.py"
#: the table moved out of `floor_intents.py` into `language/assent.py` (#161); every row below
#: was re-pinned there on 2026-09-07 — the claims are the same, the pattern is gone (the table
#: is matched by normalised whole-message equality, not by a compiled regex)
ASSENT = "openfactory/language/assent.py"

MUTATIONS = [
    ("the union collapses to English — the configured-language mistake from the other side",
     ASSENT,
     "    return frozenset(w for row in table.values() for w in row)",
     '    return frozenset(table.get("en", ()))'),

    ("…and the reverse: bare `ta` enters a row, so a British thank-you presses a staged merge",
     ASSENT,
     '    "pt-br": ("sim", "tá", "isso", "confirmo", "confirma", "confirmado", "claro", "exato",',
     '    "pt-br": ("sim", "ta", "tá", "isso", "confirmo", "confirma", "confirmado", "claro", '
     '"exato",'),

    ("multi-word forms stop matching across a double space", ASSENT,
     '    normalised = " ".join(body.lower().split())',
     '    normalised = body.lower()'),

    ("the table grows a cache, so a new language row is dead until a restart", ASSENT,
     "def core_words() -> frozenset[str]:\n    return _flat(CORE)",
     "_C: dict = {}\n\n\ndef core_words() -> frozenset[str]:\n"
     '    if "w" not in _C:\n        _C["w"] = _flat(CORE)\n    return _C["w"]'),
]
