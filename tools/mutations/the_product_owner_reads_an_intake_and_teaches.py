"""The third reading and its bound — the cuts that make a guess look like a measurement.

ROW 1 IS THE TEACHING READ AS A DEFECT (the marker parsed, the kind wrong). ROW 2 IS THE EVIDENCE
NOT PARSED (a reading with nothing to check). ROW 3 IS A STALE CONCEPT READ AS FRESH. ROW 4 IS A
MISSING CONCEPT READ AS PRESENT. ROW 5 IS NO BUNDLE READ AS ALTA. ROW 6 IS A MISSING REQUIREMENT
IGNORED. ROW 7 IS THE CAVEAT DROPPED from a "works like this" the bundle could not back. ROW 8 IS
THE CASE NEVER CLASSIFIED.
"""

TEST = "tests/test_the_product_owner_reads_an_intake_and_teaches.py"

MUTATIONS = [
    ("a teaching reply is read as a defect",
     "openfactory/product/role.py",
     '    kind = "misuse" if teach else "defect" if defect else "request" if request else "question"',
     '    kind = "defect" if teach else "defect" if defect else "request" if request else "question"'),

    ("the evidence is not parsed — a reading with nothing to check",
     "openfactory/product/role.py",
     "    concepts, requirements = _evidence_tokens(teach, evidence)",
     "    concepts, requirements = [], []"),

    ("a stale concept is read as fresh",
     "openfactory/product/reading.py",
     "            elif _is_stale(found, stale):",
     "            elif False:"),

    ("a missing concept is read as present",
     "openfactory/product/reading.py",
     "            if found is None:\n                verified[\"concepts\"][cited] = \"missing\"",
     "            if False:\n                verified[\"concepts\"][cited] = \"missing\""),

    ("no bundle is read as alta",
     "openfactory/product/reading.py",
     "    if bundle_dir is None:\n        level = BAIXA",
     "    if bundle_dir is None:\n        level = ALTA"),

    ("a missing requirement is ignored",
     "openfactory/product/reading.py",
     "        if not exists:\n            if level == ALTA:\n                level = MEDIA",
     "        if False:\n            if level == ALTA:\n                level = MEDIA"),

    ("the caveat is dropped from a 'works like this' the bundle could not back",
     "openfactory/product/module.py",
     '    if getattr(answer, "is_misuse", False) and bounded.confidence == BAIXA:',
     '    if False:'),

    ("the case is never classified",
     "openfactory/product/case.py",
     "        state = CLASSIFIED if (case.state == COLLECTING and kind) else case.state",
     "        state = case.state"),
]
