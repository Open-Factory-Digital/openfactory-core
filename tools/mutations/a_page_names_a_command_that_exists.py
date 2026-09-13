"""A command a page tells you to TYPE is a command this CLI has — proven by breaking it.

Found by walking `docs/setup/one-machine.md` as written (2026-09-11): it told the reader
`openfactory panel`, and typer answered *No such command*. The page whose whole promise is that a
stranger can follow it, at the step where they first look at the board.

THREE CLAIMS:

  1. **The pages name real commands**, checked against the app rather than a list in the guard.
  2. **Two levels deep** — a group's subcommand is checked too, so `box proof` cannot pass for
     `box prove`.
  3. **The one-machine page carries the step that gates pickup**, and carries it before the
     command it gates.

The guard under test is `tests/test_the_docs_do_not_drift.py`.
"""

TEST = "tests/test_the_docs_do_not_drift.py"

DOOR = "docs/setup/one-machine.md"
ONBOARD = "docs/ONBOARDING.md"

MUTATIONS = [
    ("the one-machine page sends its reader to a command that does not exist", DOOR,
     "openfactory serve        # http://localhost:8787",
     "openfactory panel        # http://localhost:8787", TEST),

    ("a group's SUBcommand is misspelled, which the top-level check alone would pass", ONBOARD,
     "openfactory box prove myapp --repo <owner>/web",
     "openfactory box proof myapp --repo <owner>/web", TEST),

    ("the one-machine page drops the proof, and its reader meets `held` instead of a card", DOOR,
     "openfactory box prove myapp\n",
     "openfactory doctor myapp   # again, why not\n", TEST),

    ("the page reaches `poll` before the proof, so the advice arrives behind the failure", DOOR,
     "```bash\nopenfactory doctor myapp\n```\n",
     "```bash\nopenfactory poll myapp\n```\n", TEST),
]
