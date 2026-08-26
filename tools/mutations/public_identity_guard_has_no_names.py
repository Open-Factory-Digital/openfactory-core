"""Publication compliance, proven by breaking it — the guards a public repository rests on.

One plan for the package that made the tree publishable (2026-08-25): the identity guards that
stopped naming what they forbid, the tenant coordinates that became synthetic, the card ids that
left the surfaces a stranger reads, the extensibility document that names the group that exists,
the ledger that now checks its vendor side both ways, and the build floor that can build the
package. Every cut is one of the defects the review measured, put back; every guard has to see it.

SYNTHETIC NAMES ONLY. A cut that plants a REAL identity lives in the gitignored
`tools/mutations/local/` and is run by path on a machine that has `tests/.identity-forbidden.txt`.
"""

TEST = "tests/test_the_product_carries_no_owners_name.py"

OWNERS = "tests/test_the_product_carries_no_owners_name.py"
PAST = "tests/test_the_product_carries_no_ones_past.py"
SHAPES = "tests/identity_forbidden.py"
CARDS = "tests/test_no_card_id_reaches_a_stranger.py"
LEDGER = "tests/test_the_core_addon_ledger.py"
DOCGUARD = "tests/test_the_extensibility_doc_names_the_real_group.py"
WHEEL = "tests/test_the_wheel_ships_what_the_platform_needs.py"
DOC = "docs/core/07-extensibility.md"

