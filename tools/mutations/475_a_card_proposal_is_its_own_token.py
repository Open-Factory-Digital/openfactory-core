"""A card proposal's confirmation button approves that card and no other (#475).

Run:  .venv/bin/python tools/mutate.py tools/mutations/475_a_card_proposal_is_its_own_token.py

Row 1 is the defect as it shipped: a card's title read only from a draft its entry does not have.
Rows 2-3 lose the card the person was shown, whole or past 800 characters. Row 4 loses the request
a plain ticket was filed from.
"""

TEST = "tests/test_a_card_proposal_is_its_own_token.py"

STAGING = "openfactory/product/staging.py"

MUTATIONS = [
    ("TODAY'S DEFECT: a card's title is read only from a draft its entry does not have", STAGING,
     '(said["title"], getattr(draft, "title", "") or entry.get("title", "")),',
     '(said["title"], getattr(draft, "title", "")),'),

    ("the card the person was shown is not in the fingerprint", STAGING,
     '    elif entry.get("card"):\n',
     "    elif False:\n"),

    ("a card is cut where a draft's body is, so a late criterion is not in it", STAGING,
     "str(entry['card'])[:4000]",
     "str(entry['card'])[:800]"),

    ("a plain ticket's request is not in the fingerprint", STAGING,
     'or entry.get("text", "") or entry.get("described", "")),',
     'or entry.get("text", "")),'),
]
