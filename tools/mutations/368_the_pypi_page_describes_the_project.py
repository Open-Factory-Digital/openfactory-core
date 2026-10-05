"""#368 — the page PyPI shows describes the project, and every promise on it can be followed.

Run:  .venv/bin/python tools/mutate.py tools/mutations/368_the_pypi_page_describes_the_project.py

THE CLAIMS, one block of rows each:

  1. `pyproject.toml` declares a long description, as markdown, in its own file — not the README,
     whose relative links are dead on the index.
  2. Every link and image on the page is absolute, and every link to a file of this repository
     names a file the tree has — the page's links and `project.urls` alike.
  3. Every `openfactory <command>` the page hands a reader is a command this CLI has, at both
     levels, wherever it sits in a command line; and the one-machine door keeps its four steps.
  4. Every `openfactory[<extra>]` on the page is an extra the package declares.
  5. The page's table of coding agents lists every harness the registry ships.
  6. The sidebar offers the documentation, the changelog and the security policy, and the
     classifiers claim the console and no system the package cannot import on.
  7. The BUILT wheel's METADATA carries the page as markdown, body and all.
  8. The bare-name rule lets the page the index shows name the core — and nothing else changes.

NOT HERE, AND WHY: the rendering guard (`test_the_page_renders_the_way_the_index_renders_it`)
skips by name where `readme_renderer` is not installed, and it was not installed where this plan
was written — a row aimed at it could only print GREEN over a skip. It needs `readme-renderer[md]`
in the environment that runs it.

THE WHEEL ROWS NEED A BUILD BACKEND. `test_the_wheel_ships_what_the_platform_needs.py` builds
without isolation when the interpreter's own setuptools meets the declared floor, and otherwise
fetches one — which needs the network and skips without it. Run offline, this plan's wheel rows
were proved with a local setuptools 80.9 on `PYTHONPATH` and `PIP_NO_INDEX=1`.
"""

TEST = "tests/test_the_pypi_page_describes_the_project.py"

WHEEL = "tests/test_the_wheel_ships_what_the_platform_needs.py"
REMEDY = "tests/test_the_remedy_a_refusal_hands_you_can_be_followed.py"

PAGE = "docs/pypi.md"
PYPROJECT = "pyproject.toml"

_DECLARATION = 'readme = { file = "docs/pypi.md", content-type = "text/markdown" }\n'

MUTATIONS = [
    # ── 1. the declaration ──────────────────────────────────────────────────────────────────────
    ("the package declares no long description again — the 0.4.0 page", PYPROJECT,
     _DECLARATION, ""),

    ("the page is declared as plain text", PYPROJECT,
     'content-type = "text/markdown" }', 'content-type = "text/plain" }'),

    ("the README is pointed at instead of the page written for the index", PYPROJECT,
     'file = "docs/pypi.md"', 'file = "README.md"'),

    # ── 2. every link absolute, and every linked file present ───────────────────────────────────
    ("a relative link comes back on the page", PAGE,
     "[What works today](https://github.com/Open-Factory-Digital/openfactory-core/blob/main/docs/STATUS.md)",
     "[What works today](docs/STATUS.md)"),

    ("an anchor-only link, which lands nowhere on the index", PAGE,
     "the coding agents, below,", "[the coding agents](#the-coding-agents), below,"),

    ("a relative image", PAGE, "", "\n![OpenFactory](docs/logo.png)\n"),

    ("a link names a file the tree does not have", PAGE,
     "blob/main/docs/reference/cli.md", "blob/main/docs/reference/commands.md"),

    # ── 3. every command one this CLI has ───────────────────────────────────────────────────────
    ("the page tells a reader to type a command that does not exist", PAGE,
     "openfactory up                                # the panel",
     "openfactory start                             # the panel"),

    ("a real group with a subcommand it does not have", PAGE,
     "openfactory box prove myapp                   # nothing",
     "openfactory box check myapp                   # nothing"),

    ("a wrong subcommand in the middle of a command line, after `exec worker`", PAGE,
     "  openfactory project init myapp https://github.com/<owner>/myapp.git",
     "  openfactory project create myapp https://github.com/<owner>/myapp.git"),

    ("the one-machine door loses the step that starts the factory", PAGE,
     "openfactory up                                # the panel, the worker and the durable "
     "engine\n",
     ""),

    # ── 4. every extra declared ─────────────────────────────────────────────────────────────────
    ("the page names an extra the package does not declare", PAGE,
     "| `openfactory[embed]` |", "| `openfactory[search]` |"),

    ("the package renames an extra and the page still names the old one", PYPROJECT,
     'embed = [\n    "model2vec==0.9.0",\n]', 'semantic = [\n    "model2vec==0.9.0",\n]'),

    # ── 5. every harness the registry ships ─────────────────────────────────────────────────────
    ("the agent that does not run drops out of the table instead of saying so", PAGE,
     "| Kimi Code | `kimi` |", "| Kimi Code | kimi |"),

    # ── 6. the metadata beside the page ─────────────────────────────────────────────────────────
    ("the sidebar loses the changelog", PYPROJECT,
     'Changelog = "https://github.com/Open-Factory-Digital/openfactory-core/releases", ', ""),

    ("the security policy link names a file the tree does not have", PYPROJECT,
     'Security = "https://github.com/Open-Factory-Digital/openfactory-core/blob/main/SECURITY.md"',
     'Security = "https://github.com/Open-Factory-Digital/openfactory-core/blob/main/docs/SECURITY.md"'),

    ("the classifiers claim any system while the registry imports fcntl", PYPROJECT,
     '"Operating System :: POSIX :: Linux",', '"Operating System :: OS Independent",'),

    ("the console environment is no longer declared", PYPROJECT,
     '    "Environment :: Console",\n', ""),

    # ── 7. the built wheel carries it ───────────────────────────────────────────────────────────
    ("the wheel carries no long description", PYPROJECT, _DECLARATION, "", WHEEL),

    ("the wheel's description is declared as plain text", PYPROJECT,
     'content-type = "text/markdown" }', 'content-type = "text/plain" }', WHEEL),

    # THE ONE CUT THAT LEAVES THE CONTENT TYPE STANDING. A build context without the page — the
    # shape of every `COPY pyproject.toml README.md LICENSE NOTICE` — builds green: setuptools
    # warns, writes `text/markdown` and ships an EMPTY body. Cut in the guard's own build copy,
    # because that copy IS the build context; only the body comparison can see it.
    ("the build context lacks the page, so the wheel ships an empty description", WHEEL,
     '"README.md", *_the_declared_description()):', '"README.md"):', WHEEL),

    # ── 8. the one exemption in the bare-name rule, and its two edges ──────────────────────────
    ("the page the index shows may not show the install the index serves", REMEDY,
     "    if rel and rel == _the_page_the_index_shows():", "    if False:", REMEDY),

    ("the exemption covers every file, so the README may name the core again", REMEDY,
     "    if rel and rel == _the_page_the_index_shows():", "    if rel:", REMEDY),

    ("the exemption relaxes the add-on packages as well", REMEDY,
     "        return unpublished - {core}", "        return set()", REMEDY),
]
