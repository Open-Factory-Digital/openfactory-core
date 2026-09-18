"""#162: a card in Done closes, as delivered, and "a job may be running" is only said where one may."""

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
]
