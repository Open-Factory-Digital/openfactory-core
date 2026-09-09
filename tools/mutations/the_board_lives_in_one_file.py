"""ADR-0049 slice 1, proven by breaking it — the local rows, their file, and the credential
that is not needed.

FOUR CLAIMS, EACH WITH RED TWINS:

  1. **The file's discipline.** WAL, a per-project sequence taken under the write lock, a rollback
     that leaves nothing, and the platform's own timestamp rather than SQLite's.
  2. **The port's three answers.** `None` could not look, `[]` there is nothing — on `comments()`
     and on `columns()`. This is the distinction the whole read side is built on, and it is the
     one a row gets wrong by being helpful.
  3. **The row answers, the caller compares nothing.** The board this project already has, the
     column a state belongs in, the credential this vendor needs: each moved out of neutral code
     into the row, and each cut here puts it back.
  4. **A row that needs no credential never reaches the deployment's own.** The defect the `needs`
     field exists for, and the reason `env=""` could not carry it.

WHAT THE FIRST RUN FOUND, because running is the point. Three rows survived, and each was a case
the guard could not REACH rather than a claim it did not hold:

  · `BEGIN IMMEDIATE` cut to a plain `BEGIN` survived every test here — a write lock is invisible
    to one process. It takes two, racing on a barrier, and the deferred lock then loses a card to
    the primary key (`test_two_writers_never_take_the_same_number`);
  · `set_state` cut from `False` to a raise survived, because every case stopped one line earlier
    at the key lookup. It needs a state that HAS a key on a board missing that column
    (`test_a_column_the_board_does_not_have_is_False_and_never_a_raise`);
  · the `#` on `get_ticket().id` is NOT pinned by the shared read-side contract, for any vendor —
    only this slice's own file asserts it. Noted at the row rather than fixed here.

The guards under test:
  · `tests/test_the_board_lives_in_one_file.py` — this slice's own;
  · `tests/test_the_tracker_has_a_read_side.py` — the read-side contract, which the local row now
    runs through its own table;
  · `tests/test_no_silent_failures.py` — every swallowed exception leaves a trace.
"""

TEST = "tests/test_the_board_lives_in_one_file.py"

SLICE = "tests/test_the_board_lives_in_one_file.py"
READ_SIDE = "tests/test_the_tracker_has_a_read_side.py"
SILENT = "tests/test_no_silent_failures.py"

DB = "openfactory/adapters/board_db.py"
TRACKER = "openfactory/adapters/tracker/local.py"
BOARD = "openfactory/adapters/board/local.py"
SETUP = "openfactory/adapters/board_setup/local.py"
GH_SETUP = "openfactory/adapters/tracker/github_board_setup.py"
CREDS = "openfactory/credentials.py"
CRED_ROWS = "openfactory/adapters/credential/registry.py"
DOCTOR = "openfactory/doctor.py"

