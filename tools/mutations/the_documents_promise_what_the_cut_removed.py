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
    # RETIRED 2026-09-07: the guard this row aimed at was retired ON PURPOSE, and says so. Until
    # 2026-08-26 `test_the_policy_points_at_the_function_it_describes` held SECURITY.md to the
    # platform's sentence that one spelling is enough; that premise was measured false
    # (`OPENFACTORY_TRACKER_TOKEN` was a served third spelling), the document was rewritten around
    # the guarantee that does hold, and — in its own words — "the sentence check that stood here
    # was a phrase". The document's claims are held name for name by
    # `tests/test_the_environment_carries_the_products_name.py` now. So this cut edits prose no
    # guard reads, and the row was re-pinned onto the new wording and run for the first time since
    # the refactor on 2026-09-07, where it survived. Its sibling below — the same promise made by
    # the CODE — is guarded and stays; that is the half that was ever a property.

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
    # re-targeted 2026-09-07: the reference deployment's incident page MOVED into the package
    # rather than being excluded (docs/STATUS.md) — an `addons/` path, so the runner and the
    # guard skip both rows here, and `openfactory-aws` is the tree they run in
    ("an operator page drops the add-on banner and keeps naming the vendor",
     "addons/openfactory-aws/docs/runbook.md",
     "> **This page drives `infra/`, which is not in this tree.** That directory and the deployment it\n"
     "> stands up ship with the `openfactory-aws` **add-on package** — one cloud realisation, never the\n"
     "> platform ([STATUS.md](STATUS.md) lists what leaves with it). Every `infra/…` path below is a\n"
     "> path inside that package's checkout; a deployment on your own machines has no such directory,\n"
     "> and [`operations.md`](operations.md) is its page.\n\n",
     "",
     "tests/test_the_docs_name_no_vendor_as_the_core.py"),

    # ── (e) the retired acronym in the operator path ────────────────────────────────────────
    ("the runbook sends a 9pm incident to the retired namespace and workflow",
     "addons/openfactory-aws/docs/runbook.md",
     "1. **Temporal Cloud UI** → your namespace (`TEMPORAL_NAMESPACE`, the one named above) → workflow\n"
     "   `openfactory-{project}-{issue}`, the id every entry point mints",
     "1. **Temporal Cloud UI** → namespace `sdlc` → workflow `sdlc-{project}-{issue}`, the id\n"
     "   every entry point mints",
     "tests/test_the_operator_path_names_what_the_code_mints.py"),

    ("a rotation page names the deployment's repositories by the retired prefix",
     "docs/rotation-and-retention.md",
     # re-pinned 2026-09-07: the page names the one file the policies live in now
     "- the add-on package's `infra/terraform/alerting.tf` — both lifecycle policies and their counts.",
     "- the add-on package's `infra/terraform/alerting.tf` — the `sdlc-*` repos' lifecycle policies.",
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
    # RETIRED 2026-09-07: the guard stopped asking whether the tag EXISTS, and says why. `git tag
    # -l` made it read the machine twice over — a developer's clone holds every tag, so the
    # attribution branch never ran; CI fetches depth 1 with no tags, so every citation needed one
    # and the suite went red on a page nobody had touched. The rule is unconditional now: say
    # whose history it is, always. A different tag number with `of `openfactory`` still beside it
    # is a citation that rule is content with, so this cut cannot go red — which is what running
    # it for the first time since the refactor showed. The half of the claim that IS guarded is
    # the attribution, and `a_tag_says_whose_history_it_is.py` cuts exactly that.

    ("the licensing page claims the copyright line lives where grep finds nothing",
     "docs/core/04-business-and-licensing.md",
     "rather than left as boilerplate) and in `NOTICE`. Those are",
     "rather than left as boilerplate), in `NOTICE`, and in `pyproject.toml`. Those are",
     "tests/test_the_operator_path_names_what_the_code_mints.py"),
]
