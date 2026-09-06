"""A case does not outlive its test — the guard for `conftest._a_case_does_not_outlive_its_test`.

TWO TESTS IN DEFINITION ORDER, ON PURPOSE. The first opens an intake on the bucket and the
conversation most of the suite shares (`books`, `C1`); the second must find nothing there. Under
the fixture that is true whatever ran before; without it the second test reads the first one's
case — the shape that made a fake in `test_sweep_client_surface.py` receive an `intake=` it never
asked for, on CI, on commits that did not touch the store (2026-09-06).
"""

from __future__ import annotations

import time
from types import SimpleNamespace

from openfactory.product import case as _case

BOOKS = SimpleNamespace(name="books")
ANSWER = SimpleNamespace(text="?", reading=None, is_defect=False, is_request=False)


def test_1_a_test_opens_an_intake_in_the_shared_conversation():
    opened = _case.note_turn(BOOKS, "C1", "UADM", "o backup falha às segundas", ANSWER,
                             now=time.time())
    assert opened.open and opened.facts, "the first test really did leave an open case"
    found = _case.current(BOOKS, "C1", "UADM")
    assert found is not None and found.id == opened.id


def test_2_the_next_test_starts_from_nothing():
    assert _case.current(BOOKS, "C1", "UADM") is None, (
        "the previous test's intake survived into this one — the store is not cleared between "
        "tests, and `proposed()` would now target a case this test never opened")
    assert _case.block_for(BOOKS, "C1", "UADM") == ""
    assert not _case._CASES.get("books"), "the shared bucket still holds the previous test's case"
