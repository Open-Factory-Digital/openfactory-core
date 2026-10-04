"""No `gh` call acts on a repository it was not given, and the suite has no `gh` login to act with.

Run:  .venv/bin/python tools/mutate.py \
        tools/mutations/the_suite_never_writes_to_a_real_repository.py

Rows 1-2 are the leak as it shipped, one per GitHub row: an empty `--repo` reaches `gh`, which
fills it in from the working directory. Rows 3-5 narrow the rule: blank is not empty, `-R` is not
`--repo`, `--repo=` is not seen. Rows 6-9 (review of #489): the board's `--owner` reaches `gh`, and
`--owner`, `--head` and `--base` are left out of the guessed flags. Row 10 gives `gh` back whatever
configuration the shell names. Row 11 installs the live test's card and asserts nothing of it.
"""

TEST = "tests/test_the_suite_never_writes_to_a_real_repository.py"

TRACKER = "openfactory/adapters/tracker/github.py"
FORGE = "openfactory/adapters/forge/github.py"
RULE = "openfactory/adapters/github_cli.py"
CONFTEST = "tests/conftest.py"
LIVE = "tests/test_a_preview_starts_on_a_real_daemon.py"

GUARD = "        why = nothing_named(args)\n"
BOARD = "openfactory/adapters/tracker/github_project.py"

MUTATIONS = [
    ("THE LEAK, on the tracker: an empty --repo reaches gh", TRACKER, GUARD, '        why = ""\n'),

    ("THE LEAK, on the forge: an empty --repo reaches gh", FORGE, GUARD, '        why = ""\n'),

    ("a blank repository passes for a named one", RULE,
     '        if not str(value or "").strip():\n',
     "        if not value:\n"),

    # re-pinned 2026-10-03: the rule covers every flag `gh` fills in by guessing (review of #489)
    ("-R is not read as --repo", RULE,
     '    "-R": "the repository of the directory it runs in",\n',
     ""),

    ("--repo= with nothing after it is not seen", RULE,
     '        value = inline if inline is not None else (args[i + 1] if i + 1 < len(args) else "")',
     '        value = args[i + 1] if i + 1 < len(args) else "x"'),

    ("THE SAME LEAK, on the board: an empty --owner reaches gh as the logged-in account", BOARD,
     "    why = nothing_named(args)\n",
     '    why = ""\n'),

    ("an empty --owner is not one of the guessed flags", RULE,
     '    "--owner": "the account it is logged in as",\n',
     ""),

    ("an empty --head is not one of the guessed flags", RULE,
     '    "--head": "the branch checked out in the directory it runs in",\n',
     ""),

    ("an empty --base is not one of the guessed flags", RULE,
     '    "--base": "the repository\'s default branch",\n',
     ""),

    ("gh reads whatever configuration the operator's shell names", CONFTEST,
     '    os.environ["GH_CONFIG_DIR"] = str(gh_config)\n',
     ""),

    ("the live test installs its card and asserts nothing of it", LIVE,
     "        ((ref, said),) = card.said\n",
     ""),
]
