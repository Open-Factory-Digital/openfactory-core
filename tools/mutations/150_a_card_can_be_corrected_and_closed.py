"""#150 slices 1 and 2, proven by breaking them — a card can be corrected, closed and reopened.

WHAT WAS MEASURED, on `main` at `506317a`, driving the real parser, the real spec gate and the
queue's own readiness check over five card bodies: the panel's new-card button makes a card the
gate is certain to refuse, a Gherkin scenario under a correctly-named heading parses as zero
criteria while the queue calls it ready, and a card the product role files is refused too. None of
that could be fixed where it sat: `openfactory actions` had `card_create`, `card_move` and
`card_comment`, and no row changed a card's title or body, closed it or reopened it. On
`tracker: local` the board IS the tracker, so the panel was the only surface and it could not.

SIX CLAIMS:

  1. **A card is corrected only before the factory takes it up.** An agent works from the text it
     read at pickup, so an edit afterwards moves the target with nobody seeing. `todo` and
     `backlog` are the operator's columns; the other four are where `set_state` put the card.
  2. **Every edit leaves a record**, in the platform's voice, naming what changed.
  3. **A close is not a delete and not a delivery.** The card, its thread and its number stay, and
     it is recorded as NOT delivered — `triage.Ticket.delivered` reads that word.
  4. **A row that cannot rename or reopen is refused by name.** Those two writes are off the port
     on purpose: adding them to `TrackerAdapter` made the faithful double answer
     `isinstance=False` and `check_tracker` report the missing method INSTEAD of the read-side
     findings it exists for.

  5. **A card the product role opened is the product owner's** (decided on #150, 2026-09-16). From
     a requirement, a request or a defect, it is not edited, closed or reopened from the board in
     any column, and the drawer offers no button that would be refused. Read from a whole line
     each writer composes, never from a word a person might type.
  6. **The note says which part moved** (the issue's own words: "naming who changed which
     section"). Only what changed is written, by section and by meaning, and a save that changes
     nothing writes nothing — the form sends everything on every save.

The guard is `tests/test_the_board_is_a_page_on_the_panel.py`.

WHAT IS DELIBERATELY NOT CUT: the three hosted rows' `update_title` / `reopen_ticket`. Their bodies
are one vendor call each and no test in this tree reaches a live GitHub, Azure DevOps or Jira — a
row cut there would be a plan row that cannot go red, which is noise.
"""

TEST = "tests/test_the_board_is_a_page_on_the_panel.py"

CATALOG = "openfactory/actions/catalog.py"
COLUMNS = "openfactory/adapters/board/columns.py"
LOCAL = "openfactory/adapters/tracker/local.py"
AUTHORING = "openfactory/product/authoring.py"
APP = "openfactory/api/app.py"
PANEL = "openfactory/api/panel.html"
PARSE = "openfactory/adapters/tracker/parse.py"
VOICE = "openfactory/product/voice.py"

