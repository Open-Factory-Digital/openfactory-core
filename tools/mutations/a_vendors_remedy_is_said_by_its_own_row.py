"""What a vendor needs SAID comes from its own row — proven by breaking it (2026-09-19).

#207 moved what a provider is CALLED onto its row; the SENTENCES stayed in generic code, chosen
by kind. `doctor.py::_forge` picked a forge-credential remedy by finding `azure_devops` inside
its own probe's message and gave GitHub's to everybody else — a stranger's forge whose credential
row named `ACME_TOKEN` was sent to create a GitHub App, and a REFUSED credential read "a GitHub
App: grant it access" on every vendor. `_board_coordinates` and `_board_remedy` were `if kind ==`
chains, `product declare` had a likely cause per vendor, `project init` pointed every tracker at
one vendor's recipe, and the cockpit's how-to spelled the three boards that ship.

The rows say them now (`CredentialRow.when_missing` / `when_refused`; `coordinates`,
`when_unreadable`, `setup` and `display_name` on a board's builder; `when_unreadable` on a
forge's), `plugins.sentence` is the one rule for what counts as a declaration, and generic code
asks. A row that says nothing gets a sentence that names no vendor.

FOUR CLAIMS:

  1. **Generic code neither names a vendor to a person nor chooses words by a vendor's kind** —
     #207's parsed rule, taught two more questions, with what is left written down by name.
  2. **A row's own words reach the doctor's real findings, the real command and the payload the
     cockpit draws** — built-in or add-on, found without building the adapter.
  3. **A row that says nothing is degraded honestly**: its own variable where it named one, no
     other vendor's remedy ever, and a test double is not a declaration.
  4. **The shipped rows say what generic code used to spell.**

The guard is `tests/test_a_provider_is_named_by_its_own_row.py`.
"""

TEST = "tests/test_a_provider_is_named_by_its_own_row.py"

DOCTOR = "openfactory/doctor.py"
PLUGINS = "openfactory/plugins.py"
CLI = "openfactory/cli.py"
DOORS = "openfactory/doors.py"
ACTIVITIES = "openfactory/runtime/temporal/activities.py"
CREDENTIALS = "openfactory/credentials.py"
PANEL = "openfactory/api/panel.html"
ROWS = "openfactory/adapters/credential/registry.py"
BOARDS = "openfactory/adapters/board/factory.py"
FORGES = "openfactory/adapters/forge/registry.py"

