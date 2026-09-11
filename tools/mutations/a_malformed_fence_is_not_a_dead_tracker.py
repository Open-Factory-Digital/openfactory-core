"""The tracker reads what a person wrote — a hand-typed fence, who asked, the whole thread.

Three reads the slice-2 design critique (2026-09-06) found broken by trying them in-tree, all on
the one door the three vendors share, and each with a silent failure shape: a card that kills
every read of itself, a vendor that never names who asked, a thread handed back as its first page.

ROW 1 IS THE DEFECT ITSELF put back: the unguarded `yaml.safe_load`. Rows 2-3 cut the Jira author
twice — the fallback, and the reporter — because a version that reads only `creator` passes the
fallback guard and still names the wrong person. Rows 4-5 are the two halves of the paged read:
one that stops following the token, and one that follows it and then keeps quiet when the service
stopped short of what it promised.
"""

TEST = "tests/test_the_tracker_reads_what_a_person_wrote.py"

MUTATIONS = [
    ("the guard is removed, so one hand-typed fence is a ScannerError out of every get_ticket",
     "openfactory/adapters/tracker/parse.py",
     "            try:\n"
     "                fm = yaml.safe_load(parts[1]) or {}\n"
     "            except yaml.YAMLError as exc:\n",
     "            if True:\n"
     "                fm = yaml.safe_load(parts[1]) or {}\n"
     "            if False:\n"),

    ("the Jira author falls back to nothing when the reporter is unset",
     "openfactory/adapters/tracker/jira.py",
     '        ticket.author = (_display(fields.get("reporter")) or _display(fields.get("creator"))'
     "\n"
     "                         or None)",
     '        ticket.author = _display(fields.get("reporter")) or None'),

    ("the Jira author is the account that clicked Create, not who the card is for",
     "openfactory/adapters/tracker/jira.py",
     '        ticket.author = (_display(fields.get("reporter")) or _display(fields.get("creator"))'
     "\n"
     "                         or None)",
     '        ticket.author = _display(fields.get("creator")) or None'),

    ("the un-limited ADO read stops following the continuation token — one page is the thread",
     "openfactory/adapters/tracker/azure_devops.py",
     '            params = {"order": "asc", "continuationToken": token}',
     "            break"),

    ("a read that ends short of totalCount is handed back without a word",
     "openfactory/adapters/tracker/azure_devops.py",
     "        if total is not None and len(rows) < total:",
     "        if False:"),
]
