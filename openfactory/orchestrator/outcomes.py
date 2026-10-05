"""The box hands its outcomes back (ADR-0055 D7, #414).

THE BOX RUNS WHERE THE CARD'S CONSUMERS ARE NOT. A job runs on a remote box, or in a worker
thread, or under `openfactory run`, with no ledger, no conversation, no preview registry and no
record of the card's life — and it used to write every state it reached on the card itself, so a
pull request opened, a merge or a park reached the board and nothing else. The card's door
(`openfactory/lifecycle/`) is the one place that knows every consumer of a change.

So a runner writes on the card only its PROGRESS MARKS (`contracts/state.py::PROGRESS_MARKS`),
which say how far a job is and have no consequences, and every OUTCOME it reaches is noted on the
runner as it happens and stamped on the result its public method returns (`RunResult
.handed_back`). Whoever drove the runner — the worker's activity, the attended CLI, the panel's
in-process release — applies them through the door (`lifecycle/handed_back.apply`).

ONE WRAPPER FOR EVERY PUBLIC ENTRY, because the outcomes are reached in dozens of branches and
returned through as many `return`s: a rule that every return has to remember is the rule most of
them forget. The list is reset when the method starts, so a runner asked twice hands back only
what THIS call reached. Applied after each class rather than as a decorator line, which would
break the guards that parse a method's source (`machine.py`, at its end).
"""

from __future__ import annotations

import functools
from collections.abc import Callable


def hands_back[F: Callable](method: F) -> F:
    """Stamp the result `method` returns with the outcomes the runner reached during the call."""

    @functools.wraps(method)
    def handing_back(self, *args, **kwargs):
        self._handed_back = []
        result = method(self, *args, **kwargs)
        if result is not None and hasattr(result, "handed_back"):
            result.handed_back = list(self._handed_back)
        return result

    return handing_back  # type: ignore[return-value]
