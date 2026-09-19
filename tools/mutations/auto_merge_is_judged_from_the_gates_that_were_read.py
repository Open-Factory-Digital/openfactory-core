"""Proven by breaking it — `merge_policy: auto` is judged from the gates that were read, once.

The doctor's `merge_policy` check asked the forge `requires_review()`, a method no row ever
defined: it could not fail, and it printed "consistent with the repository's branch protection"
about protection nobody had read — since #184, one line above the finding that failed the same
repository for the review it had just listed. The check is folded into `merge_gates`, the probe
is deleted, and the rows are the one source (2026-09-19).

THREE CLAIMS:

  1. **`auto` is judged from the listing, by one finding.** Red against a required review that
     was read; UNCHECKED — in the message and in the note the verdict repeats — where nothing was
     read; "consistent" only with gates that were listed; and none of it under `human`.
  2. **Nothing else speaks for the policy**: no second finding, no second probe.
  3. **The class**: no capability is asked of a forge row, by name, that no shipped row declares.

The guard is `tests/test_auto_merge_is_judged_from_the_gates_that_were_read.py`.
"""

TEST = "tests/test_auto_merge_is_judged_from_the_gates_that_were_read.py"

DOCTOR = "openfactory/doctor.py"
BASE = "openfactory/adapters/forge/base.py"

MUTATIONS = [
    # ── claim 1: judged from the listing ──────────────────────────────────────────────────────
    ("THE DEFECT: `auto` is called consistent with protection nobody read", DOCTOR,
     '               "was NOT checked" if policy == "auto" else ""),\n',
     '               "is consistent with the repository\'s branch protection" '
     'if policy == "auto" else ""),\n'),

    ("`auto` against an unread listing is told nothing about not having been checked", DOCTOR,
     '               "was NOT checked" if policy == "auto" else ""),\n',
     '               "was NOT checked" if False else ""),\n'),

    ("the closing verdict does not repeat that `auto` went unchecked", DOCTOR,
     '                  "they could not be listed" if policy == "auto" else ""))\n',
     '                  "they could not be listed" if False else ""))\n'),

    ("a project where a person merges is told its auto-merge was not checked", DOCTOR,
     '               "was NOT checked" if policy == "auto" else ""),\n',
     '               "was NOT checked" if True else ""),\n'),

    ("`auto` is never told it is consistent with the gates that were listed", DOCTOR,
     '            + (" — merge_policy \'auto\' is consistent with them" if policy == "auto" '
     'else ""))\n',
     '            + (" — merge_policy \'auto\' is consistent with them" if False else ""))\n'),

    ("a project where a person merges is told about `auto`", DOCTOR,
     '            + (" — merge_policy \'auto\' is consistent with them" if policy == "auto" '
     'else ""))\n',
     '            + (" — merge_policy \'auto\' is consistent with them" if True else ""))\n'),

    ("under auto-merge a required review that was read passes", DOCTOR,
     '    if policy == "auto":\n',
     "    if False:\n"),

    ("an unreadable manifest beside an unread listing is judged as auto-merge", DOCTOR,
     '                  "merge_policy \'human\'", str(exc)[:160])\n        policy = "human"\n',
     '                  "merge_policy \'human\'", str(exc)[:160])\n        policy = "auto"\n'),

    # ── claim 2: nothing else speaks for the policy ───────────────────────────────────────────
    ("the old check is back: a second finding vouches for the policy", DOCTOR,
     '        _guarded("board_columns", lambda: _board(probes)),\n',
     '        _guarded("board_columns", lambda: _board(probes)),\n'
     '        Finding("merge_policy", True, "merge_policy is consistent with the repository\'s "\n'
     '                                      "branch protection"),\n'),

    ("a second probe answers for the review", DOCTOR,
     "    merge_gates: Callable[[], list[dict] | Exception | None] | None = None\n",
     "    merge_gates: Callable[[], list[dict] | Exception | None] | None = None\n"
     "    requires_review: Callable[[], bool] | None = None\n"),

    # ── claim 3: the class ────────────────────────────────────────────────────────────────────
    ("the doctor asks its forge, again, a question no row answers", DOCTOR,
     "        return merge_gates_of(build_forge(project, token=forge_token_for(project)), base)\n",
     "        forge = build_forge(project, token=forge_token_for(project))\n"
     '        if getattr(forge, "requires_review", None):\n'
     "            return None\n"
     "        return merge_gates_of(forge, base)\n"),

    ("the port asks for the gates under a name no row declares", BASE,
     '    ask = getattr(forge, "merge_gates", None)\n',
     '    ask = getattr(forge, "list_merge_gates", None)\n'),
]
