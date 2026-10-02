"""No `gh` call acts on a repository it was not given, and the suite has no `gh` login to act with.

Run:  .venv/bin/python tools/mutate.py \
        tools/mutations/the_suite_never_writes_to_a_real_repository.py

Rows 1-2 are the leak as it shipped, one per GitHub row: an empty `--repo` reaches `gh`, which
fills it in from the working directory. Rows 3-5 narrow the rule: blank is not empty, `-R` is not
`--repo`, `--repo=` is not seen. Row 6 gives `gh` back whatever configuration the shell names.
Row 7 installs the live test's card and asserts nothing of it.
"""

TEST = "tests/test_the_suite_never_writes_to_a_real_repository.py"

TRACKER = "openfactory/adapters/tracker/github.py"
FORGE = "openfactory/adapters/forge/github.py"
RULE = "openfactory/adapters/github_cli.py"
CONFTEST = "tests/conftest.py"
LIVE = "tests/test_a_preview_starts_on_a_real_daemon.py"

GUARD = "        why = no_repository_named(args)\n"

MUTATIONS = [
    ("THE LEAK, on the tracker: an empty --repo reaches gh", TRACKER, GUARD, '        why = ""\n'),

    ("THE LEAK, on the forge: an empty --repo reaches gh", FORGE, GUARD, '        why = ""\n'),

    ("a blank repository passes for a named one", RULE,
     '            if not str(value or "").strip():\n',
     "            if not value:\n"),

    ("-R is not read as --repo", RULE,
     '        if arg in ("--repo", "-R"):\n',
     '        if arg == "--repo":\n'),

    ("--repo= with nothing after it is not seen", RULE,
     '        elif arg.startswith("--repo="):\n',
     "        elif False:\n"),

    ("gh reads whatever configuration the operator's shell names", CONFTEST,
     '    os.environ["GH_CONFIG_DIR"] = str(gh_config)\n',
     ""),

    ("the live test installs its card and asserts nothing of it", LIVE,
     "        ((ref, said),) = card.said\n",
     ""),
]
