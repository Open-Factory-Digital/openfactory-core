"""The product owner writes the backlog order — the capability cut at each provider, and the verb.

ROWS 1-2 ARE AZURE BOARDS LYING WITH A NUMBER. A rank that is not the midpoint lands the card
somewhere else than between its neighbours; a rank written to `StackRank` on a Scrum process
reorders nothing while reporting success, because that process sorts by `BacklogPriority`.

ROW 1 SURVIVED THE FIRST RUN, and the guard was the defect. Its neighbours were ranked 1000 and
3000: the midpoint is 2000 — and so is "the predecessor plus a fixed step of 1000", the exact wrong
rule the row installs. The fixture's numbers made the two formulas agree. They are 1000 and 5000
now (3000 against 2000), and the guard says why in its own docstring. Same lesson as
`a_fingerprint_gains_a_reader` ROW 4: a fixture that puts its values where the wrong rule also
lands is decoration.

ROW 3 IS GITHUB PROJECTS FORGETTING THE ANCHOR: every placement goes to the top, so "7, 3, 9"
lands as "9, 3, 7".

ROW 4 IS JIRA RANKING ON THE WRONG SIDE of the anchor.

ROWS 5-6 ARE THE MODULE: a chain that never advances its anchor puts every card at the top in
turn — the reverse order — and a board that cannot rank would raise in a listener instead of
saying so.

ROW 7 IS THE SPEND-ADJACENT GATE: the next promote follows this order, so an order anybody can
write without a yes is an order anybody can spend against.
"""

TEST = "tests/test_the_product_owner_writes_the_backlog_order.py"

MUTATIONS = [
    ("Azure Boards writes the predecessor's rank plus a step instead of the midpoint, so the card "
     "lands past its successor",
     "openfactory/adapters/board/azure_devops.py",
     "            if prev_rank is not None and next_rank is not None:\n"
     "                value = (prev_rank + next_rank) / 2",
     "            if prev_rank is not None and next_rank is not None:\n"
     "                value = prev_rank + 1000.0"),

    ("Azure Boards always writes StackRank, so a Scrum process — which sorts by BacklogPriority "
     "— is reordered in a field it ignores",
     "openfactory/adapters/board/azure_devops.py",
     "        field = next((f for f in self._RANK_FIELDS\n"
     "                      if any(c.get(f) is not None for c in cards.values())), self._RANK_FIELDS[0])",
     "        field = self._RANK_FIELDS[0]"),

    ("GitHub Projects drops the anchor, so every placement goes to the top and the order comes "
     "out reversed",
     "openfactory/adapters/tracker/github_project.py",
     '        if after_item:\n            args += ["-f", f"after={after_item}"]',
     '        if False:\n            args += ["-f", f"after={after_item}"]'),

    ("Jira ranks BEFORE the anchor instead of after it",
     "openfactory/adapters/board/jira.py",
     '            payload["rankAfterIssue"] = after',
     '            payload["rankBeforeIssue"] = after'),

    ("the module never advances the anchor, so each card is placed at the top in turn and the "
     "order lands reversed",
     "openfactory/product/module.py",
     "                if placed:\n                    previous = str(number)",
     "                if placed:\n                    pass"),

    ("a board that cannot rank is not refused with a sentence — it raises inside the listener",
     "openfactory/product/module.py",
     "        if not isinstance(board, Rankable):\n"
     "            return [WriteResult(ok=False, detail=\"este quadro ainda não aceita reordenação por \"",
     "        if False:\n"
     "            return [WriteResult(ok=False, detail=\"este quadro ainda não aceita reordenação por \""),

    ("the row rewrites the order without a yes",
     "openfactory/actions/catalog.py",
     "    if not _said_yes(yes):\n        return refused(INVALID, f\"nothing was moved: this rewrites the order of {len(wanted)} \"",
     "    if False:\n        return refused(INVALID, f\"nothing was moved: this rewrites the order of {len(wanted)} \""),
]
