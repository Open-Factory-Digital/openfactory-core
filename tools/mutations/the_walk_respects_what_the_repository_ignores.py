"""The walk respects what the repository ignores — the cuts that put the browser back.

ROW 1 IS THE ANSWER FROM GIT DISCARDED: the walk sees the disk again.
ROW 2 IS THE DIRECTORIES NOT PRUNED (the files are filtered one by one, so the browser's 288
binaries are read and dropped instead of never entered — same result, unbounded cost — and a
guard that only counts files cannot see it; the pass-through guard can).
ROW 3 IS THE FILES NOT FILTERED: `.env` is read and its password scanned.
ROW 4 IS THE SURVEY FORGETTING TO RECORD the ignored set — "not inventoried" becomes a silence.
ROW 5 IS A PRIVATE KEY BY NAME GRADED LOW.
ROW 6 IS A LOCKFILE'S PACKAGE NAME GRADED HIGH AGAIN.
"""

TEST = "tests/test_the_walk_respects_what_the_repository_ignores.py"

MUTATIONS = [
    ("git's answer is discarded — the walk sees the disk again",
     "openfactory/knowledge/generator.py",
     "    if ignored is None:\n        ignored = ignored_by_git(repo)",
     "    if ignored is None:\n        ignored = frozenset()"),

    ("ignored directories are entered and only their files dropped",
     "openfactory/knowledge/generator.py",
     '                       if not _is_skipped_name(d) and f"{prefix}{d}/" not in ignored]',
     '                       if not _is_skipped_name(d)]'),

    ("ignored files are yielded — `.env` is read and scanned",
     "openfactory/knowledge/generator.py",
     '        yield rel_dir, [f for f in filenames if f"{prefix}{f}" not in ignored]',
     '        yield rel_dir, filenames'),

    ("the survey does not record what it did not walk",
     "openfactory/onboarding/context.py",
     "                  unreadable=sorted(set(unreadable)), ignored=sorted(ignored),",
     "                  unreadable=sorted(set(unreadable)), ignored=[],"),

    ("a private key by name is graded low",
     "openfactory/knowledge/inventory.py",
     '            risks.append(SecretRisk(path=rel, key="private key material", line=0,\n'
     '                                    severity="high", kind=kind))',
     '            risks.append(SecretRisk(path=rel, key="private key material", line=0,\n'
     '                                    severity="low", kind=kind))'),

    ("a lockfile's package name is graded high again",
     "openfactory/knowledge/inventory.py",
     '        if kind in {"test", "documentation", "generated", "vendored"}:',
     '        if kind in {"test", "documentation"}:'),
]
