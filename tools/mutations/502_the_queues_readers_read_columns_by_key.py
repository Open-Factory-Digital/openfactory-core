"""On a renamed board, the queue's readers count the cards where the board keeps them, the role's
sentences name the board's own columns, and an approved card lands where the poller reads (#502).

Run:  .venv/bin/python tools/mutate.py tools/mutations/502_the_queues_readers_read_columns_by_key.py

THE CLAIMS, each with a red twin below:

  1. **`readiness` reads by key, through the board's own map.** Rows 1-3 put the platform's names
     back, one bucket at a time — the defect as it shipped: on Jira the role filed into
     `Pendências` and queued into `A Fazer`, and its own next read counted neither. Rows 4-5 break
     the seam (`stage_of` ignoring the board's answer, or reading a column the board did not name
     by the platform's word); rows 6-10 drop the board at each caller and at the ask itself; rows
     11-12 let a board that cannot be built take the read with it.
  2. **Triage and what is parked read by key.** Rows 13-18: in flight, waiting on a person, done
     but open and closed elsewhere compared by name again; the triage handed no map; the parked
     cards found by the platform's `Needs Action`.
  3. **The sentences name the board's own columns.** Rows 19-34: each catalogue entry spelled with
     the platform's word, each caller that stops handing the board's name in, the door's `Seen`
     losing the column, `column_said` ignoring what it is handed, and — HOSTILE — the queue's name
     said where the backlog's belongs.
  4. **`promote` writes where the poller reads.** Rows 35-42: `pickup_status` ignored by the fold,
     the map's `todo` winning over it, the disagreement unsaid, and each shipped row — Jira's
     `status_map`, GitHub's `columns`, the local board's rows and its own pickup answer — left
     out of it.
  5. **The guard.** Row 43 writes a platform literal into neutral code; row 44 retires the one
     allowance while it is still listed.
"""

TEST = "tests/test_the_queues_readers_read_columns_by_key.py"

QUEUE = "openfactory/product/queue.py"
TRIAGE = "openfactory/product/triage.py"
MOD = "openfactory/product/module.py"
BOARD = "openfactory/product/board.py"
ACTIVITIES = "openfactory/runtime/temporal/activities.py"
VOICE = "openfactory/product/voice.py"
CONFIRM = "openfactory/product/confirm.py"
ENGINE = "openfactory/product/engine.py"
NEEDS = "openfactory/product/needs_action.py"
CARD = "openfactory/lifecycle/card.py"
PORTS = "openfactory/lifecycle/ports.py"
FACTORY = "openfactory/adapters/board/factory.py"
LOCAL = "openfactory/adapters/board/local.py"
TRACKERS = "openfactory/adapters/tracker/registry.py"

