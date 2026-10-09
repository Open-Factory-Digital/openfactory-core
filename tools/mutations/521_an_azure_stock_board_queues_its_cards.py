"""An Azure board with a stock process queues its cards once `New` is mapped, and until then every
sentence that refuses one names the line that maps it (#521).

Run:  .venv/bin/python tools/mutate.py \\
        tools/mutations/521_an_azure_stock_board_queues_its_cards.py

The claims, one row or more each:

  1. A COLUMN NO STAGE IS HAS NO STATE. The door refuses a card in one for every event; reading
     it as the backlog would queue the stock `New` card, and edit, withdraw or remove a card in
     any column nobody maps (row 1). The table is not where the fix is.
  2. THE REFUSAL NAMES THE REPAIR: the option THIS board reads and the line that makes the column
     the backlog (rows 2-3), in the project's language (row 4) — and the panel's move says the
     same sentence, not one of its own (row 5).
  3. THE DOCTOR SAYS IT BEFORE THE FIRST CARD: it asks at all (row 6), it asks the row rather
     than the platform's own names (row 7), it says an unreadable board once and not as a board
     with no backlog (rows 8-9), it names a board with no backlog (row 10), it never fails a
     column a client's board legitimately has (row 11), the verdict repeats the whole line, what
     the repair is for included (row 12),
     and a row that declares no option is not handed one (row 13).
  4. THE LINE IS ONE THE REGISTRY TAKES (review of #521): a string of JSON, quoted for YAML,
     because `ProviderRef.options` holds strings and the unquoted line is a mapping the registry
     refuses — wherever it is printed: the one helper (row 14), the refusal (row 15), the doctor's
     stages line (row 16) and its pickup remedy (row 17). And a board with no backlog whose first
     column is the queue is not said as though it were harmless (row 18, #536).
"""

TEST = "tests/test_an_azure_stock_board_queues_its_cards.py"

BASE = "openfactory/adapters/board/base.py"
PORTS = "openfactory/lifecycle/ports.py"
VOICE = "openfactory/product/voice.py"
CATALOG = "openfactory/actions/catalog.py"
DOCTOR = "openfactory/doctor.py"

MUTATIONS = [
    # ── 1. the table stays honest ──────────────────────────────────────────────────────────────
    ("OPTION (a), THE ONE NOT TAKEN: a column no stage is is read as the backlog, so the stock "
     "card is queued — and edited, withdrawn and removed — through the door", PORTS,
     "        state = BY_COLUMN.get(stage_key(board, column))\n",
     "        state = BY_COLUMN.get(stage_key(board, column) or \"backlog\")\n"),

    # ── 2. the refusal names the repair ────────────────────────────────────────────────────────
    ("THE DEFECT'S SENTENCE: the refusal names no option and no line, only 'the tracker options'",
     VOICE,
     "    option = (option or \"\").strip()\n",
     "    option = \"\"\n"),

    ("the door's refusal names the option generic code assumes, not the one this board reads — "
     "`columns` on a Jira board, a remedy that changes nothing", PORTS,
     "                ref=card, column=column, option=stage_option(board),\n",
     "                ref=card, column=column, option=\"columns\",\n"),

    ("the refusal is said in English to every conversation, whatever the project speaks", PORTS,
     "                language=getattr(self.project, \"language\", None)))\n",
     "                language=None))\n"),

    ("the panel's move keeps a sentence of its own, so the same card is refused in two ways",
     CATALOG,
     "        return _Stage(column=column, cannot_tell=card_unmapped(\n",
     "        return _Stage(column=column, cannot_tell=(lambda **_: (\n"
     "            f\"{issue} is in {column!r}, which is not a column this platform maps, so it \"\n"
     "            f\"cannot tell whether the factory has taken the card up.\"))(\n"),

    # ── 3. the doctor says it before the first card ────────────────────────────────────────────
    ("the doctor does not ask which stage each column is, so nothing says it before the first "
     "card is refused", DOCTOR,
     "        *_board_stages(probes),\n",
     ""),

    ("the doctor's probe reads the columns by the platform's own names, not the row's map, so a "
     "column the deployment DID map is reported as no stage", DOCTOR,
     "        return {name: stage_key(board, name) for name in names}, stage_option(board)",
     "        from openfactory.adapters.board.columns import key_for\n"
     "        return {name: key_for(name) for name in names}, stage_option(board)"),

    ("an unreadable board is read as a board with no columns, so the doctor reports it as one "
     "with no backlog", DOCTOR,
     "        if names is None:\n"
     "            raise BoardUnreadable(_board_coordinates(project), "
     "remedy=_board_remedy(project))",
     "        if names is None:\n"
     "            return {}, stage_option(board)"),

    ("an unreadable board is said twice — once here, as a failure of a check that never ran",
     DOCTOR,
     "        return []      # the board `board_columns` could not read either, and that line "
     "says why\n",
     "        return [Finding(\"board_stages\", False, \"could not check board_stages\",\n"
     "                        \"see board_columns\")]\n"),

    ("a board with no backlog is not said, so a filed card is placed nowhere in silence", DOCTOR,
     "    if not backlog:\n        said.append(",
     "    if False:\n        said.append("),

    # re-pinned 2026-10-05: the verdict repeats the whole line now, consequence and repair, so
    # both rows anchor on the one return (review of #521, #536)
    ("a column a client's board legitimately has FAILS the doctor, so a project that runs its "
     "tickets is told it is not ready", DOCTOR,
     "    return [Finding(\"board_stages\", True, line, note=line)]",
     "    return [Finding(\"board_stages\", False, line, line)]"),

    ("the verdict repeats the repair and drops what it is a repair FOR", DOCTOR,
     "    return [Finding(\"board_stages\", True, line, note=line)]",
     "    return [Finding(\"board_stages\", True, line, note=repair)]"),

    ("a row that declares no option is handed one anyway, an empty pair of backticks to edit",
     DOCTOR,
     "    if not option:\n",
     "    if False:\n"),

    # ── 4. the line is one the registry takes ──────────────────────────────────────────────────
    ("THE REVIEW'S FINDING: the line is printed as a mapping, which the registry refuses where "
     "its options are strings", BASE,
     "    return f\"{option}: '{value.replace(chr(39), chr(39) * 2)}'\"",
     "    return f\"{option}: {value}\""),

    ("the refusal spells its own line, unquoted, past the helper", VOICE,
     "        option=option, line=option_line(option, {\"backlog\": column}))",
     "        option=option, line=option + ': {\"backlog\": \"' + column + '\"}')"),

    ("the doctor's stages line spells its own line, unquoted, past the helper", DOCTOR,
     "`{option_line(option, {'backlog': first})}` makes it the",
     "`{option}: {{\\\"backlog\\\": \\\"{first}\\\"}}` makes it the"),

    ("the doctor's pickup remedy prints its line unquoted again", DOCTOR,
     "        f\"`{option_line('columns', {'todo': '<your column>'})}` — or set",
     "        f'`columns: {{\"todo\": \"<your column>\"}}` — or set' f\""),

    ("#536: a board with no backlog whose first column is the queue is said as one that merely "
     "lacks a backlog", DOCTOR,
     "    if key != \"todo\":\n        return \"\"",
     "    if True:\n        return \"\""),
]
