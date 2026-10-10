"""The guard against Portuguese welded into the core sees a short phrase (#535, the guard's half),
proven by breaking it.

Run:  .venv/bin/python tools/mutate.py tools/mutations/535_the_language_guard_sees_a_short_phrase.py

`is_portuguese` needed an accent, or two of its words and more of them than English words: the
short phrases the role wrote on a card — " fechado a pedido de ", "**Produto:**", a commit message
"capacidade {slug}: confirmada por {who}" — passed it. The claims, each a row:

  1. a word only Portuguese writes says it alone, in a literal with no English word (rows 1-2);
  2. an OCR language list is not prose (row 3);
  3. the capability's commit message is English, and the guard holds it there (row 4).
"""

TEST = "tests/test_no_portuguese_is_welded_into_the_core.py"

GUARD = "tests/test_no_portuguese_is_welded_into_the_core.py"
CAPABILITIES = "openfactory/product/capabilities.py"

MUTATIONS = [
    ("TODAY'S DEFECT: a short phrase passes the two-word floor", GUARD,
     "    return bool(_PT_ALONE.search(text)) and english == 0\n",
     "    return False\n"),
    ("one such word reads a whole English sentence as Portuguese", GUARD,
     "    return bool(_PT_ALONE.search(text)) and english == 0\n",
     "    return bool(_PT_ALONE.search(text))\n"),
    ("an OCR language list reads as Portuguese", GUARD,
     "    if _LANGUAGE_CODES.fullmatch(text.strip()):\n        return False\n",
     "    if False:\n        return False\n"),
    ("the capability's commit message is Portuguese again", CAPABILITIES,
     '        rc, out = _git(["commit", "-m", f"capability {slug}: confirmed by {confirmed_by}"],\n',
     '        rc, out = _git(["commit", "-m", f"capacidade {slug}: confirmada por {confirmed_by}"],\n'),
]
