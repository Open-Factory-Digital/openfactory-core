"""Proven by breaking it — the board a reader sees is the board on disk, whichever process wrote it
(#393).

A person removed a card through the panel, and the product role in the worker went on describing
it as open for three turns: `product/board.py` trusted a per-process snapshot for six hours,
refreshed only by `list_tickets(updated_since=…)`, and `forget_board` in the panel never reached the
worker. The snapshot is a trade against a hosted API's rate limit; a whole read of a 300-card
`board.db` is 2.9 ms.

THREE CLAIMS:

  1. **A row whose whole read is cheap is read whole on every call** — no snapshot is trusted, so
     every write by another process (every writer of both local rows, an early stamp, a burst
     larger than one refresh) is seen on the next read.
  2. **The local row declares it, and only a literal `True` declares it** — a double answering
     every attribute truthily is not read as cheap.
  3. **A row that says nothing keeps the snapshot exactly** — the incremental read, and `fresh=True`
     still forcing a sweep, for every hosted row.

The guard is `tests/test_the_board_a_reader_sees_is_the_board_on_disk.py`; claim 3's `fresh` row
is guarded by `tests/test_product_board_reads.py`.
"""

TEST = "tests/test_the_board_a_reader_sees_is_the_board_on_disk.py"

BOARD = "openfactory/product/board.py"
BASE = "openfactory/adapters/tracker/base.py"
LOCAL = "openfactory/adapters/tracker/local.py"

MUTATIONS = [
    # ── claim 1: read whole, never from memory ───────────────────────────────────────────────
    ("THE DEFECT ITSELF: the reader trusts its own snapshot of a board another process writes",
     BOARD,
     "    trusted = not fresh and not whole_read_is_cheap(tracker)\n",
     "    trusted = not fresh\n"),

    ("the snapshot is consulted whatever the row declared",
     BOARD,
     "        snapshot = _SNAPSHOT.get(name) if trusted else None\n",
     "        snapshot = _SNAPSHOT.get(name) if not fresh else None\n"),

    # ── claim 2: the row declares it, literally ──────────────────────────────────────────────
    ("the local row stops declaring its whole read cheap",
     LOCAL,
     "    whole_read_is_cheap = True\n",
     "    whole_read_is_cheap = False\n"),

    ("any truthy attribute declares it — a MagicMock would re-read a hosted API on every call",
     BASE,
     '    return getattr(tracker, "whole_read_is_cheap", False) is True\n',
     '    return bool(getattr(tracker, "whole_read_is_cheap", False))\n'),

    # ── claim 3: the snapshot stays where a read costs something ─────────────────────────────
    ("every row is read whole — a hosted board loses what stands between it and its rate limit",
     BASE,
     '    return getattr(tracker, "whole_read_is_cheap", False) is True\n',
     "    return True\n"),

    ("`fresh=True` no longer forces a sweep on a row that keeps a snapshot",
     BOARD,
     "    trusted = not fresh and not whole_read_is_cheap(tracker)\n",
     "    trusted = not whole_read_is_cheap(tracker)\n",
     "tests/test_product_board_reads.py"),
]
