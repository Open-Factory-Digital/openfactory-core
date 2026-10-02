"""On Jira, a card the product role files is placed in Backlog, and a reported defect is followed —
the placement and the delivery loop keyed on the tracker's own ref, never on a number (#479).

Run:  .venv/bin/python tools/mutate.py tools/mutations/479_a_jira_key_is_a_card_ref.py

Rows 1-4 put the number back, one site at a time — the defect as it shipped: the card a person asked
for, the defect's placement, the defect's delivery loop, and the breakdown's filer each keyed on a
number a Jira key does not carry. Rows 5-7 are the other direction: the key stops being the one a
GitHub-shaped ref always had (`#12` asked of the board, or followed as `defeito-#12`).
"""

TEST = "tests/test_a_jira_key_is_a_card_ref.py"

MOD = "openfactory/product/module.py"

MUTATIONS = [
    ("TODAY'S DEFECT: the card a person asked for is placed only when its ref is a number", MOD,
     "        # sat inside the skipped block. The board port takes the provider's ref (C-05).\n"
     "        key = canonical_ref(ref)\n",
     "        # sat inside the skipped block. The board port takes the provider's ref (C-05).\n"
     '        key = canonical_ref(ref) if canonical_ref(ref).isdigit() else ""\n'),

    ("a reported defect is placed, and followed, only when its ref is a number", MOD,
     "        # `file_ticket`: a Jira key was 0, so a reported defect was neither placed nor "
     "followed\n"
     "        key = canonical_ref(ref)\n",
     "        # `file_ticket`: a Jira key was 0, so a reported defect was neither placed nor "
     "followed\n"
     '        key = canonical_ref(ref) if canonical_ref(ref).isdigit() else ""\n'),

    ("a reported defect on Jira is placed, and its delivery is never followed", MOD,
     "        if key:\n"
     "            self._track_defect(key, conversation=conversation, requester=requester)\n",
     "        if key.isdigit():\n"
     "            self._track_defect(key, conversation=conversation, requester=requester)\n"),

    ("a requirement's card is placed only when its ref is a number", MOD,
     "            key = split_repo_ref(ref)[1]\n",
     '            key = split_repo_ref(ref)[1] if split_repo_ref(ref)[1].isdigit() else ""\n'),

    ("the card a person asked for is placed under the ref as typed — `#12`, not the `12` a "
     "GitHub board was always asked for", MOD,
     "        # sat inside the skipped block. The board port takes the provider's ref (C-05).\n"
     "        key = canonical_ref(ref)\n",
     "        # sat inside the skipped block. The board port takes the provider's ref (C-05).\n"
     "        key = str(ref)\n"),

    ("a reported defect is followed as `defeito-#12`, a subject no earlier loop had", MOD,
     "            self._track_defect(key, conversation=conversation, requester=requester)\n",
     "            self._track_defect(str(ref), conversation=conversation, requester=requester)\n"),

    ("a requirement's card is placed under the ref as filed, not the part after its repository",
     MOD,
     "            key = split_repo_ref(ref)[1]\n",
     "            key = str(ref)\n"),
]
