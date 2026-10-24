"""No command of the command line writes the installation but through a row, and every installation
row is the mapping of a command (#741, slice 4), proven by breaking it.

Run:  .venv/bin/python tools/mutate.py \
        tools/mutations/741d_every_installation_verb_goes_through_a_row.py

Each row is aimed at the one test that must see it, so a red is that test's and not a neighbour's.
The claims, each a group of rows:

  1. a command that is no mapping at all and writes the installation is seen — through an instance
     built inline, a name bound to one, the people store, the schedule's hold reached as the
     module's attribute, and a row's runner called without the door;
  2. a write is seen past the command's own instance, in each shape `_reaches` says it reads — the
     five an independent review put in `cli.py` (a registry handed to a helper, one a helper
     returned, a class's method, `catalog.CATALOG["enable"].run(...)`, `import openfactory.x as
     y`) and each other step the reading takes: a registry handed by name, through a thread, by a
     parameter's annotation, by `registry or ProjectRegistry()`, a module imported whole, a writer
     on another object's attribute by a name only the registry has, and a row's runner taken off
     the catalogue by `.get`, by a loop over its items and by `actions.spec`;
  3. every command that maps onto an installation row is seen the day it writes the installation
     itself again, beside its row — sixteen commands, `onboard` twice: from the command, and from
     the onboarding module it calls;
  4. `onboard` creates the context repository through `product_init`, backfills the project as
     re-read, and says what it made;
  5. the walk is held to the app: a group it loses, a walk that stops at the root, a command whose
     body it cannot read and a function shadowed by another of its name are each seen;
  6. the door is `perform`: a shell that runs its rows without it is seen by the positive twin
     (and, since claim 2's reading, by the guard too, which reads `CATALOG[name].run(...)` as
     every row's runner);
  7. the catalogue a front end reads says which rows are the installation's.

The schedule's hold reached as the module's attribute (claim 1) is red only because the reading
enters the schedule's pausing functions (slice 4); without that, the walk saw a hold by its name
alone and this row survived. Each of claim 2's rows passed the walk the review was made on
(`191a9fdc`).
"""

TEST = "tests/test_the_installation_is_changed_through_its_rows.py"
GUARD = TEST + "::test_no_command_writes_the_installation_but_through_a_row"
WALK = TEST + "::test_the_walk_reaches_every_command_the_app_registers_and_reads_each_body"
TWIN = TEST + "::test_every_installation_row_is_the_mapping_of_a_command"
RECORDER = (TEST + "::test_onboard_creates_a_context_repository_through_its_row_and_writes_"
                   "nothing_itself")
ONBOARD_TEST = ("tests/test_onboard_builds_the_context_too.py::"
                "test_onboard_creates_an_undeclared_context_repo_through_its_row_and_rereads_the_project")

CLI = "openfactory/cli.py"
ONBOARDING = "openfactory/onboarding/onboard.py"
API = "openfactory/api/app.py"

#: The end of `cli.py`, where each of claim 2's commands is added.
MAIN = 'if __name__ == "__main__":\n    app()\n'