MUTATIONS = [
    # ── 1. the edit gate ───────────────────────────────────────────────────────────────────────
    ("THE RULE ITSELF: a card the factory has taken up is edited anyway, so an agent's target "
     "moves under it with nobody seeing", CATALOG,
     "               or await asyncio.to_thread(lambda: _stage_refusal(proj, board, issue)))",
     "               or await asyncio.to_thread(lambda: ''))"),

    ("every column reads as the operator's, so `in_progress` and `in_review` are editable too",
     COLUMNS,
     '    return bool(key) and key not in BEFORE_THE_FACTORY',
     "    return False"),

    ("a board that could not be read is treated as a card nobody has moved", CATALOG,
     '    where = board.columns()\n    if where is None:',
     "    where = board.columns()\n    if False:"),

    # RE-PINNED 2026-09-19 (#162): the board read moved out of `_stage_refusal` into `_stage`, so
    # the close can learn the column's KEY from the same read the refusal judged.
    ("a column this platform does not map is judged anyway, as if it were the operator's", CATALOG,
     "    if not key:\n        return _Stage(column=column, cannot_tell=(",
     "    if False:\n        return _Stage(column=column, cannot_tell=("),

    # ── 2. the record ──────────────────────────────────────────────────────────────────────────
    ("an edit leaves no record, so somebody else's text is rewritten with nothing in the thread",
     CATALOG,
     '            tracker.comment(issue, card_edit_note(who=str(by), parts=changed,\n'
     '                                                  language=getattr(proj, "language", '
     'None)))',
     "            pass"),

    # ── 3. closing ─────────────────────────────────────────────────────────────────────────────
    ("a card an operator withdrew is recorded as delivered work, which is what eleven cards closed "
     "as duplicates once looked like downstream", CATALOG,
     # RE-PINNED 2026-09-19 (#162): the word is decided by the card's column now, so the cut is
     # "every close is a delivery" rather than a flipped literal.
     "    delivered = has_finished(stage.key)\n",
     "    delivered = True\n"),

    # The `required` tuple protects a MISSING reason. The in-function check below protects a reason
    # of only spaces, which `perform`'s `in (None, "")` lets through. It was once removed here as
    # dead on a surviving row; the row survived because nothing drove a whitespace-only reason —
    # a weak guard, found by the review of #153.
    ("a close needs no reason, so the next reader of the card has nothing", CATALOG,
     '            required=("project", "issue", "reason"),',
     '            required=("project", "issue"),'),

    ("reopening leaves the closing reason on the card, so an open card still says why it was "
     "closed", LOCAL,
     '                "UPDATE cards SET state = \'open\', closed_reason = \'\', column_key = ?, "',
     '                "UPDATE cards SET state = \'open\', column_key = ?, "'),

    # ── 4. a row that cannot do it ─────────────────────────────────────────────────────────────
    ("a tracker that cannot rename is called anyway, so the panel offers a button that raises",
     CATALOG,
     "    if wanted_title and rename is None:",
     "    if False:"),

    # ── 5. the product owner's cards ───────────────────────────────────────────────────────────
    ("THE DECISION ITSELF: a card the product role opened is edited from the board like any other",
     CATALOG,
     '    refusal = (await asyncio.to_thread(_product_owned_refusal, tracker, issue, '
     'act="changes")\n'
     "               or await asyncio.to_thread(lambda: _stage_refusal(proj, board, issue)))",
     "    refusal = await asyncio.to_thread(lambda: _stage_refusal(proj, board, issue))"),

    ("a card the product role opened is closed from the board, killing what somebody asked for",
     CATALOG,
     # RE-PINNED 2026-09-19 (#162): the two refusals are asked one after the other now.
     '    refusal = await asyncio.to_thread(_product_owned_refusal, tracker, issue, '
     'act="closes")\n',
     "    refusal = None\n"),

    ("a card the product owner closed is reopened from the board", CATALOG,
     '    owned = await asyncio.to_thread(_product_owned_refusal, tracker, issue, act="reopens")\n'
     "    if owned:",
     '    owned = await asyncio.to_thread(_product_owned_refusal, tracker, issue, act="reopens")\n'
     "    if False:"),

    ("a card nobody could read is changed blind, though it may be somebody's promise", CATALOG,
     "        return (f\"{issue} could not be read, so there is no way to tell whether the product "
     "role \"",
     "        return \"\"\n"
     "        return (f\"{issue} could not be read, so there is no way to tell whether the "
     "product role \""),

    ("a requirement card's refusal no longer says the requirement changes first", CATALOG,
     '                    " It changes the requirement first, and then realigns this card to '
     'it."),',
     '                    ""),'),

    ("a card opened from a request is not recognised, so it is rewritten from the board", AUTHORING,
     "    if any(line.startswith(_FROM_A_REQUEST) for line in lines):",
     "    if False:"),

    ("a card opened from a defect is not recognised", AUTHORING,
     "    if any(line.startswith(_FROM_A_DEFECT) for line in lines):",
     "    if False:"),

    ("a requirement card is not recognised", AUTHORING,
     "    if any(line.startswith(_FROM_A_REQUIREMENT) for line in lines):",
     "    if False:"),

    ("the marker is searched anywhere in the text, so a person quoting it loses their own card",
     AUTHORING,
     "    if any(line.startswith(_FROM_A_REQUIREMENT) for line in lines):",
     "    if any(_FROM_A_REQUIREMENT in line for line in lines):"),

    ("the writer's line drifts from the reader's constant, and every new requirement card is the "
     "board's", AUTHORING,
     '        f"{_FROM_A_REQUIREMENT} If the work needs a decision that is not written there, '
     'the "',
     '        "Nothing in this card may go beyond that requirement. If the work needs a decision '
     'that is not written there, the "'),

    ("the drawer is not told who opened the card", APP,
     '        "opened_by_product": _opened_by_product(getattr(ticket, "raw", "") or ""),',
     '        "opened_by_product": "",'),

    ("the drawer offers edit and close on a card the row will refuse", PANEL,
     "          ${c.opened_by_product\n",
     "          ${false\n"),

    # ── 6. the note says which part moved ──────────────────────────────────────────────────────
    ("THE NOTE AGAIN: every save is recorded as a rewrite of the whole description", CATALOG,
     "            changed += sections\n",
     '            changed += ["description"]\n'),

    ("a title sent unchanged is renamed and recorded as edited", CATALOG,
     '        if wanted_title and wanted_title != (current.title or "").strip():',
     "        if wanted_title:"),

    ("a save that changes nothing still leaves a note claiming it did", CATALOG,
     "        if not changed:\n            return changed",
     "        if False:\n            return changed"),

    ("a blank line counts as a change, so a reformatted body is recorded as rewritten", PARSE,
     '    return "\\n".join(line.rstrip() for line in (text or "").strip().splitlines() '
     'if line.strip())',
     '    return text or ""'),

    ("a heading renamed to its canonical spelling is recorded as a change", PARSE,
     '            found.setdefault(key or norm, (written if not key else key, text))',
     '            found.setdefault(norm, (written if not key else key, text))'),

    ("a section somebody deleted is not reported", PARSE,
     "                (key in old) != (key in new)):",
     "                False):"),

    ("the front matter is not compared", PARSE,
     '    if fm_before != fm_after:\n        changed.append("front matter")',
     '    if False:\n        changed.append("front matter")'),

    # ── 7. the review of #153: each write its own outcome, a running card not closed ────────────
    ("a reason of only spaces closes the card with a note ending in a space", CATALOG,
     "    if not said:\n"
     '        return refused(INVALID, "say why the card is being closed',
     "    if False:\n"
     '        return refused(INVALID, "say why the card is being closed'),

    ("a card the factory has taken up is closed from under its running job", CATALOG,
     # RE-PINNED 2026-09-19 (#162): the stage is read once and handed to the refusal.
     '    refusal = _stage_refusal(proj, board, issue, act="close", stage=stage)',
     "    refusal = None"),

    ("a body that failed after the rename answers \"nothing was changed\" over a renamed card",
     CATALOG,
     "        except Exception as exc:  # noqa: BLE001 — what landed before it is still reported\n"
     "            failure = str(exc) or type(exc).__name__",
     "        except Exception:\n"
     "            raise"),

    ("an edit whose note failed is reported as an edit that did not happen", CATALOG,
     "        except Exception as exc:  # noqa: BLE001 — the edit landed; only its record did "
     "not\n",
     "        except ZeroDivisionError as exc:\n"),

    ("a reopen whose note failed is reported as a card still closed", CATALOG,
     "    except Exception as exc:  # noqa: BLE001 — the reopen landed; only its record did not\n",
     "    except ZeroDivisionError as exc:\n"),

    ("the reopen and its note share one `AttributeError` branch again, so a failed note reads as "
     "a tracker that cannot reopen", CATALOG,
     "    try:\n"
     "        reopen = tracker.reopen_ticket\n"
     "    except AttributeError:",
     "    try:\n"
     "        reopen = tracker.reopen_ticket\n"
     "        tracker.comment(issue, card_reopen_note(who=str(by)))\n"
     "    except AttributeError:"),

    ("the note lists the parts as one run-on phrase joined by `and`", VOICE,
     '    return ", ".join(named[:-1]) + _pick(_AND, language) + named[-1]',
     '    return _pick(_AND, language).join(named)'),
]
