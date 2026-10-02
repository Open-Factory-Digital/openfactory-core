"""A project is forgotten in one command (#453), proven by breaking it.

SIX CLAIMS, each cut here and each required to go red:

  1. **Every layer goes, each through its own store.** The conversations with what was derived
     from them and what they carried (files, names), the loop ledger, the three record kinds, the
     intake cases and the record of what was told, the closed cards — and the context
     repository's distillates with `--with-context`, where a person's file under the same folder
     and a requirement written by hand stay, and the role's requirements are named, not deleted.
  2. **Nothing that is not the project's.** Another product's rows, board, memory and files, and
     the deployment's people — the record kinds are a closed list that never holds `person`.
  3. **Refused by name, never reported done.** A store that cannot delete, a board with no removal
     of its own: refused, and the command exits 1. A store that fails is FAILED, never forgotten,
     and one layer's refusal does not cost the independent layers.
  4. **Refused while something runs** — a job of the project or a turn of its product, and an
     engine that cannot say; an engine declared and silent is never "nothing runs".
  5. **Asked first, backed up first.** The confirmation stands between the plan and the deletion;
     the backup is taken through SQLite's own backup, and a store with none refuses before
     anything is deleted.
  6. **A process that was not restarted cannot write forgotten cases back.**

The guard under test: `tests/test_a_project_is_forgotten_in_one_command.py`.
"""

TEST = "tests/test_a_project_is_forgotten_in_one_command.py"

FORGET = "openfactory/product/forget.py"
CLI = "openfactory/cli.py"
CASE = "openfactory/product/case.py"
EVENTS = "openfactory/product/events.py"
FILES = "openfactory/product/attachments.py"
NAMES = "openfactory/product/sessions.py"
METRICS = "openfactory/observability/sqlite_metrics.py"
BOARD = "openfactory/adapters/board_db.py"
AUTHORING = "openfactory/product/authoring.py"

