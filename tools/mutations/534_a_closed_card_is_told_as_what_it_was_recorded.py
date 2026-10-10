"""A close says the word it recorded, on either path, from either column (#534), proven by
breaking it.

Run:  .venv/bin/python tools/mutate.py \
        tools/mutations/534_a_closed_card_is_told_as_what_it_was_recorded.py

A card the product role filed, in Done, closed with `card_close`: recorded `completed` (#162's
delivered), answered "stays in the history as not done". The claims, each a row:

  1. the product role's answer reads the same `delivered` its record was written with (row 1);
  2. the close control says "delivered" for a finished card, from the reading `_card_close`
     decides with (rows 2-3);
  3. the delivered sentence says delivered (row 4).
"""

TEST = "tests/test_a_card_nobody_started_can_be_closed_and_removed.py"

MODULE = "openfactory/product/module.py"
CATALOG = "openfactory/actions/catalog.py"
VOICE = "openfactory/product/voice.py"

MUTATIONS = [
    ("TODAY'S DEFECT: the role's answer says not done over a delivered record", MODULE,
     '            result.detail = card_withdrawn_result(ref=number, how="delivered" if delivered\n'
     '                                                  else "closed", language=lang)\n',
     '            result.detail = card_withdrawn_result(ref=number, how="closed", language=lang)\n'),
    ("the close control never hears that the card is finished", CATALOG,
     "                                   removes=can_remove, finished=finished,\n",
     "                                   removes=can_remove, finished=False,\n"),
    ("a finished card's control still says not done", VOICE,
     '    if finished:\n        words["ask_close"] = words["ask_close_finished"]\n',
     '    if False:\n        words["ask_close"] = words["ask_close_finished"]\n'),
    ("the delivered sentence says not done", VOICE,
     '        "delivered": "closed {ref} as delivered — it was already finished, and what it shipped "\n',
     '        "delivered": "closed {ref} as not done — it was already finished, and what it shipped "\n'),
]
