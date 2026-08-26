"""#161: no gesture exists in one language only — and the fences still hold."""

TEST = "tests/test_no_gesture_exists_in_one_language_only.py"
FI = "openfactory/actions/floor_intents.py"
PI = "openfactory/product/intents.py"
CONV = "openfactory/techlead/conversation.py"

PERM = "tests/test_permission_is_an_order_in_every_language.py"

MUTATIONS = [
    # ── the permission form, the sentence the pilot actually typed ───────────────────────────────
    ("the merge gate stops taking permission in English", FI,
     '        r"\\b(?:" + _MAY + r"(?:fazer|dar|mandar|subir|integrar)?\\s*(?:o\\s+)?merge"',
     '        r"\\b(?:(?:pode|podes|poderia)\\s+(?:fazer|dar|mandar|subir|integrar)?'
     '\\s*(?:o\\s+)?merge"'),

    ("…and discard with it", FI,
     '        r"\\b(?:" + _MAY + r"(?:descartar?|discard)"',
     '        r"\\b(?:(?:pode|podes|poderia)\\s+(?:descartar?|discard)"'),

    ("permission accepts a FIRST person, so a withdrawal reads as a grant", FI,
     '        r"|(?:you|y\'?all)\\s+(?:can|may|could)"',
     '        r"|(?:you|we|i|y\'?all)\\s+(?:can|may|could)"', PERM),

    # `_NEGATORS` IS NOT MUTATED HERE, and the reason is a finding rather than an omission:
    # it decides NOTHING today. Measured over fourteen negated sentences in both languages,
    # every one is refused by `_commands_its_clause` first — a negator does not open a clause,
    # so the clause-opening rule gets there before `_negated_before` is ever consulted. A cut
    # to that list is therefore invisible to any guard, which is what a surviving mutation
    # said. Filed on #161 with the measurement instead of being bolted onto this pass.

    # ── the five English halves the sweep found by RUNNING sentences ─────────────────────────────
    ("a decision may only be connected with `que`", PI,
     'r"(?:\\s*(?:que|that|:|—|-|,)\\s*)(?P<decision>[^\\n]{5,400})",',
     'r"(?:\\s*(?:que|:|—|-|,)\\s*)(?P<decision>[^\\n]{5,400})",'),

    ("the English withdrawal idiom goes back to Portuguese only", PI,
     '        r"|\\b(?:we|i)\\s*(?:\'re|\'m|\\s+are|\\s+am)?\\s+not\\s+(?:going\\s+to\\s+)?"\n'
     '        r"(?:build|do|deliver|ship|implement)(?:ing)?"',
     '        r"|\\bnobody\\s+will\\s+ever\\s+possibly\\s+build"'),

    ("a requirement can only be out of scope in Portuguese", PI,
     '        r"|is\\s+(?:out\\s+of\\s+scope|cancell?ed|dropped"\n'
     '        r"|no\\s+longer\\s+(?:needed|wanted|valid|in\\s+scope))"\n'
     '        r"|(?:was|has\\s+been)\\s+(?:cancell?ed|dropped))\\b"',
     '        )\\b"'),

    ("the duplicate copula is Portuguese again", PI,
     '_NOT_NEGATED + _card("number") + r"\\s+(?:[ée]|eh|s[ãa]o|is|are)\\s+(?:an?\\s+|uma?\\s+)?"',
     '_NOT_NEGATED + _card("number") + r"\\s+(?:[ée]|eh|s[ãa]o)\\s+(?:uma?\\s+)?"'),

    ("…and the duplicate NOUN is spelled twice again, one copy monolingual", PI,
     '        r"(?:" + _DUPLICATE_NOUN + r")" + _ATTACHED',
     '        r"(?:duplicad\\w*|duplicata|repetid\\w*|c[óo]pia)" + _ATTACHED'),

    ("criteria can only be rewritten in Portuguese", PI,
     '                       r"|(?:re)?write|define|update|adjust|fix)\\s+(?:os\\s+|the\\s+)?"',
     '                       r")\\s+(?:os\\s+)?"'),

    ("…and the criteria NOUN loses its English half", PI,
     '        r"(?:crit[ée]rios?|criteria|criterion)\\b" + _ATTACHED + _card("number")',
     '        r"crit[ée]rios?\\b" + _ATTACHED + _card("number")'),

    # ── the guard that makes a monolingual row impossible to add ─────────────────────────────────
    # MUTATED FROM THE PRODUCTION SIDE, because a weakened assertion in the guard's own file is
    # not something the guard can see — the first version of this row cut the check itself and
    # the suite stayed green, which proves only that a test cannot test itself.
    ("a monolingual row is added to the floor matcher and nobody notices", FI,
     "_BARE: tuple[tuple[str, re.Pattern[str]], ...] = (",
     '_PATTERNS = _PATTERNS + (("merge", re.compile(r"\\bmergeia logo\\b", re.I)),)\n\n'
     "_BARE: tuple[tuple[str, re.Pattern[str]], ...] = ("),

    ("…and to the product matcher", PI,
     "_SCANNED = frozenset(",
     '_PATTERNS = _PATTERNS + (("drop", re.compile(r"\\bnix o requisito (?P<number>\\d+)\\b",'
     " re.I)),)\n\n_SCANNED = frozenset("),

    # ── the tech-lead may not claim it acted ─────────────────────────────────────────────────────
    ("the chat may announce an action it has not taken", CONV,
     '    "- NEVER SAY YOU HAVE DONE IT, OR THAT YOU ARE ABOUT TO. A suggestion is an OFFER '
     'waiting on "', '    "" + "', PERM),
]

MUTATIONS += [
    # ── a hold in its own clause holds what follows ──────────────────────────────────────────────
    ("the hold stops reaching the instruction at all", FI,
     "    if _held_by_another_clause(body, m.start(), m.end()):\n        return None\n", ""),

    ("…and the bare-verb path loses the same fence, as it always lacked it", FI,
     "            if _held_by_another_clause(body, at + m.start(), min(at + m.end(), len(body))):\n"
     "                continue\n", ""),

    ("the hold stops having to OPEN its clause, so `a espera acabou` refuses a merge", FI,
     '_BARE_HOLD = re.compile(\n'
     '    r"^\\s*(?:(?:" + _LEADER_WORDS + r")\\b[,.!]?\\s*)*"',
     '_BARE_HOLD = re.compile(\n'
     '    r"^.*?"'),

    ("the hold only looks BEHIND, so a retraction after the verb is ignored", FI,
     "    for chunk in (head, tail):", "    for chunk in (head,):"),

    ("a bare refusal clause stops holding", FI,
     "            if clause.strip() and (_BARE_HOLD.match(clause) or _BARE_REFUSAL.match(clause)):",
     "            if clause.strip() and _BARE_HOLD.match(clause):"),
]