MUTATIONS = [
    # ── claim 1: generic code says no vendor's words ──────────────────────────────────────────
    ("THE DEFECT ITSELF: the doctor spells one vendor's remedy for a missing credential", DOCTOR,
     '            (ask("when_missing") if ask is not None else "") or credential_missing_remedy(),\n',
     '            "set OPENFACTORY_BOT_TOKEN (a PAT, to try things out) or the GitHub App trio",\n'),

    ("the sentence that is meant to name no vendor names one", DOCTOR,
     '    "names, else its vendor\'s default — has not expired and may read and write this repository")\n',
     '    "names, else its vendor\'s default — has not expired. A GitHub App: grant it access")\n'),

    ("THE DEFECT ITSELF: `product declare` chooses the likely cause by kind again", CLI,
     '    cause = plugins.sentence(forge_row(project), "when_unreadable", "", project)\n',
     '    cause = ("On GitHub specifically: an App installed on \'Only select repositories\' cannot "\n'
     '             "see it.") if "github" in {project.forge.kind, project.tracker.kind} else ""\n'),

    ("`project init` points every tracker at one vendor's recipe again", CLI,
     '                   + (f" ({setup})" if setup else ""))\n',
     '                   + " (azure_devops states: docs/setup/azure-devops.md §3)")\n'),

    ("the door says `as GitHub` to whoever named whichever kind", DOORS,
     "Registering it as one of those is how a credential \"\n",
     "Registering it as GitHub is how a credential \"\n"),

    ("the poll tick's log line explains a fallback by naming two vendors", ACTIVITIES,
     "\"the platform's own 'TO-DO', which is only right for a board that calls it that\",\n",
     "\"'TO-DO', which is right for GitHub and wrong for at least Azure Boards\",\n"),

    ("the page spells the boards that ship, so an add-on's is not in the sentence", PANEL,
     "${esc(hostedBoards)}",
     "GitHub Projects, Azure Boards and Jira"),

    # ── claim 2: the row's own words reach the reader ─────────────────────────────────────────
    ("the remedy probe is never wired, so the real doctor has no row to ask", DOCTOR,
     "        forge_remedy=_forge_remedy,\n",
     ""),

    ("the probe finds the row and never asks it", DOCTOR,
     '        declared = plugins.sentence(row, what, "")\n',
     '        declared = ""\n'),

    ("a refused credential is answered without asking the vendor", DOCTOR,
     '        ((ask("when_refused") if ask is not None else "") or CREDENTIAL_REFUSED_REMEDY)\n',
     "        (CREDENTIAL_REFUSED_REMEDY)\n"),

    ("the row that answers is the forge's only when the project spells a forge", CREDENTIALS,
     '    return _kind_of(forge if getattr(forge, "kind", "") else getattr(project, "tracker", None))\n',
     "    return _kind_of(forge)\n"),

    ("WHICH board is no longer asked of the board's row", DOCTOR,
     '    return plugins.sentence(board_row(project), "coordinates",\n',
     '    return plugins.sentence(None, "coordinates",\n'),

    ("the board's own remedy is no longer asked for", DOCTOR,
     '    return plugins.sentence(board_row(project), "when_unreadable", "", project)\n',
     '    return ""\n'),

    ("only the built-in boards are consulted, so an add-on's words are never read", BOARDS,
     "    return BOARDS.get(kind) or plugins.builder(AXIS, kind, builtin=BOARDS)\n",
     "    return BOARDS.get(kind)\n"),

    ("only the built-in forges are consulted, so an add-on's likely cause is never offered",
     FORGES,
     '    return FORGES.get(kind) or plugins.builder("forge", kind, builtin=FORGES)\n',
     "    return FORGES.get(kind)\n"),

    ("the cockpit lists boards by their registry keys", BOARDS,
     "        names.append(plugins.display_name(row, kind))\n",
     "        names.append(kind)\n"),

    ("`hosted` keeps the board that needs no account, and the page says it twice", BOARDS,
     '        if hosted and not getattr(credential_row(kind), "needs", True):\n',
     "        if False:\n"),

    # ── claim 3: what counts as a declaration, and what silence gets ──────────────────────────
    ("any truthy attribute is a sentence, so a mock row speaks", PLUGINS,
     "    return declared.strip() if isinstance(declared, str) and declared.strip() else default\n",
     "    return str(declared) if declared else default\n"),

    ("a declaration that depends on the project is never asked about it", PLUGINS,
     "    if callable(declared):\n",
     "    if False:\n"),

    ("a row whose words raise is swallowed without a trace", PLUGINS,
     "            log.warning(\"a row's `%s` raised instead of answering; the generic sentence is "
     "said \"\n"
     "                        \"in its place\", what, exc_info=True)\n",
     "            pass\n"),

    ("a row that named its variable and no remedy is not told its own variable", DOCTOR,
     '        return credential_missing_remedy(getattr(row, "env", "") or "")\n',
     '        return ""\n'),

    # ── claim 4: the shipped rows ──────────────────────────────────────────────────────────────
    ("the Azure row loses its words for a refused credential", ROWS,
     '        when_refused=("a PAT: check that it has not expired, that it belongs to this "\n',
     '        when_refused=("" and "a PAT: check that it has not expired, that it belongs to this "\n'),

    ("the GitHub row loses its remedy for a missing credential", ROWS,
     '        when_missing=("set OPENFACTORY_BOT_TOKEN (a PAT, to try things out) or the GitHub App "\n',
     '        when_missing=("" and "set OPENFACTORY_BOT_TOKEN (a PAT, to try things out) or the GitHub App "\n'),

    ("GitHub's board can no longer say which board", BOARDS,
     "_github.coordinates = _github_coordinates\n",
     ""),

    ("Jira's board loses its remedy", BOARDS,
     "_jira.when_unreadable = _jira_unreadable\n",
     ""),

    ("Azure's board loses what setting it up means", BOARDS,
     '_azure_devops.setup = ("its columns are the project\'s work item states: "\n',
     '_azure_devops.setup = ("" and "its columns are the project\'s work item states: "\n'),

    ("the Azure forge loses its likely cause", FORGES,
     "_azure_devops.when_unreadable = (\n",
     "_azure_devops.when_unreadable = \"\" and (\n"),
]