MUTATIONS = [
    # ── identities: the shapes are scanned everywhere, on every machine ────────────────────────
    ("a tenant's account id and App name are pasted into the README", "README.md",
     "# OpenFactory",
     "# OpenFactory\n\nDeployed in account 123456789012 as the ExampleCoBot App.", PAST),

    ("…and the owner guard sees the same line through git ls-files", "README.md",
     "# OpenFactory",
     "# OpenFactory\n\nDeployed in account 123456789012 as the ExampleCoBot App.", OWNERS),

    # RE-AIMED 2026-08-26: the walk stopped being `rglob` and became a `git ls-files` pair when
    # "your machine is not the reference" landed, so the old anchor matched nothing and this cut
    # had silently stopped applying. The defect is the same one — a scanner that walks an empty
    # tree reports every page clean.
    ("the prose scanner stops walking the tree", PAST,
     '        out.extend(p for p in listed.stdout.split("\\0") if p)',
     '        out.extend([])', PAST),

    ("the coordinate list loses the App-name shape", SHAPES,
     '    ("ExampleCoBot", "the name of a live GitHub App"),\n', '', PAST),

    ("a document joins the guards' exemption set, so whatever it names is never scanned",
     SHAPES,
     '    "tests/test_the_product_carries_no_ones_past.py",\n',
     '    "tests/test_the_product_carries_no_ones_past.py",\n    "README.md",\n', OWNERS),

    ("a guard that plants nothing joins the exemption set — a hole waiting to be used", SHAPES,
     '    "tests/test_the_product_carries_no_ones_past.py",\n',
     '    "tests/test_the_product_carries_no_ones_past.py",\n'
     '    "tests/test_the_wheel_ships_what_the_platform_needs.py",\n', OWNERS),

    # ── the exemption is per token, not per file (the reviewer's surviving cut) ────────────────
    ("an exempt file is skipped outright again by the tracked-tree scan", OWNERS,
     "        rx = refused.in_exempt if rel in ALLOWED else refused.everywhere",
     "        rx = None if rel in ALLOWED else refused.everywhere", OWNERS),

    ("an exempt file is skipped outright again by the prose scan", PAST,
     "        rx = refused.in_exempt if rel in _EXEMPT else refused.everywhere",
     "        rx = None if rel in _EXEMPT else refused.everywhere", PAST),

    ("the exempt files are read with the synthetic shapes too, so every guard fires on itself",
     SHAPES,
     "    return Refused(entries, pattern(list(entries)), pattern(real) if real else None)",
     "    return Refused(entries, pattern(list(entries)), pattern(list(entries)))", OWNERS),

    ("the real-only list goes empty on every machine — exempt files are never read", SHAPES,
     "    return [(token, what) for token, what in forbidden(root) if token not in synthetic]",
     "    return []", OWNERS),

    # ── the scan's own road: the survivors of 2026-08-26, each killed by the tree twin ─────────
    ("the tracked-tree scan reads EVERY file with the real-only pattern — nothing on a fork",
     OWNERS,
     "        rx = refused.in_exempt if rel in ALLOWED else refused.everywhere",
     "        rx = refused.in_exempt", OWNERS),

    ("…and the prose scan does the same", PAST,
     "        rx = refused.in_exempt if rel in _EXEMPT else refused.everywhere",
     "        rx = refused.in_exempt", PAST),

    ("the tracked-tree scan reads one entry of the list", OWNERS,
     "        rx = refused.in_exempt if rel in ALLOWED else refused.everywhere",
     "        rx = refused.in_exempt if rel in ALLOWED else "
     "identity.pattern(list(refused.entries[1:2]))", OWNERS),

    ("the prose walk drops `.md`", PAST,
     '        if path.suffix not in (".md", ".py", ".yaml", ".yml", ".html", ".tf", ".sh", '
     '".toml",',
     '        if path.suffix not in (".py", ".yaml", ".yml", ".html", ".tf", ".sh", ".toml",',
     PAST),

    ("the prose walk skips docs/", PAST,
     '_SKIP_DIRS = (".git", ".venv", "build", ".secrets", "node_modules", "__pycache__",',
     '_SKIP_DIRS = ("docs", ".git", ".venv", "build", ".secrets", "node_modules", "__pycache__",',
     PAST),

    # ── the scan and its twins share ONE object ────────────────────────────────────────────────
    ("the tracked-tree scan builds its own list beside the shared object — same source, "
     "different object", OWNERS,
     "    refused = identity.refused(root)\n\n    offenders = []",
     "    refused = identity.Refused(tuple(identity.forbidden(root)),\n"
     "                               identity.pattern(identity.forbidden(root)),\n"
     "                               identity.pattern(identity.real_only(root))\n"
     "                               if identity.real_only(root) else None)\n\n    offenders = []",
     OWNERS),

    ("…and so does the prose scan", PAST,
     "    refused = identity.refused(root)\n    what_of = ",
     "    refused = identity.Refused(tuple(identity.forbidden(root)),\n"
     "                               identity.pattern(identity.forbidden(root)),\n"
     "                               identity.pattern(identity.real_only(root))\n"
     "                               if identity.real_only(root) else None)\n    what_of = ",
     PAST),

    ("the shared resolver reads THIS tree's list whatever root it is asked about", SHAPES,
     "    entries = tuple(forbidden(root))\n    real = real_only(root)",
     "    entries = tuple(forbidden())\n    real = real_only()", OWNERS),

    # ── a malformed real list fails the tests that read it, and never collection ──────────────
    ("the owners guard resolves the list at import again", OWNERS, "",
     "\n_EAGER = identity.refused()\n", OWNERS),

    ("…and so does the prose guard", PAST, "",
     "\n_EAGER = identity.refused()\n", OWNERS),

    ("the malformed-list error stops naming the line", SHAPES,
     '            raise ValueError(f"line {n} belongs to no section (expected `forbid:` or "\n'
     '                             f"`must_catch:` first): {raw!r}")',
     '            raise ValueError("the identity list is malformed")', OWNERS),

    # ── the front door is proven to READ the page ──────────────────────────────────────────────
    ("the front door check reads nothing and judges it", PAST,
     "    text = page.read_text()\n    assert text.strip(), ",
     '    text = ""\n    assert text.strip(), ', PAST),

    ("the front door check stops asserting the read", PAST,
     '    assert text.strip(), f"{page} was read as an empty page — nothing here was judged"\n',
     "", PAST),

    ("the front door check judges a constant instead of the page", PAST,
     "    return [what for pattern, what in rules if re.search(pattern, text, re.IGNORECASE)]",
     '    return [what for pattern, what in rules if re.search(pattern, "", re.IGNORECASE)]',
     PAST),

    ("README.md leaves the front door", PAST,
     'FRONT_DOOR = ("README.md", "NOTICE", "docs/ONBOARDING.md", "docs/STATUS.md")',
     'FRONT_DOOR = ("NOTICE", "docs/ONBOARDING.md", "docs/STATUS.md")', PAST),

    # ── the verifier keeps its floor ───────────────────────────────────────────────────────────
    ("the only must_catch line carrying the address is removed (the reviewer's cut)", SHAPES,
     '    "questions to maint@example.invalid",\n', '', OWNERS),

    ("a must_catch line whose token has a second road is removed — the count floor", SHAPES,
     '    "the board lives under https://github.com/ExampleCo/projects/7",\n', '', OWNERS),

    # ── the front door keeps every shape it used to spell as its own rule ──────────────────────
    ("the first-name shape leaves the synthetic list", SHAPES,
     '    ("exampleperson", "a person\'s first name"),\n', '', PAST),

    ("the former-company shape leaves the synthetic list", SHAPES,
     '    ("formerco", "the former parent company"),\n', '', PAST),

    ("the front door stops reading the shared list", PAST,
     "    rules = [*_FRONT_DOOR_RULES, (identity.refused(root).everywhere.pattern, _A_NAME)]",
     "    rules = [*_FRONT_DOOR_RULES]", PAST),

    ("a personal first name is written into the README", "README.md",
     "# OpenFactory", "# OpenFactory\n\nExampleperson decided the board has four columns.", PAST),

    ("the former company comes back in a compound on the README", "README.md",
     "# OpenFactory", "# OpenFactory\n\nThe first version was written at FormerCoAI.", PAST),

    # ── card ids on the surfaces a stranger reads ──────────────────────────────────────────────
    ("a card id comes back on a --help screen", "openfactory/cli.py",
     '    """Run YOUR adapter against the platform\'s conformance suite.\n',
     '    """Run YOUR adapter against the platform\'s conformance suite (C-22).\n', CARDS),

    ("a card id comes back in a conformance finding a third party is shown",
     "openfactory/conformance/adapters.py",
     '                f"items_in_status returned {type(items).__name__} with non-string members",\n'
     '                "int refs collapse CONT-412 and PROJ-412 into one ticket (a bug found live)"))',
     '                f"items_in_status returned {type(items).__name__} with non-string members",\n'
     '                "int refs collapse CONT-412 and PROJ-412 into one ticket (#69\'s live bug)"))',
     CARDS),

    ("a card id comes back in a log line", "openfactory/runtime/temporal/activities.py",
     '                "`staging_url`, which is deprecated", project.name, issue)',
     '                "`staging_url`, which is deprecated (#122)", project.name, issue)', CARDS),

    ("the sweep's pattern stops matching the older scheme", CARDS,
     'CARD_ID = re.compile(r"#\\d{2,3}\\b|C-\\d{2}\\b")',
     'CARD_ID = re.compile(r"#\\d{2,3}\\b|C-\\d{4}\\b")', CARDS),

    ("the sweep's pattern stops matching the later scheme", CARDS,
     'CARD_ID = re.compile(r"#\\d{2,3}\\b|C-\\d{2}\\b")',
     'CARD_ID = re.compile(r"#\\d{5}\\b|C-\\d{2}\\b")', CARDS),

    ("the help sweep walks no subcommands", CARDS,
     "        for name, sub in getattr(cmd, \"commands\", {}).items():\n            walk(sub, [*path, name])",
     "        for name, sub in ():\n            walk(sub, [*path, name])", CARDS),

    # ── the extensibility document names the group that exists ─────────────────────────────────
    ("the document goes back to the group the loader never reads", DOC,
     '[project.entry-points."openfactory.adapters"]\n"forge.gitea"',
     '[project.entry-points."openfactory.forge"]\n"forge.gitea"', DOCGUARD),

    ("the document names no group at all", DOC,
     '[project.entry-points."openfactory.adapters"]\n"forge.gitea"',
     '"forge.gitea"', DOCGUARD),

    # RE-AIMED 2026-08-26: §2 was rewritten when every registry was wired, so both anchors moved.
    # The sentence that told a stranger not to try is now the history clause; the axis list is now
    # seventeen names across two wrapped lines. Same two defects, aimed at today's sentences.
    ("the document tells a stranger there is nowhere to register", DOC,
     "editing the file, and `pyproject.toml` declared one console script and no plugin group. That\nis history.",
     "editing the file, so an add-on has nowhere to register itself.",
     DOCGUARD),

    ("the document claims an axis the registries do not ask the loader for", DOC,
     "  `harness`, `identity`, `metrics`, `notifier`, `role`, `session_store`, `token_pool` and\n  `tracker` —",
     "  `harness`, `identity`, `metrics`, `notifier`, `role`, `sandbox`, `session_store`,\n  `token_pool` and `tracker` —",
     DOCGUARD),

    ("the doctrine exclusion grows to swallow the extensibility document", DOCGUARD,
     'HISTORY = ("docs/adr/",)', 'HISTORY = ("docs/adr/", "docs/core/")', DOCGUARD),

    # ── the ledger checks its vendor side both ways ────────────────────────────────────────────
    # RE-AIMED 2026-08-26: the ledger's rows gained their `leaves`/`stays` mark with the public
    # cut, so an anchor ending at the path matched nothing and this cut stopped applying.
    ("a phantom vendor entry — a file that does not exist", DOC,
     "  - openfactory/adapters/tracker/jira.py            # stays\n",
     "  - openfactory/adapters/tracker/jira.py            # stays\n"
     "  - openfactory/adapters/tracker/gitea.py           # stays\n",
     LEDGER),

    ("a core module imports a vendor-owned module by path, unlisted",
     "openfactory/orchestrator/merge_policy.py", "",
     "\n\ndef _planted():\n    from openfactory.adapters.github_app import mint_installation_token\n"
     "    return mint_installation_token\n", LEDGER),

    # RE-AIMED 2026-08-26: nine entries left `mixed_modules` when the API budget became a question
    # on the tracker port and the forge credential a row on the credential registry. One remains,
    # and it is the subject both cuts now use — the list they used to aim at is paid debt.
    ("a mixed entry is dropped while its import stays", DOC,
     "  - openfactory/cli.py                          # adapters/github_app — `bot-token`, the deployment-level proof of the App trio (docs/setup/github.md)\n",
     "", LEDGER),

    ("a mixed entry whose module reaches no vendor — paid debt left on the list", DOC,
     "mixed_modules:\n",
     "mixed_modules:\n  - openfactory/orchestrator/merge_policy.py    # planted\n", LEDGER),

    ("the by-path scan goes blind", LEDGER,
     '            hits.add(f"path:{name}")',
     '            pass', LEDGER),

    # RE-AIMED 2026-08-26: `session_store.py` left `ALLOWED_IMPORTERS` when the AWS cut turned it
    # into a registry row, so the anchor named a key that is no longer there.
    ("an allowed importer is exempted although it imports nothing", LEDGER,
     '    "openfactory/adapters/board/factory.py":',
     '    "openfactory/orchestrator/merge_policy.py":', LEDGER),

    ("the registry exemption widens to every file under adapters/", LEDGER,
     '_REGISTRY = re.compile(r"openfactory/adapters/[^/]+/registry\\.py")',
     '_REGISTRY = re.compile(r"openfactory/adapters/.*\\.py")', LEDGER),

    # ── the build floor can build the package ──────────────────────────────────────────────────
    ("the floor goes back to a setuptools that refuses the licence expression", "pyproject.toml",
     'requires = ["setuptools>=77"]', 'requires = ["setuptools>=68"]', WHEEL),

    ("a broken [project] table — the build fails on OUR metadata and must not skip",
     "pyproject.toml",
     'license-files = ["LICENSE", "NOTICE"]', 'license-files = "LICENSE"', WHEEL),

    ("the skip allowlist widens to swallow a configuration error", WHEEL,
     '    r"No module named pip", re.IGNORECASE)',
     '    r"No module named pip|configuration error", re.IGNORECASE)', WHEEL),
]
