"""A version tag on the status page says whose history it belongs to — always, and the rule does
not consult the checkout (2026-08-26: it read `git tag -l`, which is full on a laptop and empty
under `actions/checkout`'s depth-1 fetch, so the rule was unmeasurable here and red there).

Point-in-time proof; anchors rot as code moves and fail loudly on rerun.
"""

TEST = "tests/test_the_operator_path_names_what_the_code_mints.py"

MUTATIONS = [
    ("the page cites the tag with no owner beside it",
     "docs/STATUS.md",
     "`v1.1.0` tag of `openfactory`.",
     "`v1.1.0` tag."),
    ("the owner is read as a literal instead of from the status line",
     "tests/test_the_operator_path_names_what_the_code_mints.py",
     '    attribution = f"of `{owner.group(1)}`"',
     '    attribution = "of `"'),
    ("the rule stops looking for the attribution at all",
     "tests/test_the_operator_path_names_what_the_code_mints.py",
     "            if attribution not in flat[max(0, flat.index(f\"`{tag}`\") - 200):",
     "            if False and attribution not in flat[max(0, flat.index(f\"`{tag}`\") - 200):"),
    ("the rule reports every citation as unattributed",
     "tests/test_the_operator_path_names_what_the_code_mints.py",
     "    return [tag for tag in sorted(cited)",
     "    return [tag for tag in sorted(cited)] or [tag for tag in sorted(cited)"),
    ("the status line stops naming whose history its commit is",
     "docs/STATUS.md",
     "main at `8cbf251` of `openfactory`, the source tree this page is",
     "main at `8cbf251`, the source tree this page is"),
]
