"""A requirement's delivery is followed on the tracker's own refs — every Jira key, and a card filed
in another repository of the product (#485).

Run:  .venv/bin/python tools/mutate.py \
        tools/mutations/485_a_requirements_delivery_keys_on_the_trackers_refs.py

Rows 1-2 are the defect as it shipped, at the two places it could live again: the refs a loop is
keyed on reduced to the ones that are numbers, and the filer handing only those to it. Rows 3-7
break the loop's one spelling: refs kept as typed (`#12` and `12` two cards), an empty ref kept,
the board order lost (the GitHub row's loop no longer byte-identical), the filer's refs handed
through un-canonicalised, and a loop opened over nothing. Rows 8-10 break the loop's readers back
to numbers — the release question's, the event's (`events.issues_of`) and the sweep's
(`followup.delivered`) — so a Jira key or a qualified ref is never found, or a delivery closes on
the cards that are numbers alone.
"""

TEST = "tests/test_a_requirements_delivery_keys_on_the_trackers_refs.py"

REFS = "openfactory/contracts/refs.py"
MOD = "openfactory/product/module.py"
FOLLOWUP = "openfactory/product/followup.py"
EVENTS = "openfactory/product/events.py"

MUTATIONS = [
    ("TODAY'S DEFECT: the loop is keyed on the refs that are numbers", REFS,
     '    unique = {canonical_ref(r) for r in refs} - {""}\n',
     "    unique = {str(n) for n in ref_numbers(refs)}\n"),

    ("…and the filer hands the loop only the refs that are numbers", MOD,
     "            fresh = deliveries_to_open({requirement.number: landed},\n",
     "            fresh = deliveries_to_open({requirement.number: [\n"
     "                r for r in landed if str(r).lstrip(\"#\").isdigit()]},\n"),

    ("the refs are kept as typed, so #12 and 12 are two cards", REFS,
     '    unique = {canonical_ref(r) for r in refs} - {""}\n',
     '    unique = {str(r).strip() for r in refs} - {""}\n'),

    ("an empty ref is kept as a card the loop waits for", REFS,
     '    unique = {canonical_ref(r) for r in refs} - {""}\n',
     "    unique = {canonical_ref(r) for r in refs}\n"),

    ("the board order is lost: 12 sorts before 3, and the GitHub row's loop moves", REFS,
     "    return sorted(unique, key=ref_sort_key)\n",
     "    return sorted(unique)\n"),

    ("the loop is written with the refs as the filer handed them", FOLLOWUP,
     "    keyed = {req: canonical_refs(refs) for req, refs in filed.items()}\n",
     "    keyed = {req: [str(r) for r in refs] for req, refs in filed.items()}\n"),

    ("a loop is opened over no card at all", FOLLOWUP,
     "        for req, issues in sorted(keyed.items())\n"
     "        if str(req) not in already and issues\n",
     "        for req, issues in sorted(keyed.items())\n"
     "        if str(req) not in already\n"),

    ("the release question matches the card as typed again", FOLLOWUP,
     "    want = canonical_ref(issue)\n",
     "    want = str(issue)\n"),

    ("the event's reader keeps only the numbers of the loop it reads", EVENTS,
     "    from openfactory.contracts.refs import canonical_ref\n\n"
     "    return {canonical_ref(n) for n in str((loop.context or {}).get(\"issues\") or \"\")",
     "    from openfactory.contracts.refs import ref_number\n\n"
     "    return {str(ref_number(n)) for n in str((loop.context or {}).get(\"issues\") or \"\")"),

    ("the sweep's reader waits only on the cards that are numbers", FOLLOWUP,
     '        issues = {canonical_ref(n) for n in (loop.context.get("issues") or "").split(",")\n'
     "                  if n.strip()}\n",
     '        issues = {canonical_ref(n) for n in (loop.context.get("issues") or "").split(",")\n'
     "                  if n.strip().isdigit()}\n"),
]
