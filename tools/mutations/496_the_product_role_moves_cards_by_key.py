"""On a board whose columns are renamed, the product role queues and files a card by the board's own
name for the column (#496).

Run:  .venv/bin/python tools/mutate.py tools/mutations/496_the_product_role_moves_cards_by_key.py

THE CLAIMS, each with a red twin below:

  1. **The product role moves by key and the board names it.** `promote`, the three filing
     writers (through `_filed_through_the_door`) and `reorder` each ask `stage_column(board,
     <key>)` and move by the answer — filing and queueing through the card's door (#414), which
     places the card by the name it is handed. Rows 1-5 put the platform's own word back, one hop
     at a time — the defect as it shipped: on Jira the site offers `A Fazer`/`Pendências` and
     refuses `TO-DO`/`Backlog`.
  2. **The money gate is the choice of key.** Only `promote` names the queue, through
     `QUEUE_KEY`; filing names the backlog, through `FILING_KEY`. Rows 6-8 open it: a filer
     reaching the queue, the constant itself moved to the queue, and — HOSTILE, behaviourally
     identical — the queue's key spelled at the call site instead of read from the gate. Rows 8b
     and 8c, HOSTILE too, on the door's facts (#414): the filing's door told the card is filed in
     the queue while the name is still the backlog's (the board shows the backlog, the record says
     queued), and a promotion handing the door no name at all.
  3. **What a log says is the board's name.** Row 9 logs the key instead.
  4. **Each row answers from the deployment's own map.** Rows 10-13 make each of the four rows
     answer the platform's word whatever the deployment declared — Jira's `status_map`, GitHub's
     and Azure's `columns`, the local board's own rows.
  5. **The seam.** `name_for` takes the map (row 14); `stage_column` believes a row's real answer
     and only that (rows 15-16), and degrades to the platform's word for a row that says nothing
     or raises (rows 17-18).
  6. **One inverse of `stage_key`** (review of #505/#506). A row whose map is silent is named by
     the first real column of the board that is the stage, before the platform's word (row 19), and
     nothing else public in `board/base.py` maps a key to a column (row 20 grows `column_for` back).
"""

TEST = "tests/test_the_product_role_moves_cards_by_key.py"

MOD = "openfactory/product/module.py"
BASE = "openfactory/adapters/board/base.py"
COLUMNS = "openfactory/adapters/board/columns.py"

