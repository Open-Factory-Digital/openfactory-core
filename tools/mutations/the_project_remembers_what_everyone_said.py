"""Project memory across stores — the cuts that make it a scan, a leak, or a hoard.

ROW 1 IS THE LEAK: a private conversation's turns reach everybody's question.
ROW 2 IS THE ECHO: the current conversation comes back as "elsewhere".
ROW 3 IS THE HOARD: the index never forgets what the stores forgot.
ROW 4 IS THE DOUBLE: a row read twice is indexed twice.
ROW 5 IS THE SCAN: the index is never saved, so every turn rebuilds it from the stores.
ROW 6 IS THE GAP: the window is never widened, so a busy day's middle rows are never indexed.
ROW 7 IS FLAT RANKING: a rare word weighs no more than a common one.
ROW 8 IS THE ROLE NOT TOLD: the ask turn drops the block.
"""

TEST = "tests/test_the_project_remembers_what_everyone_said.py"

MUTATIONS = [
    ("a private conversation's turns reach everybody",
     "openfactory/memory/recall.py",
     "            and (not is_private(h.said.where) or h.said.where == own)]",
     "            and True]"),

    ("the current conversation comes back as 'elsewhere'",
     "openfactory/memory/recall.py",
     "            if h.said.where != exclude_where\n",
     "            if True\n"),

    ("the index never forgets what retention forgot",
     "openfactory/memory/recall.py",
     "    forgotten = index.forget_before(cutoff)",
     "    forgotten = 0"),

    ("a row read twice is indexed twice",
     "openfactory/memory/recall.py",
     "        if said.id in self.rows or not said.text.strip():\n            return False",
     "        if not said.text.strip():\n            return False"),

    ("the index is never saved — every turn rebuilds it from the stores",
     "openfactory/memory/recall.py",
     "    if added or forgotten:\n        try:\n            index.save(path)",
     "    if False:\n        try:\n            index.save(path)"),

    ("the window is never widened",
     "openfactory/memory/recall.py",
     "            fetch = min(fetch * 4, FETCH_CEILING)\n            continue",
     "            break"),

    ("a rare word weighs no more than a common one",
     "openfactory/memory/recall.py",
     "            weight = 1.0 + math.log(total / len(ids))",
     "            weight = 1.0"),

    ("the ask turn drops the block",
     "openfactory/runtime/temporal/activities.py",
     "    before = _with_elsewhere(project, before, request, own=key, agent_name=agent_name)",
     "    before = before"),
]
