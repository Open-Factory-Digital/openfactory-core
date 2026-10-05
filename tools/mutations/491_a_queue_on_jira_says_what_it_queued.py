"""On Jira, a queue confirmed says which cards it queued (#491).

Run:  .venv/bin/python tools/mutate.py tools/mutations/491_a_queue_on_jira_says_what_it_queued.py

Row 1 is the defect as it shipped: the refs that landed reduced to the ones that are numbers, so a
queue on Jira answers that nothing went in while every card sits in the queue. Rows 2-3 break the
sentence's spelling: every ref decorated as GitHub decorates one (`#DAR-9`), or none decorated (a
numbered board's `#1` read as `1`, which is not how it always read). Row 4 keeps the refs as
`promote` decorated them, never in their one spelling. Rows 5-6 break the half-refused queue: a
card the board refused named as queued, and the reply that was the refusal alone, the card that
went in unnamed.
"""

TEST = "tests/test_a_queue_on_jira_says_what_it_queued.py"

CONFIRM = "openfactory/product/confirm.py"
VOICE = "openfactory/product/voice.py"

MUTATIONS = [
    # re-pinned 2026-10-04: one line keeps the tracker's refs in the approved order (#491 + #497)
    ("TODAY'S DEFECT: the refs that landed are only the ones that are numbers", CONFIRM,
     "    landed = list(dict.fromkeys(canonical_ref(r.ref) for r in results if r.ok and r.ref))\n",
     "    from openfactory.contracts.refs import ref_numbers\n"
     "    landed = ref_numbers(r.ref for r in results if r.ok and r.ref)\n"),

    # re-pinned 2026-10-05: the sentence is picked by whether the order reached the board (#512)
    ("the sentence decorates every ref as GitHub does: #DAR-9", VOICE,
     'format(items=", ".join(ref_label(n) for n in numbers))',
     'format(items=", ".join(f"#{n}" for n in numbers))'),

    # re-pinned 2026-10-05: the sentence is picked by whether the order reached the board (#512)
    ("the sentence names every ref bare, so a numbered board's #1 reads as 1", VOICE,
     'format(items=", ".join(ref_label(n) for n in numbers))',
     'format(items=", ".join(str(n) for n in numbers))'),

    # retired 2026-10-04: "the refs are kept as promote decorated them" is an equivalent mutation
    # since #497 — `ref_label` strips a typed `#` from a key too, so `queued` names `#DAR-9` as
    # `DAR-9` whether or not `_confirm_queue` normalised it first

    # re-pinned 2026-10-04: one line keeps the tracker's refs in the approved order (#491 + #497)
    ("a card the board refused is named among the ones queued", CONFIRM,
     "    landed = list(dict.fromkeys(canonical_ref(r.ref) for r in results if r.ok and r.ref))\n",
     "    landed = list(dict.fromkeys(canonical_ref(r.ref) for r in results if r.ref))\n"),

    ("a half-refused queue answers with the refusal alone, the card that went in unnamed", CONFIRM,
     "    if not landed:\n"
     "        return (_client_detail(failed[0].detail, lang, project=project) if failed\n"
     "                else _said(lang)[\"not_queued\"])\n",
     "    if not landed or failed:\n"
     "        return (_client_detail(failed[0].detail, lang, project=project) if failed\n"
     "                else _said(lang)[\"not_queued\"])\n"),
]
