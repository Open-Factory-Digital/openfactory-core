"""A front that builds on one the breakdown did not file is held, and said with the front it waits on
(#576), proven by breaking it.

Run:  .venv/bin/python tools/mutate.py \
        tools/mutations/576_a_front_waits_on_the_front_it_builds_on.py

The review refused a breakdown's first front and the second, built on the first's rows, was filed
anyway; the pre-flight parked it a move later. The claims, each a row:

  1. the decomposition is asked what each front builds on, and a position outside its own list is
     read as no dependency;
  2. a front on one that was not filed is held, down the chain, and filed after its base when it
     was listed first; the results keep the decomposition's order; a circle files in its own order;
  3. the reply names every front that was not opened, the held one with the one it waits on.
"""

TEST = "tests/test_a_front_waits_on_the_front_it_builds_on.py"
ROLE = "openfactory/product/role.py"
MODULE = "openfactory/product/module.py"
VOICE = "openfactory/product/voice.py"
CONFIRM = "openfactory/product/confirm.py"

MUTATIONS = [
    # 1. the decomposition says it
    ("the decomposition is never asked what a front builds on", ROLE,
     '             "already_on_board": str|null, "builds_on": [int]}]}\n',
     '             "already_on_board": str|null}]}\n'),
    ("a position outside the breakdown is kept as a dependency", ROLE,
     "            kept = [b for b in dict.fromkeys(issue.builds_on)\n"
     "                    if 1 <= b <= len(issues) and b != position]\n",
     "            kept = list(issue.builds_on)\n"),

    # 2. filing
    ("TODAY'S DEFECT: a front on a refused one is filed anyway", MODULE,
     "            if waits_on is not None:\n",
     "            if False:\n"),
    ("the fronts are filed in the order they were listed", MODULE,
     "        for index in _filing_order(fronts):\n",
     "        for index in range(len(fronts)):\n"),
    ("the results come back in the order they were filed", MODULE,
     "        results = [filed[index] for index in range(len(fronts))]\n",
     "        results = list(filed.values())\n"),
    ("a circle files nothing at all", MODULE,
     "            ready = left\n",
     "            return order\n"),

    # 3. the reply
    ("the reply names the first front not opened, and no other", CONFIRM,
     "        out += said[\"not_registered_some\"].format(n=len(failed)) + \" \".join(told)\n",
     "        out += said[\"not_registered_some\"].format(n=len(failed)) + told[0]\n"),
    ("when nothing was opened, the reply names the first front alone", CONFIRM,
     "        return head + \" \".join(told)\n",
     "        return head + told[0]\n"),
    ("the held sentence does not say which front it waits on", VOICE,
     '        "en": ("“{base}” was not opened, so I held “{title}”, which builds on it — ask for the "',
     '        "en": ("a front was not opened, so I held “{title}”, which builds on it — ask for the "'),
]
