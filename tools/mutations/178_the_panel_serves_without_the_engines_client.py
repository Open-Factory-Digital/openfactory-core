"""#178, proven by breaking it — the panel serves without the engine's client library.

Three docstrings said the panel is built to serve without the `runtime` extra (`temporalio`), and
the page did not keep the promise: with the library unimportable, 12 of the panel's 41 GET routes
answered 500 on `main` at `1512d0a` — `/` and every page route, `/api/floor`, `/api/attention` —
and `openfactory worker`, `poller pause` and `poller resume` ended in a raw `ModuleNotFoundError`.

FOUR CLAIMS:

  1. **The page's words cost no engine import.** `ATTENTION_STATES`, `MERGE_WAIT` and
     `merge_wait_note` are defined in `runtime/temporal/vocabulary.py`, which imports nothing of
     the engine; `view.py`, `workflow.py` and the tech-lead only NAME them.
  2. **The floor never raises, and says which thing is missing.** `_engine`'s import is inside its
     `try`; an absent library reaches the ladder as "no durable engine installed" with the install
     on the detail line, and anything else that fails to import is reported as itself.
  3. **One sentence for one condition.** The panel's engine routes, the floor and the commands all
     say `host.CLIENT_MISSING`.
  4. **What IS the engine's refuses in a sentence** — `worker` (the command and the module),
     `poller pause`, `poller resume` — and importing the worker still raises, because an importer
     has an `except` of its own.

The guard is `tests/test_the_panel_serves_without_the_engines_client.py`. Every reading in it runs
in a child interpreter, so blocking the library cannot leak into the suite's own process.
"""

TEST = "tests/test_the_panel_serves_without_the_engines_client.py"
UP = "tests/test_the_engine_starts_only_beside_the_library_its_worker_runs_on.py"

APP = "openfactory/api/app.py"
CLI = "openfactory/cli.py"
HOST = "openfactory/runtime/host.py"
LADDER = "openfactory/floor/ladder.py"
READING = "openfactory/floor/reading.py"
TECHLEAD = "openfactory/techlead/conversation.py"
VIEW = "openfactory/runtime/temporal/view.py"
VOCABULARY = "openfactory/runtime/temporal/vocabulary.py"
WORKER = "openfactory/runtime/temporal/worker.py"
WORKFLOW = "openfactory/runtime/temporal/workflow.py"