MUTATIONS = [
    # ── 1. a command that is no mapping writes the installation ─────────────────────────────────
    ("`project show` sets a project's language through an instance built inline", CLI,
     '    typer.echo(json.dumps(project.model_dump(mode="json", exclude_none=True), indent=2))\n',
     '    ProjectRegistry().set_language(name, "en")\n'
     '    typer.echo(json.dumps(project.model_dump(mode="json", exclude_none=True), indent=2))\n',
     GUARD),
    ("`project list` removes a project through a name bound to the registry", CLI,
     "    for p in ProjectRegistry().list():\n",
     "    registry = ProjectRegistry()\n"
     '    registry.remove("acme")\n'
     "    for p in ProjectRegistry().list():\n",
     GUARD),
    ("`people list` invites somebody through the store it bound", CLI,
     "    store = _people.PeopleStore()\n    try:\n        registered = store.people()\n",
     "    store = _people.PeopleStore()\n"
     '    store.invite("someone@acme.example", by="shell")\n'
     "    try:\n        registered = store.people()\n",
     GUARD),
    ("`poller status` holds the schedule through the module's attribute", CLI,
     "    intake, jobs = _poller_reading()\n    _describe_intake(intake)\n",
     "    import asyncio\n\n"
     "    from openfactory.runtime.temporal import schedule\n\n"
     '    asyncio.run(schedule.hold_poller(on=False, note="held while reading"))\n'
     "    intake, jobs = _poller_reading()\n    _describe_intake(intake)\n",
     GUARD),
    ("`product status` calls a row's runner itself, without the door", CLI,
     '    outcome = _perform("product_status", project=name)\n',
     "    import asyncio\n\n"
     "    from openfactory.actions import catalog\n\n"
     '    asyncio.run(catalog._product_name(project=name, by=None, agent_name="Ana"))\n'
     '    outcome = _perform("product_status", project=name)\n',
     GUARD),

    # ── 2. past the command's own instance: each shape the walk reads ───────────────────────────
    ("a command hands a registry to a helper that writes through its parameter", CLI,
     MAIN,
     "def _switch_off(registry, name):\n"
     "    registry.set_enabled(name, False)\n\n\n"
     '@app.command("switch-off")\n'
     "def switch_off_cmd(name: str) -> None:\n"
     "    _switch_off(ProjectRegistry(), name)\n\n\n" + MAIN,
     GUARD),
    ("a command hands a registry to a helper by the parameter's name", CLI,
     MAIN,
     "def _switch_off(name, registry):\n"
     "    registry.set_enabled(name, False)\n\n\n"
     '@app.command("switch-off")\n'
     "def switch_off_cmd(name: str) -> None:\n"
     "    _switch_off(name=name, registry=ProjectRegistry())\n\n\n" + MAIN,
     GUARD),
    ("a command writes through the registry a helper returned", CLI,
     MAIN,
     "def _the_registry():\n"
     "    return ProjectRegistry()\n\n\n"
     '@app.command("switch-off")\n'
     "def switch_off_cmd(name: str) -> None:\n"
     "    registry = _the_registry()\n"
     "    registry.set_enabled(name, False)\n\n\n" + MAIN,
     GUARD),
    ("a command writes through a method of a class of its module, which calls another on `self`",
     CLI, MAIN,
     "class _Switch:\n"
     "    def off(self, name):\n"
     "        self._write(name)\n\n"
     "    def _write(self, name):\n"
     "        ProjectRegistry().set_enabled(name, False)\n\n\n"
     '@app.command("switch-off")\n'
     "def switch_off_cmd(name: str) -> None:\n"
     "    _Switch().off(name)\n\n\n" + MAIN,
     GUARD),
    ("a command calls a row's runner off the catalogue by the row's name, without the door", CLI,
     MAIN,
     '@app.command("switch-off")\n'
     "def switch_off_cmd(name: str) -> None:\n"
     "    from openfactory.actions import catalog\n\n"
     '    asyncio.run(catalog.CATALOG["enable"].run(project=name, enabled=False))\n\n\n' + MAIN,
     GUARD),
    ("a command creates a context repository through a module it imported under another name", CLI,
     MAIN,
     '@app.command("make-context")\n'
     "def make_context_cmd(name: str) -> None:\n"
     "    import openfactory.product.onboard as context\n\n"
     "    context.create_context_repository(_get_project(name), name)\n\n\n" + MAIN,
     GUARD),
    ("a command creates a context repository through a module it imported whole", CLI,
     MAIN,
     '@app.command("make-context")\n'
     "def make_context_cmd(name: str) -> None:\n"
     "    import openfactory.product.onboard\n\n"
     "    openfactory.product.onboard.create_context_repository(_get_project(name), name)\n\n\n"
     + MAIN,
     GUARD),
    ("a command hands a registry on with the helper a thread runs", CLI,
     MAIN,
     "def _switch_off(registry, name):\n"
     "    registry.set_enabled(name, False)\n\n\n"
     '@app.command("switch-off")\n'
     "def switch_off_cmd(name: str) -> None:\n"
     "    asyncio.run(asyncio.to_thread(_switch_off, ProjectRegistry(), name))\n\n\n" + MAIN,
     GUARD),
    ("a helper writes through a parameter annotated as the registry, handed one from a tuple", CLI,
     MAIN,
     "def _switch_off(name: str, registry: ProjectRegistry) -> None:\n"
     "    registry.set_enabled(name, False)\n\n\n"
     '@app.command("switch-off")\n'
     "def switch_off_cmd(name: str) -> None:\n"
     "    for registry in (ProjectRegistry(),):\n"
     "        _switch_off(name, registry)\n\n\n" + MAIN,
     GUARD),
    ("a helper writes through `registry or ProjectRegistry()`", CLI,
     MAIN,
     "def _switch_off(name, registry=None):\n"
     "    registry = registry or ProjectRegistry()\n"
     "    registry.set_enabled(name, False)\n\n\n"
     '@app.command("switch-off")\n'
     "def switch_off_cmd(name: str) -> None:\n"
     "    _switch_off(name)\n\n\n" + MAIN,
     GUARD),
    ("a command sets a language through a registry held on another object", CLI,
     MAIN,
     '@app.command("set-english")\n'
     "def set_english_cmd(name: str) -> None:\n"
     "    from types import SimpleNamespace\n\n"
     "    held = SimpleNamespace(registry=ProjectRegistry())\n"
     '    held.registry.set_language(name, "en")\n\n\n' + MAIN,
     GUARD),
    ("a command runs the row it is given off the catalogue's `.get`, without the door", CLI,
     MAIN,
     '@app.command("run-row")\n'
     "def run_row_cmd(row: str) -> None:\n"
     "    from openfactory import actions as act_layer\n\n"
     "    found = act_layer.CATALOG.get(row)\n"
     "    asyncio.run(found.run())\n\n\n" + MAIN,
     GUARD),
    ("a command runs every row off the catalogue's items, without the door", CLI,
     MAIN,
     '@app.command("run-rows")\n'
     "def run_rows_cmd() -> None:\n"
     "    from openfactory.actions import CATALOG\n\n"
     "    for _name, found in CATALOG.items():\n"
     "        asyncio.run(found.run())\n\n\n" + MAIN,
     GUARD),
    ("a command runs a row found by `actions.spec`, without the door", CLI,
     MAIN,
     '@app.command("run-row")\n'
     "def run_row_cmd(row: str) -> None:\n"
     "    from openfactory import actions as act_layer\n\n"
     "    asyncio.run(act_layer.spec(row).run())\n\n\n" + MAIN,
     GUARD),

    # ── 3. each mapped command writes the installation itself again, beside its row ─────────────
    ("`project add` registers the project itself", CLI,
     '    outcome = _perform("project_add", project=name, repo_path=repo_path,\n',
     "    from openfactory.contracts.project import Project\n"
     "    ProjectRegistry().add(Project(name=name, repo_path=repo_path))\n"
     '    outcome = _perform("project_add", project=name, repo_path=repo_path,\n',
     GUARD),
    ("`project set-model` saves the model itself", CLI,
     '    outcome = _perform("project_set_model", project=name, model=model, role=role or "")\n',
     "    ProjectRegistry().set_model(name, model, role=role)\n"
     '    outcome = _perform("project_set_model", project=name, model=model, role=role or "")\n',
     GUARD),
    ("`project set-language` saves the language itself", CLI,
     '    _says_the_row(_perform("project_set_language", project=name, language=language), '
     'name)\n',
     "    ProjectRegistry().set_language(name, language)\n"
     '    _says_the_row(_perform("project_set_language", project=name, language=language), '
     'name)\n',
     GUARD),
    ("`project set-preview` saves the policy itself", CLI,
     '    outcome = _perform("project_set_preview", project=name, required=required, '
     'hours=hours,\n',
     "    ProjectRegistry().set_preview(name, {})\n"
     '    outcome = _perform("project_set_preview", project=name, required=required, '
     'hours=hours,\n',
     GUARD),
    ("`project remove` unregisters the project itself", CLI,
     '    outcome = _perform("project_remove", project=name)\n',
     "    ProjectRegistry().remove(name)\n"
     '    outcome = _perform("project_remove", project=name)\n',
     GUARD),
    ("`project init` attaches the board itself", CLI,
     '    outcome = _perform("project_init", project=name, repo_path=repo_path or "", '
     'repo=repo or "",\n',
     '    ProjectRegistry().attach_board(name, board_owner=board_owner or "", board_number="1")\n'
     '    outcome = _perform("project_init", project=name, repo_path=repo_path or "", '
     'repo=repo or "",\n',
     GUARD),
    ("`poller pause` holds the schedule itself", CLI,
     '    outcome = _perform("poller_pause", note=reason)\n',
     "    import asyncio\n\n"
     "    from openfactory.runtime.temporal.schedule import hold_poller\n\n"
     "    asyncio.run(hold_poller(on=False, note=reason))\n"
     '    outcome = _perform("poller_pause", note=reason)\n',
     GUARD),
    ("`poller resume` lifts the hold itself", CLI,
     '    outcome = _perform("poller_resume", note=reason)  # the',
     "    import asyncio\n\n"
     "    from openfactory.runtime.temporal.schedule import hold_poller\n\n"
     "    asyncio.run(hold_poller(on=True, note=reason))\n"
     '    outcome = _perform("poller_resume", note=reason)  # the',
     GUARD),
    ("`people invite` mints the invitation itself", CLI,
     "    voucher = by.strip() or getpass.getuser()\n",
     "    voucher = by.strip() or getpass.getuser()\n"
     "    from openfactory.identity import people as _people\n"
     "    _people.PeopleStore().invite(person, by=voucher)\n",
     GUARD),
    ("`people revoke` withdraws the person itself", CLI,
     '    outcome = _perform("people_revoke", person=person)\n',
     "    from openfactory.identity import people as _people\n"
     "    _people.PeopleStore().withdraw(person, by=_shell_user())\n"
     '    outcome = _perform("people_revoke", person=person)\n',
     GUARD),
    ("`product start` starts the product itself, through the module its row calls", CLI,
     '    outcome = _perform("product_start", project=name, docs_repo=docs_repo,\n',
     "    from openfactory.product import before_code\n"
     "    before_code.start_before_code(name, docs_repo)\n"
     '    outcome = _perform("product_start", project=name, docs_repo=docs_repo,\n',
     GUARD),
    ("`product first-source` records the code itself, through the module its row calls", CLI,
     '    outcome = _perform("product_first_source", project=name, repo_path=repo_path,\n',
     "    from openfactory.product import before_code\n"
     "    before_code.first_source(name, repo_path)\n"
     '    outcome = _perform("product_first_source", project=name, repo_path=repo_path,\n',
     GUARD),
    ("`product name` names the product role itself", CLI,
     '    outcome = (_perform("product_name", project=name) if agent_name is None\n',
     '    ProjectRegistry().set_agent_name(name, agent_name or "")\n'
     '    outcome = (_perform("product_name", project=name) if agent_name is None\n',
     GUARD),
    ("`product declare` records the context repository itself", CLI,
     '    outcome = _perform("product_declare", project=name, docs_repo=docs_repo)\n',
     "    ProjectRegistry().set_docs_repo(name, docs_repo)\n"
     '    outcome = _perform("product_declare", project=name, docs_repo=docs_repo)\n',
     GUARD),
    ("`product init` creates the context repository itself", CLI,
     '    outcome = _perform("product_init", project=name, source=list(source or []), '
     'write=write,\n',
     "    from openfactory.product.onboard import create_context_repository\n"
     "    create_context_repository(_get_project(name), name)\n"
     '    outcome = _perform("product_init", project=name, source=list(source or []), '
     'write=write,\n',
     GUARD),
    ("`onboard` creates the context repository itself", CLI,
     '    outcome = _perform("product_init", project=name, create_context=True)\n',
     "    from openfactory.product.onboard import create_context_repository\n"
     "    create_context_repository(project, name)\n"
     '    outcome = _perform("product_init", project=name, create_context=True)\n',
     GUARD),
    ("the onboarding module creates the context repository again, as it did before this slice",
     ONBOARDING,
     "    if not docs_repo:\n"
     "        out.detail = (f\"{getattr(project, 'name', 'this project')} declares no context \"\n",
     "    if not docs_repo:\n"
     "        from openfactory.product.onboard import create_context_repository\n\n"
     "        docs_repo, out.created = create_context_repository(\n"
     "            project, getattr(project, \"name\", \"product\"))\n"
     "    if not docs_repo:\n"
     "        out.detail = (f\"{getattr(project, 'name', 'this project')} declares no context \"\n",
     GUARD),

    # ── 4. onboard through product_init ─────────────────────────────────────────────────────────
    ("`onboard` backfills the project it held before the repository was made", CLI,
     '    return _get_project(name), context["state"] == STEP_DONE, ""\n',
     '    return project, context["state"] == STEP_DONE, ""\n',
     ONBOARD_TEST),
    ("`onboard` never says it created the repository", CLI,
     '    return _get_project(name), context["state"] == STEP_DONE, ""\n',
     '    return _get_project(name), False, ""\n',
     RECORDER),

    # ── 5. the walk is held to the app ──────────────────────────────────────────────────────────
    ("the walk loses a command group", TEST,
     "            for name, sub in sorted(subs.items()):\n"
     "                yield from walk(sub, (*words, name))\n",
     "            for name, sub in sorted(subs.items()):\n"
     '                if name != "product":\n'
     "                    yield from walk(sub, (*words, name))\n",
     WALK),
    ("the walk stops at the root, reading every group as one command", TEST,
     '        subs = getattr(command, "commands", None)\n        if subs:\n',
     '        subs = getattr(command, "commands", None)\n        if subs and not words:\n',
     WALK),
    ("a command whose body the walk cannot read is registered", CLI,
     'if __name__ == "__main__":\n    app()\n',
     'app.command("whisper")(lambda: None)\n\n\nif __name__ == "__main__":\n    app()\n',
     WALK),
    ("a command's function is shadowed by a later one of the same name", CLI,
     'if __name__ == "__main__":\n    app()\n',
     "def project_show(name: str) -> None:\n    return None\n\n\n"
     'if __name__ == "__main__":\n    app()\n',
     WALK),

    # ── 6. the door is perform ──────────────────────────────────────────────────────────────────
    ("the shell runs its rows without `perform` — no question of who acts, no audit line", CLI,
     "    return asyncio.run(act_layer.perform(\n"
     '        name, by=act_layer.Actor(id=who, display=who, via="cli", admin=True), **params))\n',
     "    return asyncio.run(act_layer.CATALOG[name].run(\n"
     '        by=act_layer.Actor(id=who, display=who, via="cli", admin=True), **params))\n',
     TWIN),

    # ── 7. the catalogue says whose a row is ────────────────────────────────────────────────────
    ("the catalogue a front end reads stops saying which rows are the installation's", API,
     '         "installation": s.installation,\n',
     '         "installation": False,\n',
     TEST + "::test_the_catalogue_a_front_end_reads_marks_exactly_the_installation_rows"),
]
