"""The inventory counts what it could not place — the cuts that would make it quietly wrong.

ROW 1 IS THE REMAINDER VANISHING: a file no rule places called `code`, and the coverage table
divides by a denominator that hides it.

ROWS 2-3 ARE CONTENT SHAPE SWITCHED OFF: a fully commented file read as live code (the pilot's
fifteen), a barrel read as behaviour.

ROWS 4-6 ARE THE CREDENTIAL SCAN: the value recorded instead of the key (the report becomes the
leak); a placeholder graded high; a value that only NAMES a variable graded high.

ROWS 7-8 ARE THE COVERAGE TABLE: `unclassified` excused wholesale (the one row that must stay
visible), and concepts counted per file cited instead of per concept.

ROW 9 IS THE BLINDNESS DROPPED: an unreadable directory declared by the walk and never gapped.

ROW 10 IS THE READER GUESSING: an unknown schema accepted as the one it knows.

ROW 11 IS THE BACKFILL KEEPING THE INVENTORY TO ITSELF: its gaps never join the manifest.
"""

TEST = "tests/test_the_inventory_counts_what_it_could_not_place.py"

MUTATIONS = [
    ("a file no rule places is silently `code`",
     "openfactory/knowledge/inventory.py",
     '    return "unclassified", f"no rule places `{suffix or name}`"',
     '    return "code", f"no rule places `{suffix or name}`"'),

    ("a fully commented file is live code",
     "openfactory/knowledge/inventory.py",
     "        if comments / len(lines) >= DEAD_CODE_SHARE:",
     "        if comments / len(lines) > 1.0:"),

    ("a barrel module is behaviour",
     "openfactory/knowledge/inventory.py",
     "    if live and all(_ONLY_IMPORTS.match(ln) for ln in live):",
     "    if False and all(_ONLY_IMPORTS.match(ln) for ln in live):"),

    ("the scan records the VALUE under `key` — the report is the leak",
     "openfactory/knowledge/inventory.py",
     '        found.append(SecretRisk(path=rel, key=hit.group("key"), line=number, severity=low,',
     '        found.append(SecretRisk(path=rel, key=hit.group("value"), line=number, severity=low,'),

    ("a placeholder is graded high",
     "openfactory/knowledge/inventory.py",
     '        low = ("low" if (_PLACEHOLDER.match(value) or _NAMES_A_VARIABLE.match(value))',
     '        low = ("low" if (_NAMES_A_VARIABLE.match(value))'),

    ("a value that names a variable is graded high",
     "openfactory/knowledge/inventory.py",
     '        low = ("low" if (_PLACEHOLDER.match(value) or _NAMES_A_VARIABLE.match(value))',
     '        low = ("low" if (_PLACEHOLDER.match(value))'),

    ("`unclassified` is excused wholesale",
     "openfactory/knowledge/inventory.py",
     '    "unclassified": (NO_EXEMPTION, False),',
     '    "unclassified": (NO_EXEMPTION, True),'),

    ("concepts are counted per file cited, not per concept",
     "openfactory/knowledge/inventory.py",
     "        touched = {kinds[s.path] for s in concept.sources if s.path in kinds}",
     "        touched = [kinds[s.path] for s in concept.sources if s.path in kinds]"),

    ("an unreadable directory is declared by the walk and never gapped",
     "openfactory/knowledge/inventory.py",
     "    for where in inventory.unreadable:",
     "    for where in []:"),

    ("an unknown schema is read as the one it knows",
     "openfactory/knowledge/inventory.py",
     '    if not isinstance(data, dict) or str(data.get("schema_version", "")) != SCHEMA_VERSION:',
     '    if not isinstance(data, dict):'),

    ("the backfill keeps the inventory's gaps out of the manifest",
     "openfactory/onboarding/onboard.py",
     "            gaps=list(gaps) + inventory_gaps(inventory),",
     "            gaps=list(gaps),"),
]
