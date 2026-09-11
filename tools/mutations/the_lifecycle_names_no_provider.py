"""ADR-0049 slice 0, proven by breaking it — the platform's vocabulary and the row's own answers.

THREE CLAIMS, AND EACH ONE HAS A RED TWIN HERE:

  1. **The columns are the platform's and live in one place.** Six names, six neutral keys, one
     board order. Cutting the home, the order or any of the four neutral callers must be seen.
  2. **The row answers who a person is and how to address them.** The lifecycle used to compare
     the provider's name; the port now carries the question. Cutting the degradation, the
     precedence between a declared map and a row, or the row's own answer must be seen.
  3. **The lifecycle names no provider.** The guard is itself mutated — HOSTILE cuts that keep
     every vocabulary word and stop the rule from reaching the thing it forbids, which is the cut
     a reviewer lands rather than "delete the assert".

WHAT THE FIRST RUN FOUND, because it is the point of running rather than re-reading. Four rows
survived, and all four were the guards' fault rather than the plan's:

  · the poller's `CANONICAL_COLUMNS["todo"]` cut back to the literal `"TO-DO"` and NOTHING could
    see it — the two spell the same six characters, and that caller's answer lives inside a
    function where no attribute can be read for it. Fixed by moving the home and asking the caller
    again (`test_the_pollers_last_resort_follows_the_home_rather_than_a_literal`);
  · TWO of the guard's own planted twins re-implemented the rule inline instead of calling it, so
    a cut to the real walk left the twin's copy proving itself. The rule is now
    `provider_kind_decisions` / `provider_words`, called by the property AND by its twin;
  · dropping a file from `LIFECYCLE` made a parametrized guard run FEWER cases and stay green —
    a property silently ceasing to cover the module it was written for. The scope is now asserted.

The guards under test:
  · `tests/test_the_columns_and_the_identity_are_the_platforms.py` — the move and the capabilities;
  · `tests/test_the_lifecycle_names_no_provider.py` — the property, and its own two planted cases;
  · `tests/test_the_docs_do_not_drift.py` — the count the new record changes.
"""

import pathlib

TEST = "tests/test_the_columns_and_the_identity_are_the_platforms.py"

COLUMNS = "tests/test_the_columns_and_the_identity_are_the_platforms.py"
GUARD = "tests/test_the_lifecycle_names_no_provider.py"
DRIFT = "tests/test_the_docs_do_not_drift.py"

HOME = "openfactory/adapters/board/columns.py"
GH_SETUP = "openfactory/adapters/tracker/github_board_setup.py"
GH_BOARD = "openfactory/adapters/tracker/github_project.py"
MODULE = "openfactory/product/module.py"
TRIAGE = "openfactory/product/triage.py"
ACTIVITIES = "openfactory/runtime/temporal/activities.py"
REQUESTER = "openfactory/product/requester.py"
GH_TRACKER = "openfactory/adapters/tracker/github.py"

#: DERIVED, because a hard-coded count here rots on every new record — which it did, twice.
_ADRS = len(list((pathlib.Path(__file__).resolve().parents[2] / "docs" / "adr")
                 .glob("[0-9][0-9][0-9][0-9]-*.md")))

