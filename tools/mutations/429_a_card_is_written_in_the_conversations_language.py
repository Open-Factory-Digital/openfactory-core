"""A card is written in the language of the conversation it came from, and no Portuguese string is
welded into the core outside a catalogue (#429).

Run:  .venv/bin/python tools/mutate.py tools/mutations/429_a_card_is_written_in_the_conversations_language.py

Row 1 is the defect as it shipped: the layout ignores the language, so an English conversation gets
the Portuguese layout. Rows 2-3 lose the language on its way to the layout or the drafter. Rows 4-5
switch off the floor's check or make it guess. Row 6 lets the product's own layout lose to a shipped
one. Rows 7-8 find the correction's section by one language's literal, or rename it on the way out.
Row 9 puts the admin line back in one language. Rows 10-12 blind the guard: a detector that sees no
Portuguese, a catalogue test that accepts a key it should not, an exemption list that stops
shrinking. Rows 13-17 are what the person sees after the yes: the card body's own lines in one
language, a marker read in one language only (a translated card the product owner owns becomes
editable from the board), the broken promise's heading read in one language, the requirement's
breakdown reply and the pen's replies in one language.
"""

TEST = "tests/test_a_card_is_written_in_the_conversations_language.py"

CARDS = "openfactory/product/cards.py"
MODULE = "openfactory/product/module.py"
WRITTEN = "openfactory/language/written.py"
VOICE = "openfactory/product/voice.py"
GUARD = "tests/test_no_portuguese_is_welded_into_the_core.py"
AUTHORING = "openfactory/product/authoring.py"
CONFIRM = "openfactory/product/confirm.py"

MUTATIONS = [
    ("TODAY'S DEFECT: the shipped layout is chosen without the language", CARDS,
     "    return _shipped_for(name, language)",
     "    return _shipped_for(name, \"pt-BR\")"),

    ("the module does not hand the language to the layout", MODULE,
     "            template=cards.load_template(ctx.docs_path, kind, lang),",
     "            template=cards.load_template(ctx.docs_path, kind),"),

    ("the drafter is not told the language by name", CARDS,
     "            template=template, feedback=feedback, kind=kind, language=language)))",
     "            template=template, feedback=feedback, kind=kind)))"),

    ("the floor never checks the language", CARDS,
     "    other = not_in(written, language)",
     "    other = None"),

    ("the language check guesses on thin evidence", WRITTEN,
     "    if most < ENOUGH or most < LOPSIDED * max(next_most, 1):",
     "    if most < 1:"),

    ("the product's own layout loses to the shipped one", CARDS,
     "        if not problem:\n            return text",
     "        if False:\n            return text"),

    ("the correction's section is found by one literal", MODULE,
     '    "what was asked": ("O que foi pedido",),',
     '    "what was asked": (),'),

    ("a correction renames the section into the identity's language", MODULE,
     '    named = old.split("\\n", 1)[0].lstrip("#").strip() if old else heading',
     "    named = heading"),

    ("the admin line is Portuguese in every language", VOICE,
     "    said = _pick(_ADMINS_MUST_CONFIRM, language)",
     '    said = _pick(_ADMINS_MUST_CONFIRM, "pt-BR")'),

    ("the detector sees no accented Portuguese", GUARD,
     "    if _PT_LETTERS.search(text):\n        return True",
     "    if False:\n        return True", GUARD),

    ("a catalogue without English allows its Portuguese", GUARD,
     '        if "en" not in keys or not keys & _PT_KEYS:',
     "        if not keys & _PT_KEYS:", GUARD),

    ("a dead exemption is not reported", GUARD,
     "        dead += [f\"{rel}: {text!r}\" for text in (listed - have).elements()]",
     "        pass", GUARD),

    ("the card body's own lines are Portuguese in every language", AUTHORING,
     "    return _pick(_CARD_LINES, language)",
     '    return _pick(_CARD_LINES, "pt-BR")'),

    ("a request card is recognised by its Portuguese marker only", AUTHORING,
     "    if any(line.startswith(tuple(_FROM_A_REQUEST.values())) for line in lines):",
     '    if any(line.startswith(_FROM_A_REQUEST["pt-BR"]) for line in lines):'),

    ("the broken promise is read under its Portuguese heading only", MODULE,
     "(?:A promessa violada|The broken promise)",
     "(?:A promessa violada)"),

    ("the requirement's breakdown reply is Portuguese in every language", CONFIRM,
     "    return _pick(_SAID, lang)",
     '    return _pick(_SAID, "pt-BR")'),

    ("the pen's replies are Portuguese in every language", MODULE,
     "        said = _pick(_FILING, lang)\n        ctx = self.context()\n        name = ",
     '        said = _pick(_FILING, "pt-BR")\n        ctx = self.context()\n        name = '),
]
