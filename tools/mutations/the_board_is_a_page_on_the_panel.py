"""ADR-0049 slice 2, proven by breaking it — the Board is the panel's, through the ports.

THREE CLAIMS:

  1. **One read, through the two ports.** The board says where a card is, the tracker says what it
     is, and neither is asked twice. Cutting the merge, the 404, or the opt-in card detail must be
     seen.
  2. **The three answers survive the trip to the browser.** `None` could not read, `[]`/`{}` read
     fine and empty. A surface that collapses them is how the factory once reported itself idle
     with a queue of work in front of it — so the collapse is cut here on purpose, twice.
  3. **Watching is the ROW's answer.** `Watchable` exists so the panel never decides, by a
     provider's name, which boards are cheap to re-read. Cutting the protocol check, or making the
     page poll a row that never said it could be polled, must be seen.

WHAT THE FIRST RUN FOUND, and it is one finding with five faces: **nothing in this repository
executes the panel's JavaScript.** Five rows survived — the unreadable-board branch, the
unreadable-thread branch, the poll cadence, the move going through the catalogue, and the served
addresses — because every guard over `panel.html`, this slice's included and the house's existing
ones too, reads it as TEXT.

Four of the five are now visible, by making the text assertions name the exact condition rather
than the feature (`d.columns === null`, `c.comments === null`, `poll_seconds`, `act("card_move"`),
and the fifth by an actual HTTP request through `TestClient`. That is strong enough to see a
branch deleted or a literal written back; it is NOT strong enough to see a branch that runs
wrongly, and saying so is the point. Executing the page — a node harness in CI, which this
repository has never had — is its own card, not a thing to slip into a slice.

The guards under test:
  · `tests/test_the_board_is_a_page_on_the_panel.py` — this slice's own;
  · `tests/test_a_credential_is_scoped.py` — the product surface shows no floor chrome;
  · `tests/test_the_action_layer.py` — the page reaches the board through the catalogue.
"""

TEST = "tests/test_the_board_is_a_page_on_the_panel.py"

SLICE = "tests/test_the_board_is_a_page_on_the_panel.py"
SCOPED = "tests/test_a_credential_is_scoped.py"
LAYER = "tests/test_the_action_layer.py"  # noqa: F841 — named for the note below

APP = "openfactory/api/app.py"
PANEL = "openfactory/api/panel.html"
BASE = "openfactory/adapters/board/base.py"
BOARD = "openfactory/adapters/board/local.py"

