"""Work package 3 of the pre-launch audit: the documents promised what the cut removed.

Every row below puts back, verbatim, a sentence or a setting that was in the tree on 2026-08-26,
and requires the guard written for it to go red. The five defects, in the audit's order:

  (a) `SECURITY.md`'s credential-reach bullet promised the workspace scrub covered "both current
      and legacy spellings of every name". A retired-prefix twin survives `_scrubbed_env` —
      measured — and the deny lists refuse a second spelling on purpose.
  (b) the one remedy a refusal handed an operator was `pip install openfactory-slack`, a name no
      index serves, while `docs/STATUS.md` called the packages private.
  (c) six reader-facing surfaces still configured a chat channel the core no longer has: a
      registry example a reader copies, the template that documents its keys, two environment
      templates and the compose file.
  (e) the operator path still spelled the platform's retired acronym — the workflow a 9pm
      incident is sent to, the resources a rotation names, the identity a bot commits under.
  (f) `docs/STATUS.md` cited a tag a fresh-history clone does not carry, and `docs/core/04` said
      the copyright line lives in a file where `grep` finds nothing.
"""

TEST = "tests/test_the_examples_a_reader_copies_load_on_the_core.py"

MUTATIONS = [
    # ── (a) the false security guarantee ────────────────────────────────────────────────────
    ("SECURITY.md promises the scrub covers the legacy spelling too", "SECURITY.md",
     """(`_scrubbed_env`). The deny lists name the ONE
  spelling this platform reads for each secret, and that is the whole guarantee: **a name they
  do not list is not removed.** It is enough only because no second spelling exists to hold the
  same token — the old spelling of this platform's namespace is one *nothing serves and no
  add-on may take up* (`environ.reserved`, which refuses it to any add-on for that reason). The
  day a second spelling is served, the same secret sits under both and this bullet is false
  until that name is on the list. Anything""",
     """(`_scrubbed_env` — both current and legacy
  spellings of every name). Anything""",
     "tests/test_the_security_policy_promises_what_the_scrub_does.py"),

    ("the scrub grows the second spelling the document used to promise",
     "openfactory/adapters/sandbox/worktree.py",
     '_AGENT_CRED_VARS = ("OPENFACTORY_AGENT_TOKENS",)',
     '_AGENT_CRED_VARS = ("OPENFACTORY_AGENT_TOKENS", "SDLC_AGENT_TOKENS")',
     "tests/test_the_security_policy_promises_what_the_scrub_does.py"),

    # ── (b) the remedy that cannot be followed ──────────────────────────────────────────────
    ("the refusal hands the operator a bare-name index install again", "openfactory/plugins.py",
     'return (f" — {kind!r} ships in the add-on package {package}, which is on no public index: "\n'
     '            f"install the wheel your deployment carries, or any package declaring `{axis}.{kind}`")',
     'return f" — {kind!r} ships in the add-on package {package}: `pip install {package}`"',
     "tests/test_the_remedy_a_refusal_hands_you_can_be_followed.py"),

    ("a document repeats that command", "docs/README.md",
     "**Neither is on a public index**: they are built as wheels from the private tree and installed",
     "Install either with `pip install openfactory-slack`: they are built as wheels and installed",
     "tests/test_the_remedy_a_refusal_hands_you_can_be_followed.py"),

    ("the refusal stops naming the entry point a stranger could declare instead",
     "openfactory/plugins.py",
     'f"install the wheel your deployment carries, or any package declaring `{axis}.{kind}`")',
     'f"install the wheel your deployment carries")',
     "tests/test_the_remedy_a_refusal_hands_you_can_be_followed.py"),

    ("the worker cuts the remedy out of the line an operator reads",
     "openfactory/runtime/temporal/worker.py",
     "kind, _readable(exc))",
     "kind, str(exc)[:200])",
     "tests/test_the_chat_is_a_directory_delete.py"),

    # ── (c) the chat configuration a reader copies ──────────────────────────────────────────
    ("the registry example carries a chat coordinate again", "docs/reference/configuration.md",
     "    harness: codex                            # or per role, below\n",
     "    harness: codex                            # or per role, below\n"
     "    channel_id: C0XXXXXXXXX                   # Slack channel for this project\n"),

    ("the registry template documents the coordinate under its OLD spelling",
     "deploy/registry.yaml.example",
     "# THE CHANNEL: no key here, and that is the working configuration.",
     "#   slack_channel: C0XXXXXXXXX        # the channel the tech-lead narrates in\n"
     "# THE CHANNEL: no key here, and that is the working configuration."),

    ("the compose file forwards a package's variables into the worker", "docker-compose.yml",
     "      OPENFACTORY_BOT_NAME: ${OPENFACTORY_BOT_NAME:-OpenFactory Bot}",
     "      SLACK_BOT_TOKEN: ${SLACK_BOT_TOKEN:-}\n"
     "      SLACK_APP_TOKEN: ${SLACK_APP_TOKEN:-}\n"
     "      OPENFACTORY_BOT_NAME: ${OPENFACTORY_BOT_NAME:-OpenFactory Bot}"),

    ("the compose template sets them as live rows", ".env.compose.example",
     "# Add those rows to this file once the package is installed: every row of it reaches the worker,",
     "SLACK_BOT_TOKEN=\nSLACK_APP_TOKEN=\n"
     "# Add those rows to this file once the package is installed: every row of it reaches the worker,"),

    # ── (d) the exemption list is held to its framing ───────────────────────────────────────
    ("an operator page drops the add-on banner and keeps naming the vendor", "docs/runbook.md",
     "> **This page drives `infra/`, which is not in this tree.** That directory and the deployment it\n"
     "> stands up ship with the `openfactory-aws` **add-on package** — one cloud realisation, never the\n"
     "> platform ([STATUS.md](STATUS.md) lists what leaves with it). Every `infra/…` path below is a\n"
     "> path inside that package's checkout; a deployment on your own machines has no such directory,\n"
     "> and [`operations.md`](operations.md) is its page.\n\n",
     "",
     "tests/test_the_docs_name_no_vendor_as_the_core.py"),

    # ── (e) the retired acronym in the operator path ────────────────────────────────────────
    ("the runbook sends a 9pm incident to the retired namespace and workflow", "docs/runbook.md",
     "1. **Temporal Cloud UI** → your namespace (`TEMPORAL_NAMESPACE`, the one named above) → workflow\n"
     "   `openfactory-{project}-{issue}`, the id every entry point mints",
     "1. **Temporal Cloud UI** → namespace `sdlc` → workflow `sdlc-{project}-{issue}`, the id\n"
     "   every entry point mints",
     "tests/test_the_operator_path_names_what_the_code_mints.py"),

    ("a rotation page names the deployment's repositories by the retired prefix",
     "docs/rotation-and-retention.md",
     "- the add-on package's `infra/terraform/*` — the `<prefix>-worker` and `<prefix>-python` repos'",
     "- the add-on package's `infra/terraform/*` — the `sdlc-*` repos'",
     "tests/test_the_operator_path_names_what_the_code_mints.py"),

    ("the bot identity a page states drifts from what the code defaults to", "docs/operations.md",
     '  to "OpenFactory Bot" / `openfactory-bot@localhost` (`credentials.bot_identity`).',
     '  to "Factory Bot" / `openfactory-bot@localhost` (`credentials.bot_identity`).',
     "tests/test_the_operator_path_names_what_the_code_mints.py"),

    ("the page hands the reader an export stamping the abandoned acronym", "docs/operations.md",
     '   export OPENFACTORY_BOT_NAME="OpenFactory Bot"',
     '   export OPENFACTORY_BOT_NAME="SDLC Bot"',
     "tests/test_the_operator_path_names_what_the_code_mints.py"),

    # ── (f) the small false citations ───────────────────────────────────────────────────────
    ("the status page cites a tag no clone of this repository carries", "docs/STATUS.md",
     "source tree's `v1.1.0` tag (named the way line 6 names the commit: a tag of the history this\ntree was cut from, which a fresh-history clone does not carry)",
     "`v9.9.9` tag",
     "tests/test_the_operator_path_names_what_the_code_mints.py"),

    ("the licensing page claims the copyright line lives where grep finds nothing",
     "docs/core/04-business-and-licensing.md",
     "rather than left as boilerplate) and in `NOTICE`. Those are",
     "rather than left as boilerplate), in `NOTICE`, and in `pyproject.toml`. Those are",
     "tests/test_the_operator_path_names_what_the_code_mints.py"),
]
