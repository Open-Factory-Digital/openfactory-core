"""Mutation plan for the review round of the chat cut (2026-08-26): the doctor's fallback line,
the `addons/` row as the public-tree signal, CI linting what the gate lints, no staying document
linking a leaving one, and the deployment renderer asking the rows for their variables.

Point-in-time proof; anchors rot as code moves and fail loudly on rerun.
"""

TEST = "tests/test_the_doctor_says_where_project_less_speech_goes.py"
CUT = "tests/test_the_public_cut_is_written_down.py"
CI = "tests/test_ci_runs_what_we_run.py"
ROWS = "tests/test_the_deployment_asks_the_rows_for_their_variables.py"
SURVEY = "tests/test_onboarding_backfills_the_context.py"

MUTATIONS = [
    # ── finding 1: the doctor's line ────────────────────────────────────────────────────────────
    ("the state ignores the declaration",
     "openfactory/adapters/notify/registry.py",
     "    kind = fallback_kind()\n    installed, unserviceable = _candidates()",
     '    kind = ""\n    installed, unserviceable = _candidates()'),
    ("the state reports no installed candidate",
     "openfactory/adapters/notify/registry.py",
     "    installed, unserviceable = _candidates()\n    if not kind:",
     "    installed, unserviceable = (), ()\n    if not kind:"),
    # ── the re-review: an offered option must be executable ─────────────────────────────────────
    ("a per-project row is offered as the deployment-wide fallback",
     "openfactory/adapters/notify/registry.py",
     "    answer = _row_answer(kind, None, builder)\n    if not isinstance(answer, CannotPost):\n"
     '        return ""',
     '    return ""\n    answer = _row_answer(kind, None, builder)\n'
     '    if not isinstance(answer, CannotPost):\n        return ""'),
    ("a row that declares nothing is offered on the strength of an env-shaped word",
     "openfactory/adapters/notify/registry.py",
     "    declared = set(plugins.environment(builder))",
     "    declared = set(_ENV_SHAPED.findall(' '.join(answer.missing)))"),
    ("the doctor drops the sentence for a row a project-less caller cannot use",
     "openfactory/doctor.py",
     "    for kind, need in s.unserviceable:", "    for kind, need in ():"),
    ("the deployment-wide row declares nothing",
     "openfactory/adapters/notify/telegram.py",
     "build.environment = (BOT_TOKEN_ENV, CHAT_ID_ENV)\n", "build.environment = ()\n", ROWS),
    ("a declared row that cannot post is reported as posting",
     "openfactory/adapters/notify/registry.py",
     '    lacked = _lacked(answer) if isinstance(answer, CannotPost) else ""',
     '    lacked = ""'),
    ("the line drops the remedy for an installed, undeclared notifier",
     "openfactory/doctor.py",
     "    if s.installed:\n        kinds = ", "    if False:\n        kinds = "),
    ("the none-declared line stops saying where project-less speech goes",
     "openfactory/doctor.py",
     '    line = "notifier fallback: none declared — project-less notifications go nowhere"',
     '    line = "notifier fallback: none declared — the panel is the last resort"'),
    ("the uninstalled-kind line drops the package to install",
     "openfactory/doctor.py",
     '                f"{plugins.install_hint(AXIS, s.declared)}; project-less notifications go "',
     '                f"; project-less notifications go "'),
    ("the CLI stops printing the line",
     "openfactory/cli.py",
     '    typer.echo(f"· {doc.notifier_fallback_line()}")',
     '    pass'),
    ("STATUS's behaviour-change paragraph stops naming the variable to declare",
     "docs/STATUS.md",
     "`OPENFACTORY_NOTIFIER_FALLBACK=telegram` declares it (with `openfactory-slack` installed). A",
     "the fallback declaration names it (with `openfactory-slack` installed). A"),
    # ── the dev extra is this tree's suite, not a vendor's ──────────────────────────────────────
    ("the core's dev extra carries a cloud SDK again",
     "pyproject.toml",
     '    "temporalio>=1.7",\n    "pytest-randomly>=3.15",',
     '    "temporalio>=1.7",\n    "boto3>=1.34",\n    "pytest-randomly>=3.15",',
     "tests/test_the_core_addon_ledger.py"),
    # ── finding 2: the signal is a row ──────────────────────────────────────────────────────────
    ("STATUS loses the addons/ row while four guards test for that path",
     "docs/STATUS.md",
     "| `addons/` | the add-on packages themselves — each is built from this tree into its own wheel and installed beside the core; private, and the documents of the deployment a package carries live under its own `docs/` |\n",
     "", CUT),
    # ── finding 3: CI lints what the gate lints ─────────────────────────────────────────────────
    ("the Makefile's lint line drops the add-on packages",
     "Makefile",
     "\truff check openfactory/ tests/ $(wildcard addons)\n",
     "\truff check openfactory/ tests/\n", CI),
    ("CI stops running the linter",
     ".github/workflows/ci.yml",
     "      - run: make lint\n", "      - run: make help\n", CI),
    # ── residue (i): a staying document links a leaving one ─────────────────────────────────────
    ("the contributor's page links the walkthrough that left with the cloud package",
     "CONTRIBUTING.md",
     "| [docs/STATUS.md](docs/STATUS.md) | what is proven end to end and what is not |",
     "| [docs/STATUS.md](docs/STATUS.md) | what is proven end to end and what is not |\n"
     "| [the cloud walkthrough](addons/openfactory-aws/docs/DEPLOYMENT.md) | deploying |", CUT),
    # ── residue (ii): the survey stops reporting unread code ────────────────────────────────────
    ("the survey reports no unread code at all",
     "openfactory/onboarding/context.py",
     "        counts[suffix] = counts.get(suffix, 0) + 1\n    return sorted(counts, key=lambda s: (-counts[s], s))",
     "        pass\n    return sorted(counts, key=lambda s: (-counts[s], s))",
     SURVEY + "::test_it_surveys_this_repository_and_finds_its_own_vocabulary"),
    # ── residue (iii): the renderer asks the rows ───────────────────────────────────────────────
    ("the core spells the chat package's variable again",
     "openfactory/onboarding/deployment.py",
     '    rows = "".join(f"{name}=\\n" for name in names)',
     '    rows = "SLACK_BOT_TOKEN=\\n" + "".join(f"{name}=\\n" for name in names)', ROWS),
    ("the reviewer's cut: a module-level name holds the chat variable (the scan must see the string)",
     "openfactory/onboarding/deployment.py",
     "def _channel_block(kind: str, out: Rendered) -> str:",
     'SLACK_BOT_TOKEN = "SLACK_BOT_TOKEN"\n\n\ndef _channel_block(kind: str, out: Rendered) -> str:',
     ROWS),
    ("a split string walks the source scan — the rendered rows are held equal to the declaration",
     "openfactory/onboarding/deployment.py",
     '    rows = "".join(f"{name}=\\n" for name in names)',
     '    rows = "SLACK_BOT" + "_TOKEN=\\n" + "".join(f"{name}=\\n" for name in names)', ROWS),
    ("the renderer ignores what the row declares",
     "openfactory/onboarding/deployment.py",
     "    names = plugins.environment(builder)\n    if not names:",
     "    names = ()\n    if not names:", ROWS),
    ("the contract answers nothing for every row",
     "openfactory/plugins.py",
     "    names = declared() if callable(declared) else declared\n    return tuple(str(n) for n in names)",
     "    return ()", ROWS),
    ("the chat row declares nothing",
     "openfactory/adapters/channel/slack.py",
     "build.environment = environment\n",
     "build.environment = lambda: ()\n", ROWS),
    ("the chat row keeps a table instead of deriving",
     "openfactory/adapters/channel/slack.py",
     "    return tuple(sorted(n for n in read if not n.startswith(environ.ENV_PREFIX)))",
     '    return ("SLACK_BOT_TOKEN",)', ROWS),
    ("names_read stops accepting one file",
     "openfactory/environ.py",
     '    paths = [base] if base.is_file() else sorted(base.rglob("*.py"))',
     '    paths = sorted(base.rglob("*.py"))', ROWS),
]
