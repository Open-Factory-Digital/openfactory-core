"""A case does not outlive its test — the guard for `conftest._a_case_does_not_outlive_its_test`.

TWO TESTS IN DEFINITION ORDER, ON PURPOSE. The first opens an intake on the bucket and the
conversation most of the suite shares (`books`, `C1`); the second must find nothing there. Under
the fixture that is true whatever ran before; without it the second test reads the first one's
case — the shape that made a fake in `test_sweep_client_surface.py` receive an `intake=` it never
asked for, on CI, on commits that did not touch the store (2026-09-06).
"""

from __future__ import annotations

import os
import time
from types import SimpleNamespace

from openfactory.product import case as _case

BOOKS = SimpleNamespace(name="books")
#: a project WITH a home on disk — `repo_path` gives `case._path` a file to write, which the bare
#: namespace above never has; the disk half of the leak can only be seen through this one
PERSISTED = SimpleNamespace(name="books", repo_path="/t")
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


def test_3_a_test_writes_its_intake_to_a_directory_of_its_own():
    _case.note_turn(PERSISTED, "C1", "UADM", "o backup falha às segundas", ANSWER,
                    now=time.time())
    path = _case._path(PERSISTED)
    assert path is not None and path.is_file(), f"the case was not persisted: {path}"
    assert str(path).startswith(os.environ["OPENFACTORY_LOG_DIR"]), (
        "the journals went to the default directory — a machine where that is writable would "
        "hand this case to the next run")


def test_4_the_next_test_reads_nothing_back_from_disk():
    """The reload happens on the first touch after the clear — `current()` is that touch.

    NO STATE SHARED WITH `test_3`, on purpose: under `-n 2` the two may run in different workers,
    and a module-level list written by one is empty in the other. The previous test's directory is
    computed the way the fixture names it, so this one can assert it is not its own."""
    import hashlib

    assert _case.current(PERSISTED, "C1", "UADM") is None, (
        "the previous test's case came back through the clear, from disk")
    path = _case._path(PERSISTED)
    assert path is not None and not path.exists()
    previous = hashlib.sha1(
        b"tests/test_a_case_does_not_outlive_its_test.py::"
        b"test_3_a_test_writes_its_intake_to_a_directory_of_its_own").hexdigest()[:12]
    assert previous not in str(path), "two tests share one journal directory"
    own = os.environ["OPENFACTORY_LOG_DIR"]
    assert own in str(path) and own.split("/")[-1] != previous
