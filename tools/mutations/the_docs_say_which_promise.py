"""ADR-0049 slice 6, proven by breaking it — the docs lead with the door that needs nothing.

THREE CLAIMS:

  1. **The prompts and the prose agree**, because the guard reads the prompts rather than a copy
     of them: the two `init` defaults ARE the kind a bare path registers as.
  2. **A reader meets a card before they meet a vendor** — the first registration in both entry
     documents is a path, and Docker is asked for by the door that uses it.
  3. **The compose file says whose credentials those are**, so somebody arriving from the
     one-machine page is not sent to fetch a forge token nothing will read.

A DOCS GUARD THAT ASSERTS ITS OWN LITERAL proves nothing, which is why the rows below cut the CODE
as often as the prose: a flip in `deployment.py` or in `doors.py` must reach this guard.

The guard under test is `tests/test_the_docs_say_which_promise.py`.
"""

TEST = "tests/test_the_docs_say_which_promise.py"

README = "README.md"
DEP = "openfactory/onboarding/deployment.py"
DOORS = "openfactory/doors.py"
ENV = ".env.compose.example"

MUTATIONS = [
    # ── 1. the prompts and the prose ───────────────────────────────────────────────────────────
    ("the forge prompt sends a person to a vendor again, and the docs stop matching the door",
     DEP,
     '             "Any other answer decides which credential this file asks you for", _forges, '
     '"local"),',
     '             "Any other answer decides which credential this file asks you for", _forges, '
     '"github"),', TEST),

    ("the door stops registering a bare path as itself, so the quickstart's first command lies",
     DOORS,
     '    return "github" if (repo or "").strip() else "local"',
     '    return "github"', TEST),

    # ── 2. what a reader meets first ───────────────────────────────────────────────────────────
    ("the quickstart registers a github.com URL again, so an account comes before a card", README,
     "openfactory project init myapp ~/code/myapp   # a path registers as itself — no owner, no board",
     "openfactory project init myapp https://github.com/<owner>/myapp.git", TEST),

    ("Docker is the first word of the prerequisites again, for readers who never containerise",
     README,
     "Prerequisites: git, Python 3.12+, and a coding agent on your PATH already signed in",
     "Prerequisites: Docker, git, Python 3.12+, and a coding agent on your PATH already signed in",
     TEST),

    ("the hosted door comes first, which is the order this slice exists to swap", README,
     "## Quickstart — one machine", "## Quickstart — with Docker", TEST),

    ("the one-machine page loses its link from the front page", README,
     "| [docs/setup/one-machine.md](docs/setup/one-machine.md) | one repository, one terminal, "
     "one credential — the door that needs no account anywhere |\n", "", TEST),

    # ── 3. whose credentials ───────────────────────────────────────────────────────────────────
    ("the compose file stops saying whose two credentials those are", ENV,
     "# THIS FILE IS THE HOSTED DOOR'S. A deployment whose code and tickets live on THIS MACHINE — "
     "the\n# `local` answers `openfactory init` now defaults to — needs neither of those two: its "
     "forge is the\n# operator's own repository and its board is a file beside the registry, so the "
     "only credential\n# left is the harness's own login. It runs no compose stack either; see "
     "docs/setup/one-machine.md.", "", TEST),
]
