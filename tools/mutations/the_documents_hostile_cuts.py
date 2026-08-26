"""The cuts a hostile reviewer would write against package 4's own guards.

The other plan beside this one breaks the thing each guard protects and requires red — the
ordinary proof. This one is the round's harder instruction: not the cut that restores the old
text, but the one that KEEPS THE VOCABULARY AND INVERTS THE MEANING, or reaches the same defect
through a different spelling, or moves the claim into a syntax the scan does not read.

Every row here was written to make a guard look silly. The ones that came back green were
findings about the guard and were closed before this plan was committed; what remains is the
record of the attack, so the next reviewer starts from a higher wall than an empty one.

Where a cut is best caught by a guard somebody else already wrote, the row says so with its own
test target — the fifth element — rather than pretending this file is the only wall.
"""

TEST = "tests/test_the_documents_describe_the_product_this_tree_is.py"

MUTATIONS = [
    # ── against the knowledge-layer polarity sweep ─────────────────────────────────────────────
    ("keeps `defaults to true` and denies it two paragraphs later, in words the page never used",
     "docs/knowledge-layer.md",
     "", "\n\nIn practice the map is switched off unless a project has asked for it.\n"),

    ("moves the denial into a table row instead of a sentence",
     "docs/knowledge-layer.md",
     "", "\n\n| flag | state |\n|---|---|\n| `knowledge_map` | off by default |\n"),

    ("deletes the rendered claim entirely, so the page states no default at all — silence is not "
     "compliance",
     "docs/knowledge-layer.md",
     "**`knowledge_map` defaults to `true`**",
     "the flag is there for projects that want to think about it"),

    # ── against the citation scans ─────────────────────────────────────────────────────────────
    ("cites the absent registry file without backticks, so a code-citation scan cannot see it",
     "docs/agents.md",
     "| who may authorise | the registry → `product.admins` |",
     "| who may authorise | the deploy/registry.yaml file, product.admins |"),

    ("keeps the citation and swaps the symbol for one the module imports rather than defines",
     "docs/agents.md",
     "`openfactory/adapters/reviewer/harness.py` → `build_review_prompt` |\n| **tech lead**",
     "`openfactory/adapters/reviewer/harness.py` → `ReviewInput` |\n| **tech lead**"),

    # ── against the harness list ───────────────────────────────────────────────────────────────
    ("splits the list away from the table's name, leaving the anchor paragraph with no kinds",
     "docs/agents.md",
     "module: `claude_code`, `codex`, `kimi` and `opencode`. The last",
     "module.\n\nThe kinds are `claude_code`, `codex`, `kimi` and `opencode`. The last"),

    ("keeps four backticked kinds and makes one of them a harness nothing ships",
     "docs/agents.md",
     "`claude_code`, `codex`, `kimi` and `opencode`",
     "`claude_code`, `codex`, `kimi` and `cursor`"),

    # ── against the board-fallback condition ───────────────────────────────────────────────────
    ("keeps `moved` in the branch's test and makes the branch always true anyway — the AST guard "
     "sees its vocabulary; the behaviour twin next door is what has to catch this",
     "openfactory/adapters/tracker/github.py",
     "        if self.board is None or not moved:",
     "        if self.board is None or moved is not None:",
     "tests/test_tracker_board_writes.py"),

    # ── against the compose scan ───────────────────────────────────────────────────────────────
    ("pins the vendor variable in Compose's OTHER environment syntax, which a mapping-only scan "
     "reads as a value rather than a name",
     "docker-compose.yml",
     "    environment:\n      TEMPORAL_ADDRESS: temporal:7233\n      TEMPORAL_NAMESPACE: default\n"
     "      OPENFACTORY_METRICS_SINK: sqlite",
     "    environment:\n      - TEMPORAL_ADDRESS=temporal:7233\n      - TEMPORAL_NAMESPACE=default\n"
     "      - JIRA_API_TOKEN=\n      - OPENFACTORY_METRICS_SINK=sqlite"),

    # ── against the operations future-work sweep ───────────────────────────────────────────────
    ("defers the shipped promotion chain in words the page never used",
     "docs/operations.md",
     "Beyond the PR (D-12 — **built**)",
     "Beyond the PR (D-12 — a design we intend to ship)"),

    # ── against the retention table ────────────────────────────────────────────────────────────
    ("keeps both numbers and swaps which repository each belongs to",
     "docs/rotation-and-retention.md",
     "| `<prefix>-python` — the box image | **20** |",
     "| `<prefix>-python` — the box image | **30** |"),

    # ── against the quickstart scan ────────────────────────────────────────────────────────────
    ("keeps a `pip install .` line but in a SECOND block, leaving the copied one root-relative",
     "addons/openfactory-aws/README.md",
     "pip install .                        # from THIS directory, where this README is\n",
     ""),

    # ── against the readable twins ─────────────────────────────────────────────────────────────
    ("keeps both forms competing and quietly halves the cap, so the diagnosis is cut anyway",
     "openfactory/runtime/temporal/worker.py",
     "def _readable(exc: BaseException, cap: int = 200) -> str:",
     "def _readable(exc: BaseException, cap: int = 50) -> str:"),

    # ── against the lesson/record agreement ────────────────────────────────────────────────────
    ("names a pool variable nobody reads, spelled as if it were current",
     "docs/engineering-lessons.md",
     "today `OPENFACTORY_AGENT_TOKENS`",
     "today `OPENFACTORY_CLAUDE_AGENT_TOKENS`"),
]