MUTATIONS = [
    # ── 1. every layer goes ───────────────────────────────────────────────────────────────────
    ("the conversations layer keeps the files sent in them", FORGET,
     '        counts["files sent in them"] = forget_product(where.key)',
     '        counts["files sent in them"] = 0'),

    ("a forgotten product's files keep their bytes", FILES,
     "        blob.unlink(missing_ok=True)\n",
     "        pass\n"),

    ("the conversations layer keeps the names people gave them", NAMES,
     "            one.unlink(missing_ok=True)",
     "            pass"),

    ("the loop ledger is not forgotten", FORGET,
     '    return Went(LOOPS, FORGOTTEN, {"ledger rows": _sink().forget(t.name, kind=LEDGER_KIND)})',
     '    return Went(LOOPS, FORGOTTEN, {"ledger rows": 0})'),

    ("the preview records leave the list of what is forgotten", FORGET,
     'RECORD_KINDS = {"card_verdict": "card verdicts", "preview": "preview records",',
     'RECORD_KINDS = {"card_verdict": "card verdicts",'),

    ("the intake cases are not forgotten", FORGET,
     '    return Went(INTAKE, FORGOTTEN, {"intake cases": case.forget_project(t.project),',
     '    return Went(INTAKE, FORGOTTEN, {"intake cases": 0,'),

    ("the record of what was told survives its forgetting", EVENTS,
     "        data = _read(path)\n        path.unlink()",
     "        data = _read(path)"),

    ("the open cards are removed with the closed ones", FORGET,
     '    closed = tracker.list_tickets(state="closed")',
     '    closed = tracker.list_tickets(state="all")'),

    ("a person's file under conversations/ is taken for a distillate", AUTHORING,
     '        distillates = tuple(p for p in listed.split("\\0") if p and distillate_of(p) is not None)',
     '        distillates = tuple(p for p in listed.split("\\0") if p)'),

    ("a requirement written by hand is reported as the role's", AUTHORING,
     "        if not sha or not number or _ROLE_REQUIREMENT_LINE not in body:",
     "        if not sha or not number:"),

    ("the older command stops going through the conversations layer", CLI,
     "        counts = forget.conversations(where, members)",
     "        counts = {\"conversation rows\": transcript.forget(where), \"index lines\": 0,\n"
     "                  \"files sent in them\": 0, \"people who named them\": 0}"),

    # ── 2. nothing that is not the project's ──────────────────────────────────────────────────
    ("the deployment's people join the record kinds", FORGET,
     # re-pinned 2026-10-03: the door's record (`card_transition`) joined the list (#412)
     '                "card_transition": "card transitions"}',
     '                "card_transition": "card transitions", "person": "people"}'),

    # ── 3. refused by name, never reported done ───────────────────────────────────────────────
    ("a store that cannot delete is handed to the layers anyway", FORGET,
     "    if not isinstance(sink, ForgettingSink):",
     "    if False:"),

    ("the transcript's refusal for a store that cannot delete becomes a failure", FORGET,
     "    except (ValueError, NotImplementedError) as exc:",
     "    except ValueError as exc:"),

    ("a board with no removal of its own is not refused", FORGET,
     "    if not removes(tracker):",
     "    if False:"),

    ("a layer whose store failed is reported forgotten", FORGET,
     "            out.append(Went(layer, FAILED,",
     "            out.append(Went(layer, FORGOTTEN,"),

    ("one layer's refusal stops the independent layers", FORGET,
     "            out.append(Went(layer, REFUSED, said=str(exc)))",
     "            out.append(Went(layer, REFUSED, said=str(exc)))\n            break"),

    ("a refused layer exits 0", CLI,
     "    if any(w.state in (forget.REFUSED, forget.FAILED) for w in went):",
     "    if any(w.state == forget.FAILED for w in went):"),

    # ── 4. refused while something runs ───────────────────────────────────────────────────────
    ("the command deletes under a running job", CLI,
     "    if flight.refusal():\n        typer.echo(f\"✗ {flight.refusal()}\")",
     "    if False:\n        typer.echo(f\"✗ {flight.refusal()}\")"),

    ("another project's job refuses this one", FORGET,
     "            if project in names:",
     "            if project:"),

    ("another product's conversation refuses this one", FORGET,
     "            if not str(wf.id).startswith(prefix):",
     "            if False:"),

    ("an engine that cannot list what runs reads as nothing running", FORGET,
     '        return Flight(unread=f"the engine could not say what runs ({first_message(exc)})")',
     "        return Flight()"),

    ("a declared engine that does not answer reads as no engine", FORGET,
     '            return Flight(unread=f"the durable engine did not answer ({first_message(exc)})")',
     "            return Flight(engine=False)"),

    # ── 5. asked first, backed up first ───────────────────────────────────────────────────────
    ("the command deletes without asking", CLI,
     "        typer.echo(f\"This permanently deletes what the product role remembers about "
     "'{name}'.\")\n        typer.confirm(\"Proceed?\", abort=True)",
     "        typer.echo(f\"This permanently deletes what the product role remembers about "
     "'{name}'.\")"),

    ("the metrics store is not in the backup", FORGET,
     '            take(folder / "metrics.db")',
     "            folder.mkdir(parents=True, exist_ok=True)"),

    ("the metrics store's backup copies no pages", METRICS,
     "                conn.backup(copy)",
     "                pass"),

    ("the board's backup copies no pages", BOARD,
     "            conn.backup(copy)",
     "            pass"),

    ("a store with no backup is forgotten without one", FORGET,
     "        elif not isinstance(sink, NullMetricsSink):",
     "        elif False:"),

    # ── 6. a stale process cannot write forgotten cases back ──────────────────────────────────
    ("a save writes back the cases opened before the forgetting", CASE,
     "            for cid in [c for c, case in cases.items() if case.opened_ts < forgotten]:",
     "            for cid in [c for c, case in cases.items() if case.opened_ts < 0]:"),

    ("the forgetting leaves no stamp for the processes it cannot reach", CASE,
     '            emptied = json.dumps({"cases": [], FORGOTTEN: now})',
     '            emptied = json.dumps({"cases": []})'),
]
