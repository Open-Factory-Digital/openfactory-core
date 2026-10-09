"""#231: the board row says which neutral stage its own column is, so a Jira card can be touched.

The gate resolved the key itself out of one option name (`columns`) that `ProviderRef.options`
(`dict[str, str]`) can only hold as a string — mapping nothing, or raising `TypeError` at an
operator. Each cut here puts one piece of that back.
"""

TEST = "tests/test_the_board_row_says_which_stage_its_column_is.py"
BASE = "openfactory/adapters/board/base.py"
CATALOG = "openfactory/actions/catalog.py"
JIRA = "openfactory/adapters/board/jira.py"
LOCAL = "openfactory/adapters/board/local.py"
GH_BOARD = "openfactory/adapters/tracker/github_project.py"
FACTORY = "openfactory/adapters/board/factory.py"
TRACKERS = "openfactory/adapters/tracker/registry.py"
ACTIVITIES = "openfactory/runtime/temporal/activities.py"

MUTATIONS = [
    # ── 1. THE DEFECT ITSELF: who is asked ─────────────────────────────────────────────────────
    ("THE DEFECT ITSELF: the gate goes back to reading one option name out of generic code, so "
     "every Jira card sits in a column nothing maps", CATALOG,
     "    key = stage_key(board, column)\n",
     "    from openfactory.adapters.board.columns import key_for\n"
     "    key = key_for(column, "
     "renamed=(getattr(proj.tracker, \"options\", None) or {}).get(\"columns\"))\n"),

    ("the product role's correction gate goes back to the same option, so a Jira card cannot be "
     "corrected either", "openfactory/product/module.py",
     "            key = stage_key(self._board(), column)",
     "            from openfactory.adapters.board.columns import key_for\n"
     "            key = key_for(column, renamed=(getattr(getattr(self.project, \"tracker\", None),"
     " \"options\", None) or {}).get(\"columns\"))"),

    ("the seam stops asking the row at all and reads every board by the platform's own six names",
     BASE,
     "    if board is not None and callable(getattr(board, \"stage_key\", None)):",
     "    if False:"),

    # ── 2. what the row answers with ───────────────────────────────────────────────────────────
    ("the Jira row answers from nothing, so the deployment's own statuses map nowhere", JIRA,
     "        return key_for(column, renamed=getattr(self._tracker, \"status_map\", None) or {})",
     "        return key_for(column)"),

    # re-pinned 2026-10-04: the row's map is built once, in `_renamed`, which also folds in the
    # queue a deployment named with `pickup_status` (#502) — the claims are unchanged
    ("the local row stops reading its own rows, so a column renamed on the board is unmappable",
     LOCAL,
     "        return key_for(column, renamed=self._renamed(rows))",
     "        return key_for(column)"),

    ("the local row answers with a key that is not a stage, so a card in a deployment's own "
     "column reads as one the factory has taken up", LOCAL,
     "        named = {r[\"key\"]: r[\"name\"] for r in rows if r[\"name\"] and r[\"key\"] in "
     "CANONICAL_COLUMNS}",
     "        named = {r[\"key\"]: r[\"name\"] for r in rows if r[\"name\"]}"),

    ("the GitHub board answers from the defaults only, so a client's renamed column stops mapping",
     GH_BOARD,
     "        return key_for(column, renamed=self._columns)",
     "        return key_for(column)"),

    # ── 3. what is believed ────────────────────────────────────────────────────────────────────
    ("a row's answer is believed whatever shape it has, so a test double's mock becomes a stage "
     "key", BASE,
     "            key = said.strip() if isinstance(said, str) else None\n"
     "            if key == \"\" or (key and key in CANONICAL_COLUMNS):\n"
     "                return key",
     "            key = said\n"
     "            if key is not None:\n"
     "                return key"),

    ("a board with no row is read as a board that maps nothing, so the product role refuses every "
     "correction on a tickets-only project", BASE,
     "    if board is not None and callable(getattr(board, \"stage_key\", None)):",
     "    if board is None:\n        return \"\"\n"
     "    if board is not None and callable(getattr(board, \"stage_key\", None)):"),

    # ── 4. the refusal that stays ──────────────────────────────────────────────────────────────
    # re-pinned 2026-10-06: since #521 the door says the same refusal, so the test through
    # `card_edit` passes with this gate gone; the gate is asked directly (review of #539)
    ("a column nobody maps is judged anyway, as if it were the operator's", CATALOG,
     "    key = stage_key(board, column)\n    if not key:",
     "    key = stage_key(board, column)\n    if False:",
     "tests/test_an_azure_stock_board_queues_its_cards.py"),

    ("the refusal goes back to naming one option, which on a Jira board is a remedy that changes "
     "nothing", CATALOG,
     # RE-PINNED 2026-10-02 (#414): `card_move`'s own gate names the option the same way, so
     # the anchor carries the sentence that is `_stage`'s alone
     # re-pinned 2026-10-05: `_stage` says the door's own sentence, `voice.card_unmapped`, and
     # hands it the option THIS board reads — the claim is unchanged (#521)
     "            ref=issue, column=column, option=stage_option(board),\n",
     "            ref=issue, column=column, option=\"columns\",\n"),

    ("a row that declares no option has one invented for it", BASE,
     "    return named.strip() if isinstance(named, str) else \"\"",
     "    return named.strip() if isinstance(named, str) else \"columns\""),

    ("the Jira row declares the wrong option, so the refusal sends a person to edit `columns`",
     JIRA, "    stage_option = \"status_map\"", "    stage_option = \"columns\""),

    # ── 5. the option a person typed ───────────────────────────────────────────────────────────
    ("the GitHub board row takes the raw option again, so a declared map is an AttributeError out "
     "of `build_board`", FACTORY,
     "                              columns=declared_columns(project, options),",
     "                              columns=options.get(\"columns\") or None,"),

    ("the GitHub TRACKER row takes the raw option again, so the same map breaks `build_tracker`",
     TRACKERS,
     "        board_columns=declared_columns(project, options),",
     "        board_columns=options.get(\"columns\") or None,"),

    ("`project init` ignores the option the local row's refusal names, so the remedy it offers "
     "changes nothing", "openfactory/adapters/board_setup/local.py",
     "                    (name, key, named.get(key) or CANONICAL_COLUMNS[key], position))",
     "                    (name, key, CANONICAL_COLUMNS[key], position))"),

    ("a `columns` that will not parse is applied half-way instead of being refused by name",
     FACTORY,
     "    except (ValueError, AttributeError) as exc:\n"
     "        log.error(\"the board `%s` map for %s is not a JSON object (%s) — %s\",\n"
     "                  option, getattr(project, \"name\", \"?\"), exc, consequence)\n"
     "        return None",
     "    except (ValueError, AttributeError):\n        return None"),

    ("the poll tick reads the option again on its way to the fallback, and one project's map "
     "takes down the whole work list", ACTIVITIES,
     "    return got or CANONICAL_COLUMNS[\"todo\"]",
     "    return (got or (project.tracker.options.get(\"columns\") or {}).get(\"todo\")\n"
     "            or CANONICAL_COLUMNS[\"todo\"])"),
]