MUTATIONS = [
    # ── 1. the page's words ─────────────────────────────────────────────────────────────────────
    ("THE DEFECT ITSELF: the page fetches its words from the modules that import the engine",
     APP,
     "    from openfactory.runtime.temporal.vocabulary import ATTENTION_STATES, merge_wait_note\n",
     "    from openfactory.runtime.temporal.view import ATTENTION_STATES\n"
     "    from openfactory.runtime.temporal.workflow import merge_wait_note\n"),

    ("the attention route reads the engine's list through the engine's module again", APP,
     "    from openfactory.runtime.temporal.vocabulary import ATTENTION_STATES\n\n"
     '    return [j for j in list_jobs() if j.get("state") in ATTENTION_STATES]',
     "    from openfactory.runtime.temporal.view import ATTENTION_STATES\n\n"
     '    return [j for j in list_jobs() if j.get("state") in ATTENTION_STATES]'),

    ("the vocabulary module reaches for the engine's client itself", VOCABULARY,
     "", "\nimport temporalio  # noqa: F401, E402\n"),

    ("the view defines its own list of attention states again", VIEW,
     "from openfactory.runtime.temporal.vocabulary import ATTENTION_STATES, MERGE_WAIT\n",
     "from openfactory.runtime.temporal.vocabulary import MERGE_WAIT\n\n"
     'ATTENTION_STATES = {"failed", "needs_refinement", "on_hold", "blocked", "paused",\n'
     '                    "awaiting_prod_approval", "awaiting_your_merge"}\n'),

    ("the workflow keeps its own copy of the merge-wait sentence again", WORKFLOW,
     "    from openfactory.runtime.temporal.vocabulary import merge_wait_note\n",
     "    def merge_wait_note(auto: bool) -> str:\n"
     '        return "waiting for CI / the merge" if auto else "waiting for your review and merge"\n'),

    ("the tech-lead spells the merge-wait kind by hand again — the copy `is` cannot see", TECHLEAD,
     "_MERGE_WAIT_KIND = _MERGE_WAIT\n",
     '_MERGE_WAIT_KIND = "merge_wait"\n'),

    # ── 2. the floor ────────────────────────────────────────────────────────────────────────────
    ("the floor's import of the engine's reader goes back ABOVE its `try`", READING,
     "    try:\n        from openfactory.runtime.temporal import view as tv\n"
     "    except ImportError as exc:\n",
     "    from openfactory.runtime.temporal import view as tv\n"
     "    try:\n        pass\n"
     "    except ImportError as exc:\n"),

    ("the floor reports an absent library as a bare import error, with nothing to install",
     READING,
     '        return None, False, "", why_the_engine_cannot_be_read(exc)\n',
     '        return None, False, "", str(exc)[:200]\n'),

    ("the one sentence loses its install: an absent library is described as any import error",
     HOST,
     "        return CLIENT_MISSING\n",
     "        return str(exc)[:200]\n"),

    # RE-PINNED 2026-09-19: the question moved into `the_client_is_what_is_missing`, which the
    # action layer asks too (`178b_…`); this cuts the floor's use of it, which is what it meant.
    ("…and the reverse: ANY import that fails is blamed on the install", HOST,
     "    if the_client_is_what_is_missing(exc):\n        return CLIENT_MISSING\n",
     "    if True:\n        return CLIENT_MISSING\n"),

    ("the ladder drops WHY there is no engine, so the headline names no remedy", LADDER,
     '                             "be picked up", kind="stopped", detail=inputs.engine_error))',
     '                             "be picked up", kind="stopped"))'),

    # ── 3. one sentence ─────────────────────────────────────────────────────────────────────────
    ("the panel's engine routes go back to a spelling of their own, with nothing to install",
     APP,
     "        raise RuntimeError(why_the_engine_cannot_be_read(exc)) from exc\n",
     '        raise RuntimeError("the runtime extra is not installed") from exc\n'),

    # ── 4. the commands that ARE the engine's ───────────────────────────────────────────────────
    ("`openfactory worker` starts its import without asking, and ends in a raw traceback", CLI,
     '    _refuse_without_the_client("the worker cannot start", code=1)\n', ""),

    ("`poller pause` stops asking, and blames an engine that may be unreachable", CLI,
     '    _refuse_without_the_client("could not pause the poller", code=2)\n', ""),

    ("`poller resume` stops asking, and blames an engine that may be unreachable", CLI,
     '    _refuse_without_the_client("could not resume the poller", code=2)\n', ""),

    ("the refusal is asked and never said: the library is always reported present", CLI,
     "    if not host.the_client():\n"
     '        typer.echo(f"✗ {what}: {host.CLIENT_MISSING}", err=True)\n',
     "    if False:\n"
     '        typer.echo(f"✗ {what}: {host.CLIENT_MISSING}", err=True)\n'),

    ("run as a module, the worker ends in a raw ModuleNotFoundError again", WORKER,
     '    if __name__ != "__main__" or (_exc.name or "").split(".")[0] != "temporalio":\n'
     "        raise\n",
     "    raise\n"),

    ("…and the reverse: IMPORTING the worker exits the importer's process", WORKER,
     '    if __name__ != "__main__" or (_exc.name or "").split(".")[0] != "temporalio":\n'
     "        raise\n",
     ""),

    # ── what `up` now promises, held by #171's guard ────────────────────────────────────────────
    ("`up` stops saying the panel works on the install where it now does", CLI,
     '        typer.echo("the durable half is off: `run` and `poll` work, the panel works, and the "\n',
     '        typer.echo("the durable half is off: `run` and `poll` work, and the "\n', UP),
]
