"""The live preview tests take turns on the daemon (#265).

THEY SHARE ONE DAEMON AND ONE SET OF NAMES. `tests/test_a_preview_runs_on_a_real_daemon.py`,
`tests/test_a_preview_starts_on_a_real_daemon.py` and `tests/test_a_preview_opens_on_one_machine.py`
each bring up `openfactory-pv-acme-12` — the unit a person's card is — and a start takes down
whatever of its unit is already on the daemon, which is the point of a fresh start and exactly
wrong when the stack belongs to the test next door. Under `-n auto` they land on different
workers and can run at once, so each takes this lock for its whole run: a file lock, because the
workers are processes, in the temporary directory every worker shares.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from collections.abc import Iterator


@contextlib.contextmanager
def one_at_a_time() -> Iterator[None]:
    import fcntl  # POSIX only, like the daemon these tests need

    path = os.path.join(tempfile.gettempdir(), "openfactory-live-preview.lock")
    with open(path, "a", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


class TheCard:
    """The card's tracker, for a live preview test: what the preview says on the card is kept here.

    THESE TESTS REGISTER `Project(name="acme")`, whose GitHub row names no repository, and the step
    that brings a preview up comments on the card through the project's tracker. Through the real
    row that comment went to the repository the suite runs from, under the operator's own `gh`
    login: 31 "Preview up" comments on `openfactory-core#12` between 2026-09-29 and 2026-10-01
    (`adapters/github_cli.py`). Each test installs this in place of `activities._tracker_for`, and
    asserts what was said."""

    def __init__(self) -> None:
        self.said: list[tuple[str, str]] = []

    def comment(self, ref: str, body: str) -> None:
        self.said.append((str(ref), body))
