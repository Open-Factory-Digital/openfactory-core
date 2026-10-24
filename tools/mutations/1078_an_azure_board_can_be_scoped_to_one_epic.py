"""An Azure Boards project reads and claims only the cards under ONE Epic (#1078).

The claims, each held by a test this plan cuts under:

  - a project's `scope_epic` reaches its board from the registry row, and the board puts the
    Epic's subtree into the flat query it always asked (`[System.Id] IN (…)`), so the queue is the
    Epic's and not the team's;
  - the tracker, which the panel, the product role and the "already filed?" check read through,
    asks the same: `list_tickets` and `find_ticket` answer only within the subtree;
  - the subtree is read ONCE per instance, not once per column or per question;
  - a project that declares no scope, or only whitespace, reads exactly what it always read and
    asks for no subtree;
  - it FAILS CLOSED: an id that names nothing, one that is not a number, a subtree past the
    ceiling and a failed request are all an unreadable board (`None`) — never "no scope", which
    would hand the factory the whole team; an Epic with nothing under it is an empty queue and a
    READABLE board, told apart from a missing one by the root of the recursive query;
  - the id is a number by PATTERN, because `int()` accepts `1_0` and `+5`;
  - the board answers `holds(ref)` and `scope_named()`, which the edit/close/remove gate and the
    product role's queueing and ordering read through `getattr`: another Epic's card is refused by
    name, one that could not be asked about is refused as an unreadable board, and an unscoped
    board asks nothing more;
  - the board's remedy for an unreadable board names `scope_epic` when there is one.
"""

TEST = "tests/test_an_azure_board_can_be_scoped_to_one_epic.py"
SHARED = "openfactory/adapters/azure_devops.py"
BOARD = "openfactory/adapters/board/azure_devops.py"
FACTORY = "openfactory/adapters/board/factory.py"
TRACKER = "openfactory/adapters/tracker/azure_devops.py"

MUTATIONS = [
    # ── the option reaches the board, and the board uses it ────────────────────────────────────
    ("the registry row drops the project's scope, and its board queues the whole team",
     FACTORY,
     "scope_epic=scope_epic_of(options),",
     'scope_epic="",'),

    ("the board reads the subtree and never puts it in the query",
     BOARD,
     "where.append(within_epic(below))",
     "pass"),

    ("the scope is read on the UNSCOPED path too, one wasted request for every project",
     BOARD,
     "        if self._scope_epic:\n            below = self._epic_ids()",
     "        if True:\n            below = self._epic_ids()"),

    ("the subtree is read again for every column and every question",
     BOARD,
     "if self._epic_read:",
     "if False:"),

    # ── it fails closed ────────────────────────────────────────────────────────────────────────
    ("an unreadable scope collapses into an empty queue, and `columns()` stops saying `None`",
     BOARD,
     "            if below is None:\n                return None\n            if not below:",
     "            if not below:"),

    ("an id that names nothing is read as an Epic with no children",
     SHARED,
     '    if not any(r.get("source") is None',
     '    if False and not any(r.get("source") is None'),

    ("any string that Python's int() accepts is taken for an id",
     SHARED,
     'if not re.fullmatch(r"[0-9]+", epic or ""):',
     "if not epic:"),

    ("a subtree past the ceiling is read anyway, and the query overruns WIQL's length",
     SHARED,
     "if len(below) > SCOPE_CEILING:",
     "if False:"),

    ("…and the ceiling is one too few: a subtree exactly at it is refused",
     SHARED,
     "if len(below) > SCOPE_CEILING:",
     "if len(below) >= SCOPE_CEILING:"),

    ("the Epic itself is counted as a card under it",
     SHARED,
     'if r.get("source") is not None and (r.get("target") or {}).get("id"))',
     'if (r.get("target") or {}).get("id"))'),

    ("whitespace alone is a scope: a blank YAML key becomes an id that is not one",
     SHARED,
     'return str((options or {}).get("scope_epic") or "").strip()',
     'return str((options or {}).get("scope_epic") or "")'),

    # ── the gate and the product role ──────────────────────────────────────────────────────────
    ("the board holds every card, so another Epic's card is edited, queued and ranked",
     BOARD,
     "return number is not None and str(number) in below",
     "return True"),

    ("a scope that could not be asked about is read as `it is not ours`, a final refusal",
     BOARD,
     "            return None\n        number = ref_number(split_repo_ref(ref)[1])",
     "            return False\n        number = ref_number(split_repo_ref(ref)[1])"),

    ("the refusal of a card outside the slice no longer names the scope",
     BOARD,
     'return f"within scope_epic {self._scope_epic!r}" if self._scope_epic else ""',
     'return ""'),

    # ── the tracker ────────────────────────────────────────────────────────────────────────────
    ("`list_tickets` lists every work item of the project, under any Epic",
     TRACKER,
     "clauses.append(within_epic(below))",
     "pass"),

    ("`find_ticket` reuses another Epic's open card of the same title",
     TRACKER,
     'scope = f"AND {within_epic(below)} "',
     'scope = ""'),

    ("the tracker reads the subtree again for every question",
     TRACKER,
     "if self._epic_outcome is None:",
     "if True:"),

    ("an unresolvable scope is an empty subtree: `find_ticket` says `None`, a duplicate is filed",
     TRACKER,
     "raise self._epic_outcome",
     "return frozenset()"),

    # ── the doctor's remedy ────────────────────────────────────────────────────────────────────
    ("the remedy for an unreadable board never names the scope",
     FACTORY,
     "    if scope:\n        remedy +=",
     "    if False:\n        remedy +="),
]