MUTATIONS = [
    # ── 1. readiness, by key ────────────────────────────────────────────────────────────────────
    ("TODAY'S DEFECT: the queue is counted by the platform's `TO-DO` again", QUEUE,
     "        elif stage == todo_key:\n",
     '        elif t.column == "TO-DO":\n'),

    ("the backlog is counted by the platform's `Backlog` again — filed work vanishes", QUEUE,
     "        elif stage == backlog_key:\n",
     '        elif t.column == "Backlog":\n'),

    ("the floor is counted by the platform's `In progress` again — a busy floor reads idle", QUEUE,
     "        if stage in active_keys:\n",
     '        if t.column in ("In progress",):\n'),

    ("`stage_of` ignores the board's answer and reads every column by the platform's names",
     TRIAGE,
     "    if stages is None:\n        return key_for(column)\n"
     "    return stages.get(column, \"\")\n",
     "    return key_for(column)\n"),

    ("HOSTILE: a column the board did not name is read by the platform's word after all", TRIAGE,
     '    return stages.get(column, "")\n',
     "    return stages.get(column) or key_for(column)\n"),

    ("`propose_queue` reads the board with no map", MOD,
     "        state = readiness(tickets, stages=self._stages(tickets))\n"
     "        self._board_tickets = tickets",
     "        state = readiness(tickets)\n"
     "        self._board_tickets = tickets"),

    ("arriving, the role reads the board with no map and announces a busy floor as quiet", MOD,
     "            if not error:\n"
     "                state = readiness(tickets, stages=self._stages(tickets))\n",
     "            if not error:\n"
     "                state = readiness(tickets)\n"),

    ("the tech-lead's queued cards are read with no map", ACTIVITIES,
     "    return [str(n) for n in readiness(tickets, stages=stages_for(project, tickets,\n"
     "                                                                 token=token)).todo]\n",
     "    return [str(n) for n in readiness(tickets).todo]\n"),

    ("the role asks no board what its columns are", MOD,
     "        return stages_of(tickets, self._board_to_ask())\n",
     "        return stages_of(tickets, None)\n"),

    ("the map is asked of nobody, whatever board is handed in", BOARD,
     "    return {column: stage_key(board, column)\n",
     "    return {column: stage_key(None, column)\n"),

    ("a board the role cannot build takes the queue proposal with it", MOD,
     "        except Exception as exc:  # noqa: BLE001 — asking what a column is called is not a "
     "write\n",
     "        except ZeroDivisionError as exc:\n"),

    ("a board nobody can build takes the tech-lead's read with it", BOARD,
     "    except Exception as exc:  # noqa: BLE001 — a reader degrades; it does not raise\n",
     "    except ZeroDivisionError as exc:\n"),

    # ── 2. triage and the parked cards, by key ──────────────────────────────────────────────────
    ("triage reads work in flight by the platform's `In progress` again", TRIAGE,
     '        if stage in active_keys and t.state == "open":\n',
     '        if t.column in ("In progress",) and t.state == "open":\n'),

    ("triage reads a card waiting on a person by the platform's `Needs Action` again", TRIAGE,
     '        if stage == waiting_key and t.state == "open":\n',
     '        if t.column == "Needs Action" and t.state == "open":\n'),

    ("triage reads done-but-open by the platform's `Done` again", TRIAGE,
     '        if stage == done_key and t.state == "open" and not t.has_open_pr:\n',
     '        if t.column == "Done" and t.state == "open" and not t.has_open_pr:\n'),

    ("a closed card in the board's own done column is reported as closed elsewhere", TRIAGE,
     '        if t.state == "closed" and t.column and stage != done_key:\n',
     '        if t.state == "closed" and t.column not in ("Done", ""):\n'),

    ("the triage is handed no map", MOD,
     '        return triage(tickets, stages=self._stages(tickets)), ""\n',
     '        return triage(tickets), ""\n'),

    ("the parked cards are found by the platform's `Needs Action` again", BOARD,
     '    waiting = [t for t in tickets if stages.get(t.column) == key and t.state == "open"]\n',
     '    waiting = [t for t in tickets if t.column == "Needs Action" and t.state == "open"]\n'),

    # ── 3. the sentences name the board's own columns ───────────────────────────────────────────
    ("a filed card is said to stay in the platform's `Backlog`", VOICE,
     '    "pt-BR": "Aberto: {where}. Fica no {backlog} até o time',
     '    "pt-BR": "Aberto: {where}. Fica no Backlog até o time'),

    ("the ticket reply is handed no name for the backlog", CONFIRM,
     '                     just_asked=bool(getattr(result, "just_asked", False)),\n'
     '                     backlog=_board_word(module, "backlog")),',
     '                     just_asked=bool(getattr(result, "just_asked", False))),'),

    ("a breakdown is said to be in the platform's `Backlog` (pt-BR)", CONFIRM,
     '"in_backlog": ("\\n\\n{where} no {backlog} — ',
     '"in_backlog": ("\\n\\n{where} no Backlog — '),

    ("a breakdown is said to be in the platform's `Backlog` (en)", CONFIRM,
     '"in_backlog": ("\\n\\n{where} in the {backlog} — ',
     '"in_backlog": ("\\n\\n{where} in the Backlog — '),

    ("the breakdown reply forgets the name it was handed", CONFIRM,
     '                                         backlog=column_said(backlog, "backlog"))',
     '                                         backlog=column_said("", "backlog"))'),

    ("the acceptance's breakdown is handed no name for the backlog", CONFIRM,
     '        return head + "\\n\\n" + _breakdown_reply(results, number, "", lang, '
     'project=project,\n'
     '                                                  backlog=_board_word(module, "backlog"))',
     '        return head + "\\n\\n" + _breakdown_reply(results, number, "", lang, '
     'project=project)'),

    ("a breakdown a person asks for is handed no name for the backlog", ENGINE,
     "        return _breakdown_reply(results, number, name, lang, project,\n"
     '                                backlog=_board_word(module, "backlog"))',
     "        return _breakdown_reply(results, number, name, lang, project)"),

    ("the cards opened for a requirement are said to be in the platform's `Backlog`", CONFIRM,
     '        said += "\\n\\n" + cards_opened_awaiting(cards=cards, number=number, language=lang,\n'
     '                                                backlog=_board_word(module, "backlog"))',
     '        said += "\\n\\n" + cards_opened_awaiting(cards=cards, number=number, '
     'language=lang)'),

    ("the hand-back comment names the platform's backlog and queue", NEEDS,
     '        backlog=voice.column_said(named.get("backlog", ""), "backlog"),\n'
     '        queue=voice.column_said(named.get("todo", ""), "todo"))',
     '        backlog=voice.column_said("", "backlog"),\n'
     '        queue=voice.column_said("", "todo"))'),

    ("the review drops the board's names on the way to the comment it writes", NEEDS,
     "                            comment=fix_comment(v, agent_name=agent_name, "
     "language=language,\n"
     "                                                columns=columns)))",
     "                            comment=fix_comment(v, agent_name=agent_name, "
     "language=language)))"),

    ("the role's review of what is parked hands no names in", MOD,
     '                      language=getattr(self.project, "language", None), columns=words), ""',
     '                      language=getattr(self.project, "language", None)), ""'),

    ("the door's refusal is handed no column", CARD,
     "                language=language, column=seen.column))",
     "                language=language))"),

    ("the door's look at the card forgets the column it found it in", PORTS,
     "        return Seen(state=state, title=title, opened_by=opened_by, column=column)",
     "        return Seen(state=state, title=title, opened_by=opened_by)"),

    ("a refusal says the platform's `TO-DO` whatever it is handed", VOICE,
     '        where = where.format(queue=column_said(column, "todo"))',
     '        where = where.format(queue=column_said("", "todo"))'),

    ("`column_said` ignores the board's name it is handed", VOICE,
     '    return str(named or "").strip() or name_for(key)\n',
     "    return name_for(key)\n"),

    ("HOSTILE: the role says the queue's name where the backlog's belongs", MOD,
     "        return {self.FILING_KEY: stage_column(board, self.FILING_KEY),\n",
     "        return {self.FILING_KEY: stage_column(board, self.QUEUE_KEY),\n"),

    # ── 4. `promote` writes where the poller reads ──────────────────────────────────────────────
    ("TODAY'S DEFECT: `pickup_status` is the poller's alone — the role queues elsewhere", FACTORY,
     "    queue = declared_queue(options)\n    if not queue:\n",
     '    queue = ""\n    if not queue:\n'),

    ("the map's `todo` wins over `pickup_status`, so the poller and the role read apart", FACTORY,
     '    return {**(named or {}), "todo": queue}\n',
     '    return {"todo": queue, **(named or {})}\n'),

    ("a queue named two ways is followed in silence", FACTORY,
     "    if mapped and mapped != queue:\n",
     "    if False:\n"),

    ("the Jira row's `status_map` is never told the named queue", TRACKERS,
     '    status_map = with_the_queue(project, options, status_map, option="status_map") or {}\n',
     "    status_map = status_map or {}\n"),

    ("the rows that take `columns` are never told the named queue", FACTORY,
     "    return with_the_queue(project, options, _json_map(\n",
     "    return with_the_queue(project, {}, _json_map(\n"),

    ("the local row is never told the named queue", FACTORY,
     "                      queue=declared_queue(options))\n",
     '                      queue="")\n'),

    ("the local board names its stages without the named queue", LOCAL,
     '        if self._queue:\n            named["todo"] = self._queue\n',
     ""),

    ("the local board's pickup answer ignores the named queue", LOCAL,
     "        if self._queue:\n"
     "            # THE QUEUE THE DEPLOYMENT NAMED (#502) — what the poller pulls from either way\n"
     "            return self._queue\n",
     ""),

    # ── 5. the guard ────────────────────────────────────────────────────────────────────────────
    ("a platform column literal is written into neutral code", QUEUE, "",
     '\n\n_THE_QUEUE = "TO-DO"\n'),

    ("an allowance outlives the literal it allowed", "openfactory/runtime/temporal/io.py",
     '    pickup_status: str = "TO-DO"\n',
     '    pickup_status: str = ""\n'),
]
