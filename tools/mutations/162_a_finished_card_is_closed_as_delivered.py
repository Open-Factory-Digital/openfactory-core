"""#162: a card in Done closes, as delivered, and "a job may be running" is only said where one is.

The last nine rows are the review of #191: the carve-out for Done was incidental, because the same
sentence is untrue of `needs_action` — a card sits there with no job on it whenever the gather
parks it and returns `SKIPPED`, or an impediment deadline elapses and the park is returned
untouched — and its remedy is untrue of `in_review`, where the merge watch is alive and `stop`
refuses a job at a gate. They cut the second half of the gate: the engine's own answer.
"""

TEST = "tests/test_a_finished_card_is_closed_as_delivered.py"
CATALOG = "openfactory/actions/catalog.py"
COLUMNS = "openfactory/adapters/board/columns.py"

MUTATIONS = [
    ("THE DEFECT ITSELF: Done reads as a column where a job may be running, so a finished card is "
     "told to stop a job that ended", COLUMNS,
     "    return has_started(key) and not has_finished(key)",
     "    return has_started(key)"),

    ("no column means finished, so nothing is ever closed as delivered", COLUMNS,
     "    return bool(key) and key in AFTER_THE_FACTORY",
     "    return False"),

    ("an unmapped column reads as finished, and a card nobody can place is recorded as delivered",
     COLUMNS,
     "    return bool(key) and key in AFTER_THE_FACTORY",
     "    return key in AFTER_THE_FACTORY or not key"),

    ("shipped work is recorded as withdrawn: the close lets Done through and keeps the old word",
     CATALOG,
     "    delivered = has_finished(stage.key)\n",
     "    delivered = False\n"),

    ("a withdrawn card is recorded as delivered work — eleven cards once looked like that "
     "downstream", CATALOG,
     "    delivered = has_finished(stage.key)\n",
     "    delivered = True\n"),

    ("the close gate goes back to `has_started`, so Done is refused again", CATALOG,
     "        if may_be_running(key):\n",
     "        if has_started(key):\n"),

    ("the close gate is gone, and a card is closed from under its running job", CATALOG,
     "        if may_be_running(key):\n",
     "        if False:\n"),

    ("loosening the close loosens the edit: a finished card's text is rewritten after the fact",
     CATALOG,
     "    if has_finished(key):\n        return (f\"{issue} is in {column!r} — the factory "
     "delivered it",
     "    if has_finished(key):\n        return \"\"\n        return (f\"{issue} is in {column!r} "
     "— the factory delivered it"),

    ("a finished card is told a comment is what the factory reads next, when no job is coming",
     CATALOG,
     "    if has_finished(key):\n        return (f\"{issue} is in {column!r} — the factory "
     "delivered it",
     "    if False:\n        return (f\"{issue} is in {column!r} — the factory delivered it"),

    ("the answer does not say which of the two closes happened", CATALOG,
     "                project=proj.name, issue=str(issue), delivered=delivered)",
     "                project=proj.name, issue=str(issue))"),

    ("the refusal reads the board a second time instead of the stage it was handed", CATALOG,
     "    at = stage if stage is not None else _stage(proj, board, issue)",
     "    at = _stage(proj, board, issue)"),

    # ── the column says a job MAY be on it; the engine says whether one IS (review of #191) ────
    ("`needs_action` is folded in as finished, so a card that can be parked for ever — and never "
     "shipped — is recorded as delivered work", COLUMNS,
     'AFTER_THE_FACTORY: tuple[str, ...] = ("done",)',
     'AFTER_THE_FACTORY: tuple[str, ...] = ("done", "needs_action")'),

    ("THE DEFECT ONE COLUMN OVER: the engine is never asked, so a card whose job has ended — the "
     "gather's park, an elapsed deadline — can never be closed at all", CATALOG,
     "        elif not job.running:\n",
     "        elif False:\n"),

    ("a card is closed from under a job that IS running", CATALOG,
     "        elif not job.running:\n",
     "        elif True:\n"),

    ("an engine that could not be asked reads as an engine holding no job", CATALOG,
     "        if job.cannot_tell:\n            refusal = job.cannot_tell",
     "        if False:\n            refusal = job.cannot_tell"),

    ("a job waiting on a person is told to `stop`, which `stop` itself refuses", CATALOG,
     "        elif job.answer_it:\n",
     "        elif False:\n"),

    ("a board that could not be read is answered by the engine instead, so a card nobody can "
     "place is closed", CATALOG,
     "    if refusal and not stage.cannot_tell:",
     "    if refusal:"),

    ("the engine is asked on every close, including the ones the board settles on its own",
     CATALOG,
     "    if refusal and not stage.cannot_tell:",
     "    if True:"),

    ("the engine's answer is taken without reading the status, so a finished job still holds the "
     "card", CATALOG,
     '    if str(tv.status_label(described.status)) != "running":\n'
     "        return _JobOnTheCard()",
     "    if False:\n        return _JobOnTheCard()"),

    ("a job the engine never had reads as one it could not be asked about", CATALOG,
     "        if _looks_missing(exc):\n            return _JobOnTheCard()",
     "        if False:\n            return _JobOnTheCard()"),
]