MUTATIONS = [
    # ── 1. the columns: the home, the order, and every caller that used to spell a literal ─────
    ("a name in the home changes — the platform's own word for the pickup column, which is what "
     "a board is CREATED with and what the poller then looks for", HOME,
     '    "todo": "TO-DO",', '    "todo": "To Do",', COLUMNS),

    ("the board order silently drops a column, so a created board has five and the sixth is a "
     "column `set_column` can never find", HOME,
     '    "backlog", "todo", "in_progress", "in_review", "needs_action", "done",',
     '    "todo", "in_progress", "in_review", "needs_action", "done",', COLUMNS),

    ("the order and the map disagree — the exact rot the two tables had before the move, a key "
     "in the order that the map cannot name", HOME,
     'BOARD_ORDER: tuple[str, ...] = (\n    "backlog", "todo", "in_progress", "in_review", '
     '"needs_action", "done",\n)',
     'BOARD_ORDER: tuple[str, ...] = (\n    "backlog", "todo", "in_progress", "in_review", '
     '"needs_action", "done", "sprint",\n)', COLUMNS),

    ("`name_for` raises on a key the platform does not know, instead of answering `\"\"` — a "
     "board without the column becomes a crashed job", HOME,
     '    return CANONICAL_COLUMNS.get((key or "").strip().lower(), "")',
     '    return CANONICAL_COLUMNS[(key or "").strip().lower()]', COLUMNS),

    ("the creating act writes its own six names again, at the vendor's address — the copy the "
     "move exists to end, and it drifts by one word", GH_SETUP,
     "CANONICAL_COLUMNS = column_names()",
     'CANONICAL_COLUMNS = ("Backlog", "To Do", "In progress", "In review", "Needs Action", "Done")',
     COLUMNS),

    ("the runtime board hands out the home itself rather than a copy, so a caller mutating the "
     "adapter's dict edits the table every other axis reads", GH_BOARD,
     "DEFAULT_COLUMNS: dict[str, str] = dict(CANONICAL_COLUMNS)",
     "DEFAULT_COLUMNS: dict[str, str] = CANONICAL_COLUMNS", COLUMNS),

    ("the product role files work into a column that is not the platform's backlog — filed work "
     "lands where readiness cannot see it", MODULE,
     '    FILING_COLUMN = CANONICAL_COLUMNS["backlog"]',
     '    FILING_COLUMN = CANONICAL_COLUMNS["done"]', COLUMNS),

    ("the queue column stops being the one the poller pulls from", MODULE,
     '    QUEUE_COLUMN = CANONICAL_COLUMNS["todo"]',
     '    QUEUE_COLUMN = CANONICAL_COLUMNS["in_progress"]', COLUMNS),

    ("the triage reads the wrong column for work in flight, so every active card reports as "
     "something else", TRIAGE,
     '           active_columns: tuple[str, ...] = (CANONICAL_COLUMNS["in_progress"],),',
     '           active_columns: tuple[str, ...] = (CANONICAL_COLUMNS["in_review"],),', COLUMNS),

    ("the poller's last-resort pickup column goes back to a literal — right for one vendor and "
     "wrong for the platform's own board", ACTIVITIES,
     '            or CANONICAL_COLUMNS["todo"])', '            or "TO-DO")', COLUMNS),

    # ── 2. the identity: the row answers, and the declared map still wins ───────────────────────
    ("a tracker that implements no `mention` gets an `@` bolted on anyway — the lifecycle "
     "deciding for a row again, one layer down", ACTIVITIES,
     '    fn = getattr(tracker, "mention", None)\n    if not fn or not who:\n        return who',
     '    fn = getattr(tracker, "mention", None)\n    if not fn or not who:\n'
     '        return f"@{who}" if who else who', COLUMNS),

    ("a vendor that raises while rendering a mention takes the question with it — the comment is "
     "about to be posted, and the person is never asked", ACTIVITIES,
     '    except Exception as exc:  # noqa: BLE001 — an unrenderable mention must not lose the '
     'question\n        activity.logger.info("could not render a mention for %s (%s) — using the '
     'plain name",\n                             who, exc)\n        return who',
     '    except Exception:  # noqa: BLE001\n        raise', COLUMNS),

    ("the row is asked BEFORE the declared map, so a deployment that wrote down who its people "
     "are is overruled by a row's guess", REQUESTER,
     '    if hits:\n        return hits[0] if len(hits) == 1 else ""\n'
     '    fn = getattr(tracker, "identity_of", None)',
     '    fn = getattr(tracker, "identity_of", None)\n'
     '    if fn and (early := (fn(who) or "").strip()):\n        return early\n'
     '    if hits:\n        return hits[0] if len(hits) == 1 else ""', COLUMNS),

    ("an AMBIGUOUS declaration lets the row answer over it — two logins for one id is a mistake "
     "somebody has to fix, and this hides it behind a plausible name", REQUESTER,
     '    if hits:\n        return hits[0] if len(hits) == 1 else ""',
     '    if len(hits) == 1:\n        return hits[0]', COLUMNS),

    ("the GitHub row stops rendering the one mention a vendor actually resolves", GH_TRACKER,
     '        return f"@{login}" if (login or "").strip() else ""',
     '        return (login or "").strip()', COLUMNS),

    ("a hosted row claims it CAN spell a platform id in its own namespace — the guess that puts "
     "one person's name on another person's question", GH_TRACKER,
     '    def identity_of(self, subject_id: str) -> str:\n        """`""` — a GitHub login is not '
     'a platform id.',
     '    def identity_of(self, subject_id: str) -> str:\n        return subject_id\n\n'
     '    def _identity_of_retired(self, subject_id: str) -> str:\n        """`""` — a GitHub '
     'login is not a platform id.', COLUMNS),

    # ── 3. the guard itself, cut the way a reviewer would ───────────────────────────────────────
    ("HOSTILE: the guard keeps the word `kind` and stops recognising which chains hold a "
     "PROVIDER's — every provider-kind decision then reads as domain vocabulary", GUARD,
     '        return (len(chain) >= 2 and chain[-1] == "kind"\n'
     '                and chain[-2].lower() in PROVIDER_HOLDERS)',
     '        return len(chain) >= 2 and chain[-1] == "kind" and chain[-2].lower() in ()', GUARD),

    # re-pinned 2026-09-09: the inline walk became `provider_kind_decisions`, which is what made
    # this cut visible in the first place — the twin used to prove its own copy of the rule
    ("HOSTILE: the guard reads only the LEFT side, so writing the comparison the other way round "
     "passes — which is the first thing somebody tries", GUARD,
     "                  and any(_is_provider_kind(s) for s in (node.left, *node.comparators)))",
     "                  and any(_is_provider_kind(s) for s in (node.left,)))", GUARD),

    ("HOSTILE: the vocabulary keeps its name and loses the row this issue adds, so `local` "
     "becomes spellable in the layer that must not know it", GUARD,
     '    "github", "jira", "azure_devops", "local",',
     '    "github", "jira", "azure_devops",', GUARD),

    # re-pinned 2026-09-09: same move — the exemption now lives in `provider_words`
    ("HOSTILE: the prose exemption inverts, so only a docstring is judged and code never is — the "
     "rule keeps every word of its name and measures nothing", GUARD,
     "        and node.lineno not in prose",
     "        and node.lineno in prose", GUARD),

    # re-pinned 2026-09-09: the scope is asserted now, so the cut has TWO anchors to choose from
    # and must take the one at the top of the file — the constant, not the assertion that pins it
    ("HOSTILE: the three files become two — the runner drops out of the property while the "
     "docstring still says all three", GUARD,
     'LIFECYCLE = (\n    "openfactory/orchestrator/machine.py",',
     'LIFECYCLE = (', GUARD),

    # ── 4. the record itself is counted ─────────────────────────────────────────────────────────
    ("the new decision record is announced at the old number, which is the off-by-one the count "
     "guard exists for", "CONTRIBUTING.md",
     f"**why** — {_ADRS} decision records", f"**why** — {_ADRS - 1} decision records", DRIFT),
]
