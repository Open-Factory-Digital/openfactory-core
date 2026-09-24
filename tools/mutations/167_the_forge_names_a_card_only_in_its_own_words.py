"""#167, the second half, proven by breaking it — the card's own text reaches a forge that does not
own the card only in words it cannot read as one of its items.

#179 named the card in the forge's terms, and left the card's TEXT verbatim: the title under the
name and the objective in the body. The factory writes the tracker's mention into a title itself —
a split child is `Plan 92a — Guest hardening [auto-split of #37]`, `#37` being the parent on the
board — so on a local board over GitHub the child's commit and pull request title named
`acme/api#37`, and an objective's `Fixes #36` asked GitHub to close `acme/api#36` at the merge.

THREE CLAIMS:

  1. **Not owned: the title, the commit and the body carry no `#<number>` of the card's text**, and
     each one is written `card <number>`, so the reference stays readable and traceable.
  2. **Owned: the text is unchanged** — `#37` is the forge's own item 37, the card it names.
  3. **What counts as a mention**: a `#` directly before a number, wherever it stands; `C#`,
     `issue # 4` and `PROJ-12` are not.

The guard is `tests/test_the_forge_names_a_card_only_in_its_own_words.py`.
"""

TEST = "tests/test_the_forge_names_a_card_only_in_its_own_words.py"

MACHINE = "openfactory/orchestrator/machine.py"

MUTATIONS = [
    # ── claim 1: not owned ────────────────────────────────────────────────────────────────────
    ("THE DEFECT ITSELF, ON THE TITLE AND THE COMMIT: the card's own mentions reach the forge",
     MACHINE,
     '    return CardReference(title=without_mentions((ticket.title or "").strip()) or f"card {words}",\n',
     '    return CardReference(title=(ticket.title or "").strip() or f"card {words}",\n'),

    ("THE DEFECT ITSELF, IN THE BODY: the objective's `Fixes #36` reaches the forge verbatim",
     MACHINE,
     '            "", "## Objective", card.text(ticket.objective), "", "## Validations",\n',
     '            "", "## Objective", ticket.objective, "", "## Validations",\n'),

    # ── claim 2: owned ────────────────────────────────────────────────────────────────────────
    ("the owned card's text is rewritten too, so the forge's own `#37` stops naming its item",
     MACHINE,
     "        return words if self.owned else without_mentions(words)\n",
     "        return without_mentions(words)\n"),

    ("the owned verdict is not kept, so an owned card's objective is rewritten", MACHINE,
     '                             closing=f"{keyword} {mention}" if keyword else "", owned=True)',
     '                             closing=f"{keyword} {mention}" if keyword else "")'),

    ("the owned card's text is never rewritten AND neither is anyone else's", MACHINE,
     "        return words if self.owned else without_mentions(words)\n",
     "        return words\n"),

    # ── claim 3: what counts as a mention ─────────────────────────────────────────────────────
    ("any `#` is a mention, so `C#` is rewritten", MACHINE,
     '_A_MENTION = re.compile(r"#(?=\\d)")\n',
     '_A_MENTION = re.compile(r"#")\n'),

    ("the sign is dropped and the number left bare — no mention, and nothing says what it was",
     MACHINE,
     "    return _A_MENTION.sub(word, text or \"\")\n",
     "    return _A_MENTION.sub(\"\", text or \"\")\n"),

    ("only the first mention is rewritten", MACHINE,
     "    return _A_MENTION.sub(word, text or \"\")\n",
     "    return _A_MENTION.sub(word, text or \"\", count=1)\n"),

    ("a mention glued to a name runs into it: `acme/issuescard 37`", MACHINE,
     "        return \"card \" if before.isspace() or before in \"([{\\\"'`\" else \" card \"\n",
     "        return \"card \"\n"),

    ("a mention after a bracket gets a stray space: `( card 37)`", MACHINE,
     "        return \"card \" if before.isspace() or before in \"([{\\\"'`\" else \" card \"\n",
     "        return \"card \" if before.isspace() else \" card \"\n"),

    ("a mention that opens the text gets a stray space in front of it", MACHINE,
     '        before = found.string[found.start() - 1] if found.start() else " "\n',
     '        before = found.string[found.start() - 1] if found.start() else "x"\n'),
]