MUTATIONS = [
    # ── 1. one read, two ports ─────────────────────────────────────────────────────────────────
    ("an unreadable board reaches the page as an EMPTY one — the collapse the whole read side "
     "exists to prevent, one layer further out than it has ever been caught", APP,
     "    if placed is not None and summaries is not None:",
     "    if True:", SLICE),

    ("a card the board does not place is dropped from the page, hiding work from the person "
     "looking for exactly that", APP,
     '                  "labels": list(s.labels or []), "updated_at": s.updated_at or ""}\n'
     "                 for s in summaries]",
     '                  "labels": list(s.labels or []), "updated_at": s.updated_at or ""}\n'
     "                 for s in summaries if s.ref in placed]", SLICE),

    ("a deployment running on tickets alone gets an empty board to drag on instead of being told "
     "there is none", APP,
     '        return {"project": proj.name, "columns": None, "cards": None, "poll_seconds": None,\n'
     '                "board": False, "card": None}',
     '        return {"project": proj.name, "columns": [], "cards": [], "poll_seconds": None,\n'
     '                "board": True, "card": None}', SLICE),

    ("a project this deployment does not have is a 500 that reads as 'the panel is broken', for "
     "what is only a stale bookmark", APP,
     '        raise HTTPException(status_code=404, detail=f"no project called {project!r}") '
     "from None",
     "        raise", SLICE),

    ("the card detail is read for every card on every board open — one request becomes one per "
     "card, against somebody's hosted API", APP,
     '    if (wanted := (card or "").strip()):\n        detail = _card_detail(tracker, wanted)',
     "    for _s in (summaries or []):\n        detail = _card_detail(tracker, _s.ref)", SLICE),

    # ── 2. the three answers, all the way to the browser ───────────────────────────────────────
    ("an unreadable THREAD reaches the page as an empty one — the reader then concludes nobody "
     "has looked and repeats an answer that already failed", APP,
     '        "comments": None if thread is None else [',
     '        "comments": [] if thread is None else [', SLICE),

    ("a card that cannot be read is a 500 rather than an answer", APP,
     "    except Exception:  # noqa: BLE001 — a card that cannot be read is an answer, not a 500\n"
     '        log.info("the board could not read card %r — the page says so", ref, exc_info=True)\n'
     '        return {"ref": ref, "readable": False, "body": "", "comments": None, "title": ""}',
     "    except Exception:  # noqa: BLE001\n        raise", SLICE),

    ("the page renders an unreadable board as a board with no columns — same shape, opposite "
     "meaning", PANEL,
     "  if(!d || d.board === false || d.columns === null || d.cards === null){",
     "  if(!d || d.board === false){", SLICE),

    ("the page turns an unreadable thread into an empty one, which is the sentence it exists to "
     "avoid saying", PANEL,
     "  if(c.comments === null) return `<div class=\"dark\" style=\"padding:14px\">",
     "  if(false) return `<div class=\"dark\" style=\"padding:14px\">", SLICE),

    # ── 3. watching is the row's answer ────────────────────────────────────────────────────────
    ("the panel decides for itself that every board may be polled — a rate-limit incident against "
     "every hosted deployment, decided by a surface that has never met the row", APP,
     '        "poll_seconds": board.poll_seconds() if isinstance(board, Watchable) else None,',
     '        "poll_seconds": 3,', SLICE),

    ("the local board stops saying it may be watched, so the one board a person can watch is not "
     "watched", BOARD,
     '    def poll_seconds(self) -> int:\n        """Three seconds',
     '    def _poll_seconds_retired(self) -> int:\n        """Three seconds', SLICE),

    ("`Watchable` gains a second method, so the one row that answers it stops satisfying the "
     "protocol and nothing is watched — the failure mode a `runtime_checkable` protocol has",
     BASE,
     '    def poll_seconds(self) -> int:\n        """How often a surface may re-read this board',
     '    def is_cheap(self) -> bool:\n        """Undeclared by every row."""\n        ...\n\n'
     '    def poll_seconds(self) -> int:\n        """How often a surface may re-read this board',
     SLICE),

    ("the page polls on a fixed cadence of its own instead of the one the row named", PANEL,
     "  const every = (_bd.data||{}).poll_seconds;\n  if(!every || every <= 0) return;",
     "  const every = 3;",
     SLICE),

    # ── 4. the surface's own rules ─────────────────────────────────────────────────────────────
    ("the board pill stays on the product surface, where it is a button that can only 403", PANEL,
     '  const board=$("#board"); if(board)board.style.display="none";',
     "  // the board pill stays", SCOPED),

    # re-pinned 2026-09-09: this was aimed at `test_the_action_layer.py` and SURVIVED, correctly.
    # That file's OWNED table catches a front end reaching the PORT directly (`set_column`); a
    # front end inventing a ROUTE of its own is a different offence and is caught by this slice's
    # own `test_every_write_on_the_board_is_an_action_row`. Two guards, two offences, one rule.
    ("the page grows its own copy of a move instead of calling the row the catalogue owns — "
     "which is exactly how `resume` came to mean two things", PANEL,
     '  const r = await act("card_move", {project:_bd.project, issue:ref, column});',
     "  const r = await mfetch(\"/api/board/move\",{method:\"POST\"});", SLICE),

    ("the how-to teaches the three hosted boards and never says this panel can hold one", PANEL,
     "<b>this panel holds one itself</b>, which needs no\n          account anywhere; GitHub "
     "Projects, Azure DevOps Boards and Jira are supported the same\n          way and render on "
     "the same screen.",
     "GitHub Projects, Azure DevOps Boards and Jira are all supported.", SLICE),

    ("the deeper addresses stop being served, so a bookmarked board is the server's own 404", APP,
     '@app.get("/p/{project}/board")\n@app.get("/p/{project}/card/{ref}")\n',
     "", SLICE),
]