MUTATIONS = [
    # ── 1. the file's discipline ───────────────────────────────────────────────────────────────
    ("the write transaction stops being IMMEDIATE, so two processes can read the same next number "
     "and one of them loses its card", DB,
     '        conn.execute("BEGIN IMMEDIATE")', '        conn.execute("BEGIN")', SLICE),

    ("a failed write is COMMITTED anyway — half a card, and the caller was told it failed", DB,
     '        except BaseException:\n            conn.execute("ROLLBACK")\n            raise',
     '        except BaseException:\n            conn.execute("COMMIT")\n            raise', SLICE),

    ("the journal goes back to the default, so the panel reading blocks the worker writing", DB,
     '        conn.execute("PRAGMA journal_mode=WAL")',
     '        conn.execute("PRAGMA journal_mode=DELETE")', SLICE),

    ("the number sequence stops being per project — two projects in one file then fight over "
     "the same numbers", DB,
     '    row = conn.execute("SELECT MAX(ref) AS top FROM cards WHERE project = ?",\n'
     '                       (project,)).fetchone()',
     '    row = conn.execute("SELECT MAX(ref) AS top FROM cards").fetchone()', SLICE),

    ("the timestamp becomes SQLite's, which sorts BELOW the platform's for the same instant — an "
     "answer then reads as older than the question it answers", DB,
     "    return datetime.now(UTC).isoformat()",
     '    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")', SLICE),

    # ── 2. the three answers ───────────────────────────────────────────────────────────────────
    ("a card this file does not hold answers `[]` instead of `None` — the model then concludes "
     "nobody has looked and repeats an answer that already failed", TRACKER,
     "                                (self.project, bare)).fetchone() is None:\n"
     "                    return None",
     "                                (self.project, bare)).fetchone() is None:\n"
     "                    return []", SLICE),

    ("an unreadable FILE answers `[]` too — the same collapse, one layer out", TRACKER,
     '            log.warning("could not read the comments on %s — answering \'could not look\' '
     "rather \"\n                        \"than 'there are none'\", canonical_ref(ref), "
     "exc_info=True)\n            return None",
     '            log.warning("could not read the comments on %s", canonical_ref(ref), '
     "exc_info=True)\n            return []", SLICE),

    ("an unreadable board answers `{}` — read fine and empty, which is how the factory once "
     "reported itself idle with a queue of work in front of it", BOARD,
     '        except Exception:  # noqa: BLE001 — unreadable is not empty\n'
     '            log.warning("could not read %s\'s board", self.project, exc_info=True)\n'
     "            return None",
     '        except Exception:  # noqa: BLE001\n'
     '            log.warning("could not read %s\'s board", self.project, exc_info=True)\n'
     "            return {}", SLICE),

    ("an unreadable column list answers `[]`, which reads as 'configured and empty' and passes "
     "a setup that will never pick anything up", BOARD,
     '        except Exception:  # noqa: BLE001 — see `columns`\n'
     '            log.warning("could not read %s\'s columns", self.project, exc_info=True)\n'
     "            return None",
     '        except Exception:  # noqa: BLE001\n'
     '            log.warning("could not read %s\'s columns", self.project, exc_info=True)\n'
     "            return []", SLICE),

    ("the pickup column swallows its failure with no trace at all", BOARD,
     '        except Exception:  # noqa: BLE001 — never raise inside a poll tick\n'
     '            log.warning("could not ask %s\'s board what it calls its pickup column — '
     'falling back "\n                        "to the platform\'s own name for it", self.project, '
     "exc_info=True)\n            row = None",
     "        except Exception:  # noqa: BLE001\n            row = None", SILENT),

    # ── 3. the row answers, the caller compares nothing ────────────────────────────────────────
    # A FINDING FROM THE FIRST RUN, kept as a note rather than a fix: this cut SURVIVED against
    # `READ_SIDE`, the contract every tracker row runs. That suite does not pin the `#` on
    # `get_ticket().id` for any vendor — the shared contract is one assertion short, and only this
    # slice's own file catches it. Widening the shared contract is a change to four rows' guard
    # and belongs in its own card; the cut is pinned where it is actually seen.
    ("the two spellings collapse: a ticket's own id loses its hash and stops being the port's",
     TRACKER,
     '        ticket = parse_ticket_body(id=f"#{bare}", title=row["title"], body=row["body"] or "",',
     '        ticket = parse_ticket_body(id=str(bare), title=row["title"], body=row["body"] or "",',
     SLICE),

    ("a state the board has no column for RAISES instead of answering False — the gather's park "
     "path then dies where it should have said the park did not land", TRACKER,
     '            if conn.execute("SELECT 1 FROM columns WHERE project = ? AND key = ?",\n'
     "                            (self.project, key)).fetchone() is None:\n"
     "                return False",
     '            if conn.execute("SELECT 1 FROM columns WHERE project = ? AND key = ?",\n'
     "                            (self.project, key)).fetchone() is None:\n"
     '                raise KeyError(key)', SLICE),

    ("a person's answer is written as the platform, so the sweep never counts it and chases them "
     "for something they had already said", TRACKER,
     "                (self.project, bare, int(row[\"top\"] or 0) + 1, (author or \"\").strip(),\n"
     '                 body or "", when))',
     "                (self.project, bare, int(row[\"top\"] or 0) + 1, BOT_AUTHOR,\n"
     '                 body or "", when))', SLICE),

    ("the row claims it cannot spell a platform identity, which switches the whole "
     "ask-before-you-spend loop off for the one deployment this issue is for", TRACKER,
     '        return (subject_id or "").strip()\n\n    def mention',
     '        return ""\n\n    def mention', SLICE),

    ("the ticket url goes back to a vendor's shape instead of the panel's own route", TRACKER,
     '        return f"{panel_url()}/p/{self.project}/card/{_number(ref)}"',
     '        return f"https://example.invalid/{self.project}/issues/{_number(ref)}"', SLICE),

    ("a move to a column the board does not have reports success, so a card is 'queued' into "
     "nowhere", BOARD,
     '            if col is None:\n'
     '                log.warning("%s\'s board has no column named %r — the card stays where it is",'
     "\n                            self.project, wanted)\n                return False",
     '            if col is None:\n'
     '                log.warning("%s\'s board has no column named %r", self.project, wanted)\n'
     "                return True", SLICE),

    ("the board stops going through the platform's one state resolution and pins its own map — "
     "the `pr_open` a person is blocking on stops landing in Needs Action (#166)", BOARD,
     "        key = column_key(state, needs_person=needs_person)",
     '        key = {JobState.DONE: "done"}.get(state, "in_review")', SLICE),

    ("creating the board RENAMES the columns on every run, undoing the edit `columns:` promises "
     "a client they may make (C-14)", SETUP,
     '                    "INSERT OR IGNORE INTO columns(project, key, name, position) '
     'VALUES (?,?,?,?)",',
     '                    "INSERT OR REPLACE INTO columns(project, key, name, position) '
     'VALUES (?,?,?,?)",', SLICE),

    ("the platform's own board claims a coordinate it does not have, and `init` writes an empty "
     "one into the registry for every later read to special-case", SETUP,
     '        return "", f"{panel_url()}/p/{name}/board"',
     '        return name, f"{panel_url()}/p/{name}/board"', SLICE),

    ("the GitHub row stops refusing an empty owner in its own words, and the refusal has nowhere "
     "left to live now that the caller no longer makes it", GH_SETUP,
     '        if not (owner or "").strip():\n            raise BoardSetupError(',
     '        if False:\n            raise BoardSetupError(', SLICE),

    ("the row is asked nothing about the board this project already has, so an idempotent command "
     "recreates it", GH_SETUP,
     '        return f"{owner}/#{number}" if owner and number else ""',
     '        return ""', SLICE),

    # ── 4. the credential that is not needed ───────────────────────────────────────────────────
    ("a vendor that needs nothing falls through to the deployment's own pair — a local project on "
     "a machine that also runs a GitHub one is handed that project's token", CREDS,
     "    if not vendor_needs_credential(ref):\n        return \"\", None\n",
     ""
     , SLICE),

    ("`needs` defaults to False, so every row that declares nothing silently stops resolving a "
     "credential it does need", CRED_ROWS,
     "    needs: bool = True", "    needs: bool = False", SLICE),

    ("the local row says it needs a credential after all, and the doctor sends somebody to "
     "configure one that belongs to another system", CRED_ROWS,
     "    return CredentialRow(needs=False)", "    return CredentialRow()", SLICE),

    ("the doctor reports a missing credential for a vendor that needs none", DOCTOR,
     "        if token is None and not has_app and not vendor_needs_credential(axis):\n"
     "            return True, \"\"\n",
     "", SLICE),
]
