"""#165 and #166: the intake memo hands out a copy, and readers arriving together share one read.

Two properties on the same dozen lines, so one plan. The first three rows are #165 — each is a way
the answer could still be the memo's own object — and the rest are #166, where every row but the
first is a way single flight can be PRESENT and wrong: shared on success only, shared across
loops, owned by whichever reader happened to arrive first, or left behind after it ended.

`146_the_floor_is_read_on_a_clock.py` still holds the window itself (consulted, expiring, never
storing an unread answer, dropped on a blip); its anchors on these lines were re-pinned with this.
"""

TEST = "tests/test_the_intake_memo_is_read_once_and_handed_out_as_a_copy.py"
READING = "openfactory/floor/reading.py"

MUTATIONS = [
    # RE-PINNED 2026-09-19: the single flight moved into `_OneAtATime`, which the budget
    # memo now shares. The claim is unchanged; only where the line lives is.
    # ── #165: what a caller is handed is the memo's own object ──────────────────────────────────
    ("a reader inside the window is handed the stored dict, so its write rewrites the window",
     READING,
     "        return copy.deepcopy(_intake_memo[1])",
     "        return _intake_memo[1]"),

    ("the readers of a fresh read are handed the object the memo then stores", READING,
     "        await _intake_read.shared(lambda flight: _read_intake(flight, client, stamp)))",
     "        await _intake_read.shared(lambda f: _read_intake(f, client, stamp)))  # no copy",
     ),

    ("the copy is shallow, so every watcher row is still shared", READING,
     "        return copy.deepcopy(_intake_memo[1])",
     "        return copy.copy(_intake_memo[1])"),

    ("the budget memo hands out the dict it stored", READING,
     "        return copy.deepcopy(_budget_memo[1])",
     "        return _budget_memo[1]"),

    ("the budget memo stores the object its first reader was handed", READING,
     "        _budget_memo = (stamp, copy.deepcopy(got))",
     "        _budget_memo = (stamp, got)"),

    # ── #166: there is no single flight at all ──────────────────────────────────────────────────
    ("nobody joins a read in flight — six browsers at the window's expiry are six reads", READING,
     "    if flight is None or flight.loop is not loop:",
     "    if True:"),

    # ── …or it is there and wrong ───────────────────────────────────────────────────────────────
    ("a read in flight on ANOTHER loop is joined, and the reader awaits a task it cannot", READING,
     "    if flight is None or flight.loop is not loop:",
     "    if flight is None:"),

    ("one reader going away cancels the read under everybody waiting on it", READING,
     "        return await asyncio.shield(flight.task)",
     "        return await flight.task"),

    ("a read that ended stays in the slot, and every later reader is handed its result", READING,
     "        if self.flight is flight:\n            self.flight = None",
     "        if self.flight is flight:\n            pass"),

    # What a `finally` in the read's own body amounts to: a task cancelled before its first step
    # never enters the coroutine, so nothing gives the slot up for it.
    ("a read cancelled before it began keeps the slot, and every later reader on its loop is "
     "handed its cancellation", READING,
     "            flight.task.add_done_callback(lambda _task, landed=flight: "
     "self._give_up(landed))",
     "            flight.task.add_done_callback(lambda _task, landed=flight: "
     "None if _task.cancelled() else self._give_up(landed))"),

    ("a blip leaves the read from before it in the slot, and it fills the window when it lands",
     READING,
     "    _intake_memo = None\n    _intake_read.forget()",
     "    _intake_memo = None"),

    ("a read that lost the slot fills the window anyway", READING,
     '    if got.get("known") is not False and _intake_read.holds(flight):',
     '    if got.get("known") is not False:'),
]
