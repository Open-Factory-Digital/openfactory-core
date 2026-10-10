"""What reads a person's gestures, assent and refusals is declared a recogniser, not counted as the
sweep's debt (#535, review of #579), proven by breaking it.

Run:  .venv/bin/python tools/mutate.py tools/mutations/535_recognisers_are_not_debt.py

The list of Portuguese literals not yet in a catalogue said 414 fragments; 105 of them were the
tables that RECOGNISE what a Portuguese speaker types — no sweep will ever move what the platform
reads. Each row takes one file's declarations away, and the guard must then see those fragments as
undeclared.
"""

TEST = "tests/test_no_portuguese_is_welded_into_the_core.py"
GUARD = "tests/test_no_portuguese_is_welded_into_the_core.py"

MUTATIONS = [
    ("the assent words are welded Portuguese again", GUARD,
     '    ("openfactory/language/assent.py", "CORE"): "yes",\n',
     ""),
    ("the floor's leader words are welded Portuguese again", GUARD,
     '    ("openfactory/actions/floor_intents.py", "_LEADER_WORDS"): "please",\n',
     ""),
    ("the product's gestures are welded Portuguese again", GUARD,
     '    ("openfactory/product/intents.py", "_PATTERNS"): "introduce yourself",\n',
     ""),
]
