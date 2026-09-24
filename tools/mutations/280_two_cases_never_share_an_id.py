"""#280: two intake cases one person opens in the same millisecond are two cases.

The row puts the clock-only id back. The test closes one case and opens the next for the same
person at the same `now`, then finds both in the store: the first dropped with its facts, the
second with its own.
"""

TEST = "tests/test_an_intake_is_a_typed_case.py"
CASE = "openfactory/product/case.py"

MUTATIONS = [
    ("a case's id is the clock again, so a case opened in the same millisecond erases the last",
     CASE,
     '            id=f"{thread}|{user}|{now:.3f}|{secrets.token_hex(4)}", thread=thread,',
     '            id=f"{thread}|{user}|{now:.3f}", thread=thread,'),
]
