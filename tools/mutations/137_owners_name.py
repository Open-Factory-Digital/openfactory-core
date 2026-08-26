"""#137: OpenFactory carries nobody's company.

The first cuts put an owner's name back into the tree, one per road it actually arrived by — a
fixture value, a comment, a board URL. The rest attack the GUARD: a name list is the shape that
goes green because it missed, and a tree-wide scan is the shape that goes green because it stopped
reading the tree.

SYNTHETIC NAMES ONLY (2026-08-25). This plan used to plant the maintainer's real login, and was
one of the three tracked files that carried it. The shapes are now the synthetic ones in
`tests/identity_forbidden.py`; a plan that plants the REAL names lives in the gitignored
`tools/mutations/local/` and is run by path on a machine that has the real list.
"""

TEST = "tests/test_the_product_carries_no_owners_name.py"
GUARD = TEST
SHAPES = "tests/identity_forbidden.py"
BOARD = "openfactory/adapters/tracker/github_project.py"
FIXTURE = "tests/test_a_personal_boards_columns_can_be_read.py"

MUTATIONS = [
    ("a maintainer's login comes back in product code", BOARD,
     "#: `solo-dev` could not be read back, while creation succeeded because that path asks "
     "our own",
     "#: `example-maintainer` could not be read back, while creation succeeded because that path "
     "asks our own"),

    ("…and in a test fixture, which is how twenty-two of them arrived", FIXTURE,
     'board = gp.GitHubProjectBoard(owner="solo-dev", number="1", token="tok")',
     'board = gp.GitHubProjectBoard(owner="example-maintainer", number="1", token="tok")'),

    ("the guard forgets the organisation, keeping only the person", SHAPES,
     '    ("exampleco", "the organisation that builds the product"),\n',
     ''),

    ("the guard forgets the person, keeping only the organisation", SHAPES,
     '    ("example-maintainer", "a maintainer\'s login"),\n',
     ''),

    ("the guard stops reading the tree and passes over nothing", GUARD,
     '    return [p for p in out.stdout.split("\\0") if p]',
     '    return [p for p in out.stdout.split("\\0") if p][:1]'),

    ("the package stops naming itself, so 'no owner' is met by having no identity at all",
     "pyproject.toml", 'name = "openfactory"', 'name = "sdlc-platform"'),

    ("the real list REPLACES the synthetic shapes instead of joining them", SHAPES,
     "    for token, what in [*SYNTHETIC_FORBID, *_real(root)[0]]:",
     "    for token, what in [*(_real(root)[0] or SYNTHETIC_FORBID)]:"),

    ("the real list is never read — a machine that has it scans for the shapes only", SHAPES,
     "    if not path.is_file():\n        return [], []",
     "    if not path.is_file() or True:\n        return [], []"),

    ("the guard matches case-sensitively, so `ExampleClient` in a docstring walks past", SHAPES,
     '    return re.compile("|".join(re.escape(token) for token, _ in entries), re.IGNORECASE)',
     '    return re.compile("|".join(re.escape(token) for token, _ in entries))'),

    ("the real entries handed to the exempt files include the shapes they plant", SHAPES,
     "    return [(token, what) for token, what in forbidden(root) if token not in synthetic]",
     "    return [(token, what) for token, what in forbidden(root)]"),
]