MUTATIONS = [
    # ── 1. by key, named by the board ───────────────────────────────────────────────────────────
    ("TODAY'S DEFECT: `promote` asks every board for the platform's `TO-DO` by name", MOD,
     "        queue = stage_column(board, self.QUEUE_KEY)\n",
     '        queue = "TO-DO"\n'),

    # re-pinned 2026-10-04: filing goes through the door (#458) with the board's name (#505)
    ("a card the product role files — asked for, reported, or a requirement's — is placed in the "
     "platform's `Backlog` by name", MOD,
     '        column = stage_column(board, self.FILING_KEY) if board is not None else ""\n',
     '        column = "Backlog" if board is not None else ""\n'),

    # re-pinned 2026-10-04: filing goes through the door (#458) with the board's name (#505)
    # re-pinned 2026-10-05: integration of slices 4/5 with the door stack — the promise the
    # filing carries follows the column's name (#414)
    ("the door is handed the platform's `Backlog` while the log still names the board's own "
     "column", MOD,
     '                                      "column_name": column,\n',
     '                                      "column_name": "Backlog",\n'),

    # re-pinned 2026-10-04: filing goes through the door (#458) with the board's name (#505)
    ("the door's placement drops the name the role asked the board for, and writes the "
     "platform's word for the key", "openfactory/lifecycle/executor.py",
     '        return ports.place(row.card, effect.key, name=str(facts.get("column_name") or ""))',
     "        return ports.place(row.card, effect.key,\n"
     '                           name={"backlog": "Backlog", "todo": "TO-DO"}'
     '.get(effect.key, ""))'),

    ("the backlog order is ranked against the platform's `Backlog` by name", MOD,
     "        backlog = stage_column(board, self.FILING_KEY)\n",
     '        backlog = "Backlog"\n'),

    # ── 2. the money gate ───────────────────────────────────────────────────────────────────────
    # re-pinned 2026-10-04: filing goes through the door (#458) with the board's name (#505)
    ("a card the product role files is placed straight into the queue the poller pulls from", MOD,
     '        column = stage_column(board, self.FILING_KEY) if board is not None else ""\n',
     '        column = stage_column(board, self.QUEUE_KEY) if board is not None else ""\n'),

    ("the filing key itself becomes the queue — every filed card spends money", MOD,
     '    FILING_KEY = "backlog"\n',
     '    FILING_KEY = "todo"\n'),

    ("HOSTILE: `promote` spells the queue's key at the call site — the same column today, and a "
     "gate no longer read from the constant that is the gate", MOD,
     "        queue = stage_column(board, self.QUEUE_KEY)\n",
     '        queue = stage_column(board, "todo")\n'),

    # added 2026-10-04: filing goes through the door (#458) with the board's name (#505)
    ("HOSTILE: the filing's door is told the card is filed in the queue, while the name it places "
     "it by is still the backlog's — the board shows the backlog and the record says queued", MOD,
     '                               facts={"column": self.FILING_KEY '
     'if board is not None else "",',
     '                               facts={"column": self.QUEUE_KEY '
     'if board is not None else "",'),

    # added 2026-10-04: filing goes through the door (#458) with the board's name (#505)
    ("HOSTILE: `promote` hands the door no name, so the queue is placed by whatever the port "
     "falls back to rather than the board's answer for the gate", MOD,
     '                                   facts={"column_name": queue}, tracker=tracker,',
     "                                   facts={}, tracker=tracker,"),

    # ── 3. the log says the board's name ────────────────────────────────────────────────────────
    ("a refused filing is logged under the key, a column no board shows anybody", MOD,
     '                            "places it", ref, column)\n',
     '                            "places it", ref, self.FILING_KEY)\n'),

    # ── 4. each row answers from the deployment's own map ───────────────────────────────────────
    ("the Jira row names a stage by the platform's word, ignoring its `status_map`",
     "openfactory/adapters/board/jira.py",
     '        return name_for(key, renamed=getattr(self._tracker, "status_map", None) or {})\n',
     "        return name_for(key)\n"),

    ("the GitHub row names a stage by the platform's word, ignoring the client's `columns`",
     "openfactory/adapters/tracker/github_project.py",
     "        return name_for(key, renamed=self._columns)\n",
     "        return name_for(key)\n"),

    ("the Azure row names a stage by the platform's word, ignoring its own defaults",
     "openfactory/adapters/board/azure_devops.py",
     "        return name_for(key, renamed=self._names)\n",
     "        return name_for(key)\n"),

    # re-pinned 2026-10-04: the row's map is built once, in `_renamed` (#502) — the claim is
    # unchanged: the local row names a stage off its own rows
    ("the local row names a stage by the platform's word, ignoring its own rows",
     "openfactory/adapters/board/local.py",
     "        return name_for(key, renamed=self._renamed(rows))\n",
     "        return name_for(key)\n"),

    # ── 5. the seam ─────────────────────────────────────────────────────────────────────────────
    ("`name_for` ignores the map it is handed", COLUMNS,
     '    said = str((renamed or {}).get((key or "").strip().lower()) or "").strip()\n',
     '    said = ""\n'),

    ("the seam never believes the row, so every board is asked for the platform's word", BASE,
     # re-pinned 2026-10-04: one inverse of stage_key (review of #505/#506)
     "            if isinstance(said, str) and said.strip():\n"
     "                mapped = said.strip()\n",
     "            if False:\n"
     "                mapped = said.strip()\n"),

    ("the seam believes a mock's answer, and a mock becomes the column a card is moved to", BASE,
     # re-pinned 2026-10-04: one inverse of stage_key (review of #505/#506)
     "            if isinstance(said, str) and said.strip():\n"
     "                mapped = said.strip()\n",
     "            if said:\n"
     "                mapped = said\n"),

    ("a board that says nothing is asked for no column at all", BASE,
     # re-pinned 2026-10-04: one inverse of stage_key (review of #505/#506)
     "    if walked or existing:\n        return walked\n    return name_for(wanted)\n",
     '    if walked or existing:\n        return walked\n    return ""\n'),

    ("a board that raises when asked takes the product role's write with it", BASE,
     "        except Exception as exc:  # noqa: BLE001 — a board that cannot say is not a "
     "traceback\n"
     '            log.warning("OPENFACTORY_BOARD_STAGE_UNANSWERED key=%r: %s raised when asked',
     "        except ZeroDivisionError as exc:\n"
     '            log.warning("OPENFACTORY_BOARD_STAGE_UNANSWERED key=%r: %s raised when asked'),

    # ── 6. one inverse of `stage_key` (review of #505/#506) ────────────────────────────────────
    ("THE MIDDLE LAYER: a row whose map is silent is asked for the platform's `TO-DO`, though one "
     "of its own columns is the queue", BASE,
     '    walked = next((name for name in real if stage_key(board, name) == wanted), "")\n',
     '    walked = ""\n'),

    ("a second inverse of `stage_key` grows back beside the seam", BASE,
     "def _column_names(board, key: str) -> list[str] | None:\n",
     "def column_for(board, key: str) -> str:\n"
     "    return stage_column(board, key, existing=True)\n\n\n"
     "def _column_names(board, key: str) -> list[str] | None:\n"),
]
